"""Python reference version of the SAS Viya validation rules (rule version v2.0).

This mirrors viya/cas_job.py and viya/trend_validator_viya.sas so the engines
can be compared. SAS Viya is the system of record; this file exists so the
public demo still works when no Viya session is configured.

v2.0 adds UNLIKELY: a value that is physically implausible in its stated unit
is flagged for human review. It is never converted or "fixed".
"""
from __future__ import annotations
import re
import pandas as pd

RULE_VERSION = "v2.0"
MMOL_TO_MGDL = 18          # teaching convention: 6.0 mmol/L = 108 mg/dL
KNOWN_UNITS = {"mg/dL", "mmol/L"}
# v2 review limits: outside these, the number is unlikely to be in the stated unit
UNLIKELY_MGDL_BELOW = 20      # e.g. 6.4 "mg/dL" is almost certainly mmol/L
UNLIKELY_MMOL_ABOVE = 40      # e.g. 120 "mmol/L" is almost certainly mg/dL
COLUMNS = ["row_id", "user_id", "event_id", "ts_text", "value", "unit"]

REASONS = {
    "TIME": "Timestamp missing, unparsed or without offset",
    "UNIT": "Unknown or missing unit: quarantined, not guessed",
    "MISSING": "No glucose value recorded: kept, not imputed",
    "REPEAT": "Exact repeat of an earlier payload: audit copy kept",
    "CONFLICT": "Same event ID, different payload: needs review",
    "UNLIKELY": "Value unlikely in its stated unit: held for review, not fixed",
}


