# Can You Trust the Trend? Two-Speed Data Validation on SAS Viya

A live demo for **SAS Innovate 2027** (Davoody). A clear glucose chart can still be built on unreliable records. This app checks diabetes-tracking data on **SAS Viya** at two speeds, then shows what the chart can honestly display.

| Speed | What runs | SAS Viya piece |
|---|---|---|
| **Real time**, one reading | TIME, UNIT, MISSING, UNLIKELY | Rule set in **SAS Intelligent Decisioning**, published to **SAS Micro Analytic Service (MAS)**, called over REST |
| **Batch**, whole history | All six rules, including REPEAT and CONFLICT | **CAS DATA steps** and **FedSQL** in CAS, called from Python with **SWAT** |
| **Reporting** | Exceptions, retained readings, detection scores | Tables promoted in CAS for a **SAS Visual Analytics** report |

The app sends only records, never SAS code. The rules live on the SAS Viya side.

> ⚠️ **Educational demonstration only.** All built-in data is synthetic. This app checks data quality; it does not give medical advice, diagnose, or recommend treatment.

## What the app shows

* **Unchecked vs validated chart** for any user and day: raw numbers connected, beside retained readings only, gaps shaded.
* **Evidence card**: source rows, rows with exceptions, readings retained, mean of logged readings.
* **Exception log** with a reason code for every row-rule problem.
* **Detection vs answer key** on two synthetic banks: what each cleaner caught, missed, and flagged by mistake.
* **Check one reading**: the real-time path, as it would run through MAS.
* **How it runs on SAS Viya**: the CAS job and a download of the full SAS Studio program.

## Results so far (Python reference engine)

| Bank | Cleaner | Caught | Missed | False alarms |
|---|---|---|---|---|
| Test bank (63 rows, 22 defects) | Quick clean | 12 | 10 | 3 |
| | Validator v1 | 20 | 2 | 0 |
| | Validator v2 | 22 | 0 | 0 |
| Holdout bank (61 rows, 22 defects) | Quick clean | 12 | 10 | 3 |
| | Validator v1 | 20 | 2 | 0 |
| | Validator v2 | 22 | 0 | 0 |

* v1 misses mmol/L numbers labeled "mg/dL" because it never guesses units. v2 adds **UNLIKELY**, which holds those readings for a person to review. It never converts them.
* v2 was written after seeing v1's two misses, so the original test bank is not a fair test of it. The **holdout bank** was generated afterward with a different seed and includes genuine extreme readings (40 mg/dL, 480 mg/dL, 25 mmol/L) that v2 must not flag. It does not flag them.
* Both banks come from the same generator, so these results show the rules behave as designed. They do not estimate how often these problems happen in real apps.

**Status:** these numbers come from the Python reference engine. The SAS Viya program in `viya/trend_validator_viya.sas` applies the same rules in CAS and checks itself against the same answer key; run it in SAS Studio to confirm.

## Step 1: run it in SAS Studio on SAS Viya (no setup)

1. In SAS Viya, open **Develop Code and Flows** (SAS Studio).
2. Open `viya/trend_validator_viya.sas` (or paste it into a new SAS program). The test bank is built in.
3. Click **Run**. Look for `NOTE: Validator v2 check PASSED` in the log.
4. Results show the detection table (expect v2 22/0/0, v1 20/2/0, quick clean 12/10/3), the exception log, a one-day chart, and a detection bar chart.
5. The program promotes `TREND_DERIVED`, `TREND_EXCEPTIONS` and `TREND_DETECTION` in CASUSER, so they are ready for SAS Visual Analytics.

## Step 2: build the Visual Analytics report (optional, about 15 minutes)

In **Explore and Visualize** (SAS Visual Analytics), add the three promoted tables from CASUSER and build one page:

