"""Can You Trust the Trend? A glucose-tracking data validator powered by SAS Viya.

Companion demo for SAS Innovate 2027 (Davoody).
  Batch:     records go to CAS through SWAT; CAS DATA steps and FedSQL apply the rules.
  Real time: one reading at a time goes to a decision published to SAS Micro
             Analytic Service (built in SAS Intelligent Decisioning).
When no SAS Viya connection is configured, a Python copy of the same rules runs
so the public demo always works. The app always says which engine produced the numbers.
"""
from __future__ import annotations
from datetime import date, time
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

from validator import (clean_input, validate, quick_clean, summarize, score, check_reading,
                       RULE_VERSION, COLUMNS, REASONS)
from viya_engine import (viya_available, run_in_viya, mas_available, check_reading_mas,
                         JOB_TEXT)

HERE = Path(__file__).parent
st.set_page_config(page_title="Can You Trust the Trend?", page_icon="📈", layout="wide")

# ============================================================
# Data sources
# ============================================================
TEACHING_DAY = pd.DataFrame({
    "row_id":  ["S1", "S2", "S3", "S4", "S5", "S6"],
    "user_id": ["U001"] * 6,
    "event_id": ["E1", "E2", "E3", "E3", "E4", "E5"],
    "ts_text": ["2026-01-01T08:00:00Z", "2026-01-01T09:00:00Z", "2026-01-01T10:00:00Z",
                "2026-01-01T10:00:00Z", "2026-01-01T11:00:00Z", "2026-01-01T18:00:00Z"],
    "value":   [108, 6, 144, 144, None, 126],
    "unit":    ["mg/dL", "mmol/L", "mg/dL", "mg/dL", "mg/dL", "mg/dL"],
})


@st.cache_data
def load_bank(name: str):
    raw = pd.read_csv(HERE / "data" / f"tracker_{name}.csv", dtype={"unit": str})
    truth_file = "tracker_truth.csv" if name == "testbank" else f"tracker_{name}_truth.csv"
    truth = pd.read_csv(HERE / "data" / truth_file)
    return clean_input(raw), truth


if "added" not in st.session_state:
    st.session_state.added = []

# ============================================================
# Header
# ============================================================
st.title("📈 Can You Trust the Trend?")
st.markdown(
    "A clear glucose chart can still be built on unreliable records. This demo sends tracker "
    "records through a **SAS Viya validation job** (CAS DATA steps and FedSQL) that checks units, "
    "repeated uploads, timestamps, missing values and unlikely values, then shows what the chart "
    "can honestly display. "
    "Companion to Davoody, *SAS Innovate 2027*."
)
st.warning(
    "⚠️ **Educational demonstration only.** All built-in data is synthetic. This app checks "
    "data quality; it does not give medical advice, diagnose, or recommend treatment."
)

# ============================================================
# Sidebar
# ============================================================
st.sidebar.header("1. Choose records")
source = st.sidebar.radio(
    "Data source",
    ["Synthetic test bank (63 rows, known defects)", "Holdout bank (61 rows, unseen)",
     "Six-row teaching day", "Upload a CSV"],
)
truth = None
if source.startswith("Synthetic"):
    raw, truth = load_bank("testbank")
elif source.startswith("Holdout"):
    raw, truth = load_bank("holdout")
elif source.startswith("Six"):
    raw = clean_input(TEACHING_DAY)
else:
    up = st.sidebar.file_uploader("CSV with columns: " + ", ".join(COLUMNS), type="csv")
    if up is None:
        st.info("👈 Upload a CSV, or pick a built-in data source.")
        st.stop()
    try:
        raw = clean_input(pd.read_csv(up, dtype={"unit": str}))
    except ValueError as err:
        st.error(str(err))
        st.stop()

