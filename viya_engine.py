"""Run the validation job on SAS Viya (CAS) through SWAT, and check single
readings through a decision published to SAS Micro Analytic Service (MAS).

Batch (whole history)   : SWAT -> CAS DATA step + FedSQL  (this file, run_in_viya)
Real time (one reading) : REST -> MAS decision built in SAS Intelligent Decisioning
                          (check_reading_mas)

The code here matches viya/trend_validator_viya.sas, which is the version to
run and verify in SAS Studio. Connection settings come from environment
variables or Streamlit secrets (see README); nothing is hard-coded.
"""
from __future__ import annotations
import os
import pandas as pd

RULE_VERSION = "v2.0"
MMOL_TO_MGDL, MGDL_BELOW, MMOL_ABOVE = 18, 20, 40

# ---- the CAS job, in the order it runs ---------------------------------
STEP1 = r"""
data casuser.step1;
  set casuser.tracker_raw;
  length payload $120 ev $20;
  ts_utc  = input(strip(ts_text), ?? e8601dz25.);
  format ts_utc datetime19.;
  payload = cat(strip(user_id), '|', strip(event_id), '|', strip(ts_text), '|',
                strip(put(value, best32.)), '|', strip(unit));
  ev      = cat(strip(user_id), '|', strip(event_id));
run;
"""

IDENTITY = [
    """create table casuser.payloads {options replace=true} as
         select payload, ev, min(row_num) as keep_num
         from casuser.step1 group by payload, ev""",
    """create table casuser.conflicts {options replace=true} as
         select ev, count(*) as n_payloads
         from casuser.payloads group by ev having count(*) > 1""",
    """create table casuser.step3 {options replace=true} as
         select s.*,
                case when s.row_num = p.keep_num then 0 else 1 end as repeat_payload,
                case when c.ev is null then 0 else 1 end           as conflict_event
         from casuser.step1 as s
              inner join casuser.payloads  as p on s.payload = p.payload
              left  join casuser.conflicts as c on s.ev = c.ev""",
]

RULES = rf"""
data casuser.derived(drop=rule reason)
     casuser.exceptions(keep=row_id row_num user_id event_id rule reason rule_version);
  set casuser.step3;
  length rule $8 reason $64 rule_version $8;
  rule_version  = "{RULE_VERSION}";
  glucose_mgdl  = .;
  unlikely_unit = (unit = 'mg/dL'  and not missing(value) and value < {MGDL_BELOW})
               or (unit = 'mmol/L' and not missing(value) and value > {MMOL_ABOVE});
  if missing(ts_utc) then do;
    rule='TIME';     reason='Timestamp missing, unparsed or without offset';            output casuser.exceptions; end;
  if unit not in ('mg/dL','mmol/L') then do;
    rule='UNIT';     reason='Unknown or missing unit: quarantined, not guessed';        output casuser.exceptions; end;
  if missing(value) then do;
    rule='MISSING';  reason='No glucose value recorded: kept, not imputed';             output casuser.exceptions; end;
  if repeat_payload then do;
    rule='REPEAT';   reason='Exact repeat of an earlier payload: audit copy kept';      output casuser.exceptions; end;
  if conflict_event then do;
    rule='CONFLICT'; reason='Same event ID, different payload: needs review';           output casuser.exceptions; end;
  if unlikely_unit then do;
    rule='UNLIKELY'; reason='Value unlikely in its stated unit: held for review, not fixed'; output casuser.exceptions; end;
  if not missing(value) then do;
    if unit = 'mg/dL' then glucose_mgdl = value;
    else if unit = 'mmol/L' then glucose_mgdl = round({MMOL_TO_MGDL} * value, 0.1);
  end;
  retained = (not missing(glucose_mgdl)) and (not missing(ts_utc))
             and repeat_payload = 0 and conflict_event = 0 and unlikely_unit = 0;
  output casuser.derived;
run;
"""

JOB_TEXT = "/* CAS DATA step */" + STEP1 + "\n/* FedSQL */\n" + ";\n\n".join(IDENTITY) + \
           ";\n\n/* CAS DATA step */" + RULES