* **Bar chart** from `TREND_DETECTION`: category = cleaner, measures = caught, missed, false_alarms.
* **Bar chart** from `TREND_EXCEPTIONS`: category = rule, frequency.
* **Scatter plot** from `TREND_DERIVED`, filtered to retained = 1: x = ts_utc, y = glucose_mgdl, color = user_id. Use a scatter, not a line, so no readings are invented.
* **List table** from `TREND_EXCEPTIONS` with row_id, rule and reason.

## Step 3: build the real-time decision (optional)

In **Build Decisions** (SAS Intelligent Decisioning), create a rule set named `glucose_reading_check`.

**Inputs:** `value` (decimal), `unit` (character), `ts_text` (character). **Output:** `flags` (character), starting empty.

| Rule | Condition | Action |
|---|---|---|
| TIME | `ts_text` does not end in `Z` or a `+hh:mm` / `-hh:mm` offset | append `TIME` to `flags` |
| UNIT | `unit` is not `mg/dL` and not `mmol/L` | append `UNIT` |
| MISSING | `value` is missing | append `MISSING` |
| UNLIKELY | (`unit` = `mg/dL` and `value` < 20) or (`unit` = `mmol/L` and `value` > 40) | append `UNLIKELY` |

Separate codes with commas. Wrap the rule set in a decision, then **publish it to MAS** under the module name `glucose_reading_check`. The app calls `POST {VIYA_URL}/microanalyticScore/modules/glucose_reading_check/steps/execute` and reads `flags` from the response.

## Step 4: connect the app to SAS Viya

Set these as environment variables, or in **Settings → Secrets** on Streamlit Community Cloud (template: `.streamlit/secrets.example.toml`):

| Setting | Used for |
|---|---|
| `CAS_URL` | CAS REST endpoint, for example `https://your-viya-server/cas-shared-default-http` |
| `VIYA_TOKEN` | OAuth access token (or use `CAS_USER` and `CAS_PW` where password sign-in is allowed) |
| `VIYA_URL` and `MAS_MODULE` | The real-time decision |

With nothing set, the app runs the Python reference engine and says so. Your SAS Viya administrator decides whether outside programs can connect; trial and workshop environments often do not allow it. In that case, run Step 1 in SAS Studio for the SAS evidence and keep the public app on the reference engine.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Community Cloud

1. Push this folder to a public GitHub repo (for example `leonrodd/glucose-trend-validator`).
2. At <https://share.streamlit.io>, click **Create app**, choose the repo, and set the main file to `app.py`.
3. Add secrets only if you are connecting to SAS Viya. Never commit a token or password.

## File map

| File | Role |
|---|---|
| `app.py` | Streamlit interface |
| `viya/trend_validator_viya.sas` | Full SAS Studio program for SAS Viya: CAS DATA steps, FedSQL, scoring, charts, Visual Analytics tables |
| `viya_engine.py` | SWAT batch engine (CAS) and the MAS real-time call |
| `validator.py` | Python reference copy of the rules, quick clean, summaries, scoring |
| `data/tracker_testbank.csv`, `data/tracker_truth.csv` | Test bank and its answer key |
| `data/tracker_holdout.csv`, `data/tracker_holdout_truth.csv` | Holdout bank and its answer key |

## The rules (v2.0)

| Rule | Flags | Action |
|---|---|---|
| TIME | Timestamp missing, unreadable, or without a time zone | Flag for review; never assume UTC |
| UNIT | Unit missing or not mg/dL or mmol/L | Quarantine; never guess |
| MISSING | No value | Keep and count; never fill in |
| REPEAT | Exact repeat of the same payload | Keep one; audit the copy |
| CONFLICT | Same event ID, different payload | Flag both for review |
| UNLIKELY | "mg/dL" value below 20, or "mmol/L" value above 40 | Hold for review; never convert |

mmol/L is converted with the teaching factor 18 (6.0 mmol/L = 108 mg/dL) into a new column; raw values never change. Data validation is not clinical validation: no alerts, targets, or treatment suggestions.

## Citation

> Davoody, L. (2027). *Can You Trust the Trend? Two-Speed Data Validation on SAS Viya.* SAS Innovate 2027 (proposed).