st.sidebar.header("2. Add a reading (optional)")
with st.sidebar.form("add", clear_on_submit=False):
    users = sorted(raw["user_id"].unique())
    a_user = st.selectbox("User", users)
    a_event = st.text_input("Event ID", value=f"NEW{len(st.session_state.added) + 1}",
                            help="Reuse an existing event ID to create a repeat or a conflict.")
    a_day = st.date_input("Date", value=date(2026, 1, 1))
    a_time = st.time_input("Time", value=time(15, 0))
    a_offset = st.checkbox("Include time zone (Z)", value=True)
    a_value = st.text_input("Value (blank = missing)", value="7.5")
    a_unit = st.selectbox("Unit", ["mmol/L", "mg/dL", "(blank)", "mmol", "units"])
    if st.form_submit_button("Add reading"):
        ts = f"{a_day.isoformat()}T{a_time.strftime('%H:%M')}:00" + ("Z" if a_offset else "")
        st.session_state.added.append({
            "row_id": f"N{len(st.session_state.added) + 1:02d}", "user_id": a_user,
            "event_id": a_event.strip(), "ts_text": ts,
            "value": pd.to_numeric(a_value, errors="coerce"),
            "unit": "" if a_unit == "(blank)" else a_unit})
if st.session_state.added:
    st.sidebar.caption(f"{len(st.session_state.added)} added reading(s).")
    if st.sidebar.button("Clear added readings"):
        st.session_state.added = []
        st.rerun()
    raw = clean_input(pd.concat([raw, pd.DataFrame(st.session_state.added)], ignore_index=True))
    truth = None   # the answer key no longer covers the added rows

st.sidebar.header("3. Engine")
ok, cfg = viya_available()
engine = st.sidebar.radio("Run the rules in", ["SAS Viya (CAS)", "Python reference"],
                          index=0 if ok else 1)
if not ok:
    st.sidebar.caption(f"SAS Viya not connected here ({cfg}) See README to connect.")
if engine.startswith("SAS") and not ok:
    st.sidebar.error(f"SAS Viya is not connected here: {cfg} Using the Python reference engine.")
    engine = "Python reference"

# ============================================================
# Run
# ============================================================
sas_log = None
if engine.startswith("SAS"):
    with st.spinner("Running the validation job in CAS..."):
        try:
            res = run_in_viya(raw)
            derived, exceptions, sas_log = res["derived"], res["exceptions"], res["log"]
            engine_label = f"SAS Viya CAS via SWAT ({res['server']})"
        except Exception as err:   # show the failure honestly, then fall back
            st.error(f"The CAS job did not run: {err}. Showing the Python reference engine instead.")
            derived, exceptions = validate(raw)
            engine_label = "Python reference (SAS Viya run failed)"
else:
    derived, exceptions = validate(raw)
    engine_label = "Python reference (same rules as the SAS Viya job)"

quick = quick_clean(raw)
summary = summarize(raw, derived, quick)
st.caption(f"Results computed by: **{engine_label}** · rule version {RULE_VERSION}")

# ============================================================
# Evidence card
# ============================================================
c1, c2, c3, c4 = st.columns(4)
c1.metric("Source rows", len(raw))
c2.metric("Rows with exceptions", exceptions["row_id"].nunique())
c3.metric("Readings retained", int(derived["retained"].sum()))
kept = derived.loc[derived["retained"] == 1, "glucose_mgdl"]
c4.metric("Mean of logged readings", f"{kept.mean():.1f} mg/dL" if len(kept) else "n/a",
          help="Average of the retained readings someone logged. Not a daily or time-weighted average.")

tabs = st.tabs(["📉 Chart", "🚩 Exceptions", "📊 Summary by user"]
               + (["🎯 Detection vs answer key"] if truth is not None else [])
               + ["⚡ Check one reading", "🧾 Records", "🏗️ How it runs on SAS Viya"])