def viya_available() -> tuple[bool, str]:
    """True when SWAT is installed and a CAS endpoint plus credentials are set."""
    try:
        import swat  # noqa: F401
    except ImportError:
        return False, "SWAT is not installed."
    url = os.environ.get("CAS_URL", "")
    if not url:
        return False, "No CAS_URL set."
    if not (os.environ.get("VIYA_TOKEN") or (os.environ.get("CAS_USER") and os.environ.get("CAS_PW"))):
        return False, "No VIYA_TOKEN or CAS_USER/CAS_PW set."
    return True, url


def _connect():
    import swat
    swat.options.cas.connection_retries = 1        # fail fast in a web app
    swat.options.cas.connection_retry_interval = 2
    url = os.environ["CAS_URL"]
    token = os.environ.get("VIYA_TOKEN")
    if token:                       # SAS Viya 4: an OAuth access token is passed as the password
        return swat.CAS(url, password=token)
    return swat.CAS(url, username=os.environ["CAS_USER"], password=os.environ["CAS_PW"])


def _check(resp, what: str):
    sev = getattr(resp, "severity", 0) or 0
    if sev > 1:
        raise RuntimeError(f"{what} failed in CAS: {getattr(resp, 'status', '')}")
    return resp


def run_in_viya(raw: pd.DataFrame) -> dict:
    """Upload the tracker table to CAS, run the job, and read the results back."""
    conn = _connect()
    log = []
    try:
        conn.loadactionset("dataStep")
        conn.loadactionset("fedSql")
        up = raw.copy()
        up["row_num"] = range(1, len(up) + 1)
        up["unit"] = up["unit"].replace("", " ")
        conn.upload_frame(up, casout={"name": "tracker_raw", "caslib": "casuser", "replace": True})
        _check(conn.dataStep.runCode(code=STEP1), "Parse step")
        log.append("CAS DATA step: step1 created")
        for q in IDENTITY:
            _check(conn.fedSql.execDirect(query=q), "FedSQL")
        log.append("FedSQL: payloads, conflicts, step3 created")
        _check(conn.dataStep.runCode(code=RULES), "Rules step")
        log.append("CAS DATA step: derived and exceptions created")
        derived = conn.CASTable("derived", caslib="casuser").to_frame()
        exceptions = conn.CASTable("exceptions", caslib="casuser").to_frame()
        server = getattr(conn, "_hostname", "") or os.environ.get("CAS_URL", "")
    finally:
        conn.close()
    derived = pd.DataFrame(derived)
    exceptions = pd.DataFrame(exceptions)
    for df in (derived, exceptions):
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].fillna("").astype(str).str.strip()
    derived["retained"] = derived["retained"].astype(int)
    for c in ("repeat_payload", "conflict_event", "unlikely_unit"):
        if c in derived:
            derived[c] = derived[c].astype(int)
    return {"derived": derived.sort_values("row_num").reset_index(drop=True),
            "exceptions": exceptions.sort_values(["row_num", "rule"]).reset_index(drop=True),
            "log": "\n".join(log), "server": server}


# ---- real time: one reading through a MAS decision ----------------------
def mas_available() -> tuple[bool, str]:
    if os.environ.get("VIYA_URL") and os.environ.get("VIYA_TOKEN") and os.environ.get("MAS_MODULE"):
        return True, os.environ["MAS_MODULE"]
    return False, "No published decision configured (VIYA_URL, VIYA_TOKEN, MAS_MODULE)."


def check_reading_mas(value, unit: str, ts_text: str) -> list[str]:
    """Call the Intelligent Decisioning rule set published to MAS for one reading.

    The decision takes value, unit and ts_text and returns `flags`, a
    comma-separated list of rule codes (empty when the reading passes).
    """
    import requests
    base = os.environ["VIYA_URL"].rstrip("/")
    module = os.environ["MAS_MODULE"]
    body = {"inputs": [
        {"name": "value", "value": None if pd.isna(value) else float(value)},
        {"name": "unit", "value": unit},
        {"name": "ts_text", "value": ts_text},
    ]}
    r = requests.post(f"{base}/microanalyticScore/modules/{module}/steps/execute",
                      json=body, timeout=15,
                      headers={"Authorization": f"Bearer {os.environ['VIYA_TOKEN']}",
                               "Content-Type": "application/json"})
    r.raise_for_status()
    outs = {o["name"]: o.get("value") for o in r.json().get("outputs", [])}
    flags = (outs.get("flags") or "").strip()
    return [f.strip() for f in flags.split(",") if f.strip()]