def clean_input(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce an uploaded or edited table into the data contract's column types."""
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")
    out = df[COLUMNS].copy()
    for c in ["row_id", "user_id", "event_id", "ts_text", "unit"]:
        out[c] = out[c].fillna("").astype(str).str.strip()
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out.reset_index(drop=True)


def _parse_utc(ts: str):
    """Parse ISO 8601 only when an explicit offset (Z or +hh:mm) is present."""
    if not isinstance(ts, str) or not re.search(r"(Z|[+-]\d\d:\d\d)$", ts):
        return pd.NaT
    try:
        return pd.to_datetime(ts, utc=True)
    except (ValueError, TypeError):
        return pd.NaT


def validate(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (derived, exceptions). Raw value and unit are never modified."""
    v = clean_input(raw)
    v["ts_utc"] = v["ts_text"].map(_parse_utc)

    # exact repeats: same user, event, timestamp text, value and unit
    v["_vkey"] = v["value"].fillna(-1e18)
    v = v.sort_values(["user_id", "event_id", "ts_text", "_vkey", "unit", "row_id"])
    v["repeat_payload"] = v.duplicated(["user_id", "event_id", "ts_text", "_vkey", "unit"]).astype(int)

    # conflicts: same user + event with more than one distinct payload
    firsts = v[v["repeat_payload"] == 0].groupby(["user_id", "event_id"]).size()
    conflict_keys = set(firsts[firsts > 1].index)
    v["conflict_event"] = [int((u, e) in conflict_keys) for u, e in zip(v["user_id"], v["event_id"])]

    v["unlikely_unit"] = (((v["unit"] == "mg/dL") & (v["value"] < UNLIKELY_MGDL_BELOW))
                          | ((v["unit"] == "mmol/L") & (v["value"] > UNLIKELY_MMOL_ABOVE))).astype(int)

    rows = []
    for r in v.itertuples(index=False):
        if pd.isna(r.ts_utc):
            rows.append((r.row_id, r.user_id, r.event_id, "TIME"))
        if r.unit not in KNOWN_UNITS:
            rows.append((r.row_id, r.user_id, r.event_id, "UNIT"))
        if pd.isna(r.value):
            rows.append((r.row_id, r.user_id, r.event_id, "MISSING"))
        if r.repeat_payload:
            rows.append((r.row_id, r.user_id, r.event_id, "REPEAT"))
        if r.conflict_event:
            rows.append((r.row_id, r.user_id, r.event_id, "CONFLICT"))
        if r.unlikely_unit:
            rows.append((r.row_id, r.user_id, r.event_id, "UNLIKELY"))
    exceptions = pd.DataFrame(rows, columns=["row_id", "user_id", "event_id", "rule"])
    exceptions["reason"] = exceptions["rule"].map(REASONS)
    exceptions["rule_version"] = RULE_VERSION

    def to_mgdl(row):
        if pd.isna(row["value"]):
            return float("nan")
        if row["unit"] == "mg/dL":
            return float(row["value"])
        if row["unit"] == "mmol/L":
            return round(MMOL_TO_MGDL * row["value"], 1)
        return float("nan")

    v["glucose_mgdl"] = v.apply(to_mgdl, axis=1)
    v["retained"] = (v["glucose_mgdl"].notna() & v["ts_utc"].notna()
                     & (v["repeat_payload"] == 0) & (v["conflict_event"] == 0)
                     & (v["unlikely_unit"] == 0)).astype(int)
    v["rule_version"] = RULE_VERSION
    derived = v.drop(columns="_vkey").sort_values("row_id").reset_index(drop=True)
    return derived, exceptions.sort_values(["row_id", "rule"]).reset_index(drop=True)


def quick_clean(raw: pd.DataFrame) -> pd.DataFrame:
    """A typical default clean-up: drop blanks, drop same user + timestamp, ignore units."""
    q = clean_input(raw).sort_values(["user_id", "ts_text", "row_id"])
    q["drop_missing"] = q["value"].isna()
    q["drop_dupts"] = q.duplicated(["user_id", "ts_text"]) & ~q["drop_missing"]
    q["kept"] = ~(q["drop_missing"] | q["drop_dupts"])
    return q.sort_values("row_id").reset_index(drop=True)


def summarize(raw: pd.DataFrame, derived: pd.DataFrame, quick: pd.DataFrame) -> pd.DataFrame:
    """Mean of logged readings per user under each pipeline."""
    raw = clean_input(raw)
    out = []
    for u in sorted(raw["user_id"].unique()):
        r = raw[raw["user_id"] == u]["value"].dropna()
        q = quick[(quick["user_id"] == u) & quick["kept"]]["value"]
        d = derived[(derived["user_id"] == u) & (derived["retained"] == 1)]["glucose_mgdl"]
        out.append({"user_id": u,
                    "unchecked_n": len(r), "unchecked_mean": r.mean(),
                    "quick_n": len(q), "quick_mean": q.mean(),
                    "validated_n": len(d), "validated_mean": d.mean()})
    return pd.DataFrame(out)


RULE_FOR_FAMILY = {"MISLABEL": "UNLIKELY"}   # answer-key family -> rule that should catch it


def check_reading(value, unit: str, ts_text: str) -> list[dict]:
    """Row-level rules only, for checking one reading the moment it is entered.

    REPEAT and CONFLICT need the user's history, so they run in the batch job.
    """
    one = pd.DataFrame([{"row_id": "NEW", "user_id": "U", "event_id": "E",
                         "ts_text": ts_text, "value": value, "unit": unit}])
    _, exc = validate(one)
    return exc[["rule", "reason"]].to_dict("records")


def score(raw: pd.DataFrame, exceptions: pd.DataFrame, quick: pd.DataFrame,
          truth: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Row-level caught / missed / false alarms, plus validator results by defect family."""
    true_rows = set(truth["row_id"])
    all_rows = set(clean_input(raw)["row_id"])
    flagged = {"Validator v2": set(exceptions["row_id"]),
               "Validator v1": set(exceptions.loc[exceptions["rule"] != "UNLIKELY", "row_id"]),
               "Quick clean": set(quick.loc[~quick["kept"], "row_id"])}
    det = []
    for name, f in flagged.items():
        det.append({"cleaner": name, "caught": len(f & true_rows),
                    "missed": len(true_rows - f), "false_alarms": len((f & all_rows) - true_rows)})
    fam = []
    for family, grp in truth.groupby("family", sort=False):
        t = set(grp["row_id"])
        rule = RULE_FOR_FAMILY.get(family, family)
        p = set(exceptions.loc[exceptions["rule"] == rule, "row_id"])
        fam.append({"family": family, "seeded": len(t), "detected": len(t & p), "missed": len(t - p)})
    return pd.DataFrame(det), pd.DataFrame(fam)