# ---------- Chart ----------
with tabs[0]:
    users = sorted(raw["user_id"].unique())
    cu, cd = st.columns(2)
    sel_user = cu.selectbox("User", users, key="chart_user")
    raw_u = raw[raw["user_id"] == sel_user].copy()
    raw_u["t_plot"] = pd.to_datetime(raw_u["ts_text"].str.replace("Z", "", regex=False),
                                     errors="coerce", format="ISO8601")
    days = sorted(raw_u["t_plot"].dt.date.dropna().unique())
    sel_day = cd.selectbox("Day", days, format_func=lambda d: d.strftime("%d %b %Y"))
    day_raw = raw_u[raw_u["t_plot"].dt.date == sel_day].sort_values("t_plot")
    der_u = derived[(derived["user_id"] == sel_user) & (derived["row_id"].isin(day_raw["row_id"]))]
    ok_rows = der_u[der_u["retained"] == 1].merge(day_raw[["row_id", "t_plot"]], on="row_id")

    fig, axs = plt.subplots(1, 2, figsize=(11, 3.6), sharey=True)
    h = lambda s: s.dt.hour + s.dt.minute / 60
    axs[0].plot(h(day_raw["t_plot"]), day_raw["value"], "-o", color="#dc2626")
    axs[0].set_title("Unchecked: raw numbers, connected", loc="left", fontsize=11)
    axs[1].scatter(h(ok_rows["t_plot"]), ok_rows["glucose_mgdl"], s=60, color="#2563eb", zorder=3)
    axs[1].set_title("Validated: retained readings only (mg/dL)", loc="left", fontsize=11)
    t_ok = sorted(h(ok_rows["t_plot"]))
    for a, b in zip(t_ok, t_ok[1:]):
        if b - a >= 4:
            axs[1].axvspan(a, b, color="#e5e7eb", alpha=0.7, lw=0)
            axs[1].text((a + b) / 2, 0.97, "no readings", transform=axs[1].get_xaxis_transform(),
                        ha="center", va="top", fontsize=8, color="#6b7280")
    for ax in axs:
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 4))
        ax.set_xticklabels([f"{x:02d}:00" for x in range(0, 25, 4)])
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", color="#e5e7eb")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axs[0].set_ylabel("Value as plotted")
    plt.tight_layout()
    st.pyplot(fig)
    day_exc = exceptions[exceptions["row_id"].isin(day_raw["row_id"])]
    if len(day_exc):
        st.markdown("**What the validator did on this day**")
        st.dataframe(day_exc[["row_id", "rule", "reason"]], hide_index=True, width="stretch")
    conv = der_u[(der_u["unit"] == "mmol/L") & der_u["glucose_mgdl"].notna()]
    for r in conv.itertuples():
        st.caption(f"{r.row_id}: {r.value:g} mmol/L converted to {r.glucose_mgdl:g} mg/dL (factor 18).")
    st.caption("Points are never connected: a line would invent readings between them. "
               "Missing values are not plotted and never set to zero.")

# ---------- Exceptions ----------
with tabs[1]:
    st.markdown(f"**{len(exceptions)} row-rule exceptions** on {exceptions['row_id'].nunique()} rows. "
                "A row can have more than one problem.")
    st.dataframe(exceptions, hide_index=True, width="stretch")
    st.download_button("Download exceptions (CSV)", exceptions.to_csv(index=False),
                       "exceptions.csv", "text/csv")

# ---------- Summary ----------
with tabs[2]:
    show = summary.copy()
    for c in ["unchecked_mean", "quick_mean", "validated_mean"]:
        show[c] = show[c].map(lambda v: f"{v:.1f}")
    show.columns = ["User", "Unchecked n", "Unchecked mean", "Quick clean n", "Quick clean mean",
                    "Validated n", "Validated mean (mg/dL)"]
    st.dataframe(show, hide_index=True, width="stretch")
    st.caption("Unchecked averages every number as written, ignoring units. Quick clean drops blanks "
               "and any second record at the same timestamp, and still ignores units. Validated uses "
               "the SAS rules.")

ti = 3
# ---------- Detection ----------
if truth is not None:
    with tabs[ti]:
        det, fam = score(raw, exceptions, quick, truth)
        bank = "holdout bank (built after the rules were frozen)" if source.startswith("Holdout") \
            else "test bank"
        st.markdown(f"The {bank} has **{len(set(truth['row_id']))} seeded defects** with known answers, "
                    "plus genuine readings that share a timestamp (a trap for careless cleaners).")
        st.dataframe(det, hide_index=True, width="stretch")
        fig2, ax2 = plt.subplots(figsize=(7.5, 3))
        x = range(3)
        series = [("Quick clean", "#d97706"), ("Validator v1", "#93c5fd"), ("Validator v2", "#2563eb")]
        w = 0.26
        for i, (name, col) in enumerate(series):
            row = det[det["cleaner"] == name].iloc[0]
            vals = [row["caught"], row["missed"], row["false_alarms"]]
            bars = ax2.bar([p + (i - 1) * w for p in x], vals, w, color=col, label=name)
            for b in bars:
                ax2.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.3, int(b.get_height()),
                         ha="center", fontsize=8.5)
        ax2.set_xticks(list(x))
        ax2.set_xticklabels(["Defects caught", "Defects missed", "False alarms"])
        ax2.legend(frameon=False, fontsize=8.5)
        for sp in ("top", "right"):
            ax2.spines[sp].set_visible(False)
        plt.tight_layout()
        st.pyplot(fig2, width="content")
        st.markdown("**Validator v2 by defect family**")
        st.dataframe(fam, hide_index=True, width="stretch")
        st.caption("MISLABEL is a mmol/L number tagged as mg/dL (for example 6.4 \"mg/dL\"). v1 refuses to "
                   "guess units, so it misses these. v2 adds UNLIKELY: the reading is held for a person to "
                   "review, never converted. Because v2 was written after seeing v1's misses, the holdout "
                   "bank is the fairer test of it.")
    ti += 1

# ---------- Real time ----------
with tabs[ti]:
    st.markdown("Check a reading **the moment it is entered**, before it ever reaches the history. "
                "On SAS Viya this calls a decision built in **SAS Intelligent Decisioning** and published "
                "to **SAS Micro Analytic Service**. REPEAT and CONFLICT need the user's history, so they "
                "stay in the batch job.")
    r1, r2, r3 = st.columns(3)
    rt_value = r1.text_input("Value", "6.4", key="rt_v")
    rt_unit = r2.selectbox("Unit", ["mg/dL", "mmol/L", "(blank)", "mmol"], key="rt_u")
    rt_ts = r3.text_input("Timestamp", "2026-01-08T07:30:00Z", key="rt_t")
    mas_ok, mas_info = mas_available()
    if st.button("Check reading", type="primary"):
        val = pd.to_numeric(rt_value, errors="coerce")
        unit = "" if rt_unit == "(blank)" else rt_unit
        if mas_ok:
            try:
                codes = check_reading_mas(val, unit, rt_ts)
                where = f"SAS Micro Analytic Service ({mas_info})"
            except Exception as err:
                st.error(f"The published decision did not answer: {err}. Using the Python reference rules.")
                codes = [f["rule"] for f in check_reading(val, unit, rt_ts)]
                where = "Python reference (decision call failed)"
        else:
            codes = [f["rule"] for f in check_reading(val, unit, rt_ts)]
            where = "Python reference (no published decision configured)"
        if codes:
            for c in codes:
                st.error(f"**{c}**: {REASONS.get(c, '')}")
        else:
            mg = val if unit == "mg/dL" else round(18 * val, 1)
            st.success(f"Passes the row rules. Stored as {mg:g} mg/dL.")
        st.caption(f"Checked by: {where}")
    ti += 1

# ---------- Records ----------
with tabs[ti]:
    cols = ["row_id", "user_id", "event_id", "ts_text", "value", "unit", "glucose_mgdl",
            "repeat_payload", "conflict_event", "unlikely_unit", "retained"]
    cols = [c for c in cols if c in derived.columns]
    st.dataframe(derived[cols], hide_index=True, width="stretch")
    st.download_button("Download validated records (CSV)", derived[cols].to_csv(index=False),
                       "derived.csv", "text/csv")
    st.caption("Raw value and unit are never changed; converted values live in glucose_mgdl.")

# ---------- How it runs on SAS Viya ----------
with tabs[ti + 1]:
    st.markdown("""
| Speed | What runs | SAS Viya piece |
|---|---|---|
| **Real time**, one reading | TIME, UNIT, MISSING, UNLIKELY | Rule set in **SAS Intelligent Decisioning**, published to **SAS Micro Analytic Service**, called over REST |
| **Batch**, whole history | All six rules, including REPEAT and CONFLICT | **CAS DATA steps** and **FedSQL** in CAS, called from Python with **SWAT** |
| **Reporting** | Exceptions, retained readings, detection scores | Tables promoted in CAS for a **SAS Visual Analytics** report |

The app sends only records, never SAS code. The rules live on the SAS Viya side.
""")
    st.code(JOB_TEXT, language="sas")
    prog = HERE / "viya" / "trend_validator_viya.sas"
    st.download_button("Download the full SAS Studio program (runs on SAS Viya)",
                       prog.read_text(), "trend_validator_viya.sas")
    if sas_log:
        with st.expander("CAS steps from this run"):
            st.code(sas_log)

st.caption("Synthetic data only · Data validation is not clinical validation · "
           "Source: github.com/leonrodd (Davoody, SAS Innovate 2027)")
