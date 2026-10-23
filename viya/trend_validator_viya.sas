/*====================================================================
  Can You Trust the Trend?  Glucose tracker validation on SAS Viya
  Author: Leon Davoody                          Rule version: v2.0
  Runs in SAS Studio on SAS Viya. The work happens in CAS:
    - CAS DATA steps parse time and apply the row rules
    - FedSQL finds exact repeats and conflicting events across rows
    - Results are promoted so SAS Visual Analytics can build a report
  The 63-row synthetic test bank and its answer key are built in below,
  so nothing needs to be uploaded. Look for "PASSED" in the log.
====================================================================*/
%let rule_version = v2.0;
%let mmol_to_mgdl = 18;      /* teaching convention: 6.0 mmol/L = 108 mg/dL     */
%let mgdl_below   = 20;      /* v2 review flag: "mg/dL" value below this         */
%let mmol_above   = 40;      /* v2 review flag: "mmol/L" value above this        */

cas trend;                   /* start a CAS session */
caslib _all_ assign;         /* makes CASUSER usable as a libref */

/*--- 1. Capture: synthetic records and the answer key --------------*/
data work.tracker_raw;
  infile datalines dsd truncover;
  length row_id $8 user_id $8 event_id $8 ts_text $25 unit $8;
  input row_id $ user_id $ event_id $ ts_text $ value unit $;
  row_num = _n_;             /* stable row order for picking the original */
  datalines;
R001,U01,E001,2026-01-01T12:00:00,168,mg/dL
R002,U01,E002,2026-01-01T18:25:00Z,165,mg/dL
R003,U01,E003,2026-01-01T22:11:00Z,136,mg/dL
R004,U01,E004,2026-01-02T07:38:00Z,107,mg/dL
R005,U01,E005,2026-01-02T12:43:00Z,163,mg/dL
R006,U01,E006,2026-01-02T22:19:00Z,93,mg/dL
R007,U01,E007,2026-01-03T07:48:00Z,190,mg/dL
R008,U01,E008,2026-01-03T12:16:00Z,,mg/dL
R009,U01,E009,2026-01-03T18:10:00Z,178,mg/dL
R010,U01,E010,2026-01-03T22:22:00,205,mg/dL
R011,U01,E011,2026-01-04T07:29:00Z,133,mg/dL
R012,U01,E012,2026-01-04T12:50:00Z,,mg/dL
R013,U01,E013,2026-01-04T18:47:00Z,185,mg/dL
R014,U01,E014,2026-01-04T22:07:00Z,183,mg/dL
R015,U01,E015,2026-01-05T07:12:00Z,195,mg/dL
R016,U01,E016,2026-01-05T12:20:00Z,145,mg/dL
R017,U01,E016,2026-01-05T12:20:00Z,145,mg/dL
R018,U01,E017,2026-01-05T18:06:00Z,120,mg/dL
R019,U01,E017,2026-01-05T18:06:00Z,132,mg/dL
R020,U01,E018,2026-01-05T22:48:00,138,mg/dL
R021,U01,E019,2026-01-06T07:05:00Z,182,mg/dL
R022,U01,E020,2026-01-06T12:37:00Z,94,mg/dL
R023,U01,E020,2026-01-06T12:37:00Z,94,mg/dL
R024,U01,E021,2026-01-06T22:35:00Z,180,mg/dL
R025,U01,E022,2026-01-07T07:26:00Z,93,mg/dL
R026,U01,E022,2026-01-07T07:26:00Z,93,mg/dL
R027,U01,E023,2026-01-07T12:13:00Z,89,mmol
R028,U01,E024,2026-01-07T22:48:00Z,149,mg/dL
R029,U01,E024,2026-01-07T22:48:00Z,149,mg/dL
R030,U02,E025,2026-01-01T07:34:00Z,88,mg/dL
R031,U02,E026,2026-01-01T12:07:00Z,163,mg/dL
R032,U02,E027,2026-01-01T18:28:00Z,86,
R033,U02,E028,2026-01-01T22:00:00Z,9.2,mmol/L
R034,U02,E028,2026-01-01T22:00:00Z,9.2,mmol/L
R035,U02,E029,2026-01-02T07:23:00Z,150,mg/dL
R036,U02,E030,2026-01-02T12:24:00Z,190,mg/dL
R037,U02,E031,2026-01-02T18:13:00Z,190,mg/dL
R038,U02,E031,2026-01-02T18:13:00Z,190,mg/dL
R039,U02,E032,2026-01-02T22:29:00Z,6,mmol/L
R040,U02,E032,2026-01-02T22:29:00Z,6.7,mmol/L
R041,U02,E033,2026-01-03T07:17:00Z,6.4,mg/dL
R042,U02,E034,2026-01-03T12:30:00Z,9.7,mmol/L
R043,U02,E035,2026-01-03T18:40:00Z,170,mg/dL
R044,U02,E036,2026-01-03T22:09:00Z,112,mg/dL
R045,U02,E037,2026-01-04T07:42:00Z,9.4,mmol/L
R046,U02,E038,2026-01-04T12:50:00Z,5.3,mg/dL
R047,U02,E039,2026-01-04T18:27:00Z,5.7,mmol/L
R048,U02,E055,2026-01-04T18:27:00Z,6.2,mmol/L
R049,U02,E040,2026-01-04T22:28:00Z,,mg/dL
R050,U02,E041,2026-01-05T07:16:00Z,175,mg/dL
R051,U02,E042,2026-01-05T12:17:00Z,206,mg/dL
R052,U02,E043,2026-01-05T18:36:00Z,152,mmol
R053,U02,E044,2026-01-05T22:41:00Z,151,mg/dL
R054,U02,E053,2026-01-05T22:41:00Z,160,mg/dL
R055,U02,E045,2026-01-06T07:47:00Z,,mg/dL
R056,U02,E046,2026-01-06T12:41:00Z,189,mg/dL
R057,U02,E047,2026-01-06T18:10:00Z,104,mg/dL
R058,U02,E054,2026-01-06T18:10:00Z,113,mg/dL
R059,U02,E048,2026-01-06T22:19:00Z,6.2,mmol/L
R060,U02,E049,2026-01-07T07:37:00Z,109,mg/dL
R061,U02,E050,2026-01-07T12:16:00Z,172,mg/dL
R062,U02,E051,2026-01-07T18:17:00Z,6.1,mmol/L
R063,U02,E052,2026-01-07T22:06:00Z,113,mg/dL
;
run;

data work.truth;
  infile datalines dsd truncover;
  length row_id $8 family $10;
  input row_id $ family $;
  datalines;
R001,TIME
R008,MISSING
R010,TIME
R012,MISSING
R017,REPEAT
R018,CONFLICT
R019,CONFLICT
R020,TIME
R023,REPEAT
R026,REPEAT
R027,UNIT
R029,REPEAT
R032,UNIT
R034,REPEAT
R038,REPEAT
R039,CONFLICT
R040,CONFLICT
R041,MISLABEL
R046,MISLABEL
R049,MISSING
R052,UNIT
R055,MISSING
;
run;

proc casutil;
  load data=work.tracker_raw outcaslib="casuser" casout="tracker_raw" replace;
  load data=work.truth       outcaslib="casuser" casout="truth"       replace;
quit;

/*--- 2. Parse time and build keys (CAS DATA step) -------------------*/
data casuser.step1;
  set casuser.tracker_raw;
  length payload $120 ev $20;
  ts_utc  = input(strip(ts_text), ?? e8601dz25.);   /* no offset -> missing */
  format ts_utc datetime19.;
  /* the whole payload, so only exact retransmissions match */
  payload = cat(strip(user_id), '|', strip(event_id), '|', strip(ts_text), '|',
                strip(put(value, best32.)), '|', strip(unit));
  ev      = cat(strip(user_id), '|', strip(event_id));
run;

/*--- 3. Identity across rows (FedSQL in CAS) ------------------------*/
proc fedsql sessref=trend;
  create table casuser.payloads {options replace=true} as
    select payload, ev, min(row_num) as keep_num
    from casuser.step1
    group by payload, ev;

  create table casuser.conflicts {options replace=true} as
    select ev, count(*) as n_payloads
    from casuser.payloads
    group by ev
    having count(*) > 1;

  create table casuser.step3 {options replace=true} as
    select s.*,
           case when s.row_num = p.keep_num then 0 else 1 end as repeat_payload,
           case when c.ev is null then 0 else 1 end           as conflict_event
    from casuser.step1 as s
         inner join casuser.payloads  as p on s.payload = p.payload
         left  join casuser.conflicts as c on s.ev = c.ev;
quit;

/*--- 4. Row rules: one exception row per row-rule problem (CAS) -----*/
data casuser.derived(drop=rule reason)
     casuser.exceptions(keep=row_id row_num user_id event_id rule reason rule_version);
  set casuser.step3;
  length rule $8 reason $64 rule_version $8;
  rule_version  = "&rule_version";
  glucose_mgdl  = .;
  unlikely_unit = (unit = 'mg/dL'  and not missing(value) and value < &mgdl_below)
               or (unit = 'mmol/L' and not missing(value) and value > &mmol_above);

  if missing(ts_utc) then do;
    rule='TIME';     reason='Timestamp missing, unparsed or without offset';            output casuser.exceptions;
  end;
  if unit not in ('mg/dL','mmol/L') then do;
    rule='UNIT';     reason='Unknown or missing unit: quarantined, not guessed';        output casuser.exceptions;
  end;
  if missing(value) then do;
    rule='MISSING';  reason='No glucose value recorded: kept, not imputed';             output casuser.exceptions;
  end;
  if repeat_payload then do;
    rule='REPEAT';   reason='Exact repeat of an earlier payload: audit copy kept';      output casuser.exceptions;
  end;
  if conflict_event then do;
    rule='CONFLICT'; reason='Same event ID, different payload: needs review';           output casuser.exceptions;
  end;
  if unlikely_unit then do;
    rule='UNLIKELY'; reason='Value unlikely in its stated unit: held for review, not fixed'; output casuser.exceptions;
  end;

  /* convert only known units, into a new column; raw value never changes */
  if not missing(value) then do;
    if unit = 'mg/dL' then glucose_mgdl = value;
    else if unit = 'mmol/L' then glucose_mgdl = round(&mmol_to_mgdl * value, 0.1);
  end;

  retained = (not missing(glucose_mgdl)) and (not missing(ts_utc))
             and repeat_payload = 0 and conflict_event = 0 and unlikely_unit = 0;
  output casuser.derived;
run;

/*--- 5. Baseline for comparison: a typical "quick clean" ------------*/
/*    drop blanks, drop a second record at the same user + time,     */
/*    and ignore units                                                */
proc fedsql sessref=trend;
  create table casuser.first_at_time {options replace=true} as
    select user_id, ts_text, min(row_num) as first_num
    from casuser.tracker_raw
    group by user_id, ts_text;

  create table casuser.quick {options replace=true} as
    select r.*,
           case when r.value is not null and r.row_num = f.first_num then 1 else 0 end as kept
    from casuser.tracker_raw as r
         inner join casuser.first_at_time as f
         on r.user_id = f.user_id and r.ts_text = f.ts_text;
quit;

/*--- 6. Summaries and scoring (FedSQL in CAS) -----------------------*/
proc fedsql sessref=trend;
  create table casuser.summary_by_user {options replace=true} as
    select d.user_id,
           count(d.value)                                               as unchecked_n,
           avg(d.value)                                                 as unchecked_mean,
           sum(d.retained)                                              as validated_n,
           avg(case when d.retained = 1 then d.glucose_mgdl end)        as validated_mean
    from casuser.derived as d
    group by d.user_id;

  create table casuser.quick_by_user {options replace=true} as
    select user_id, sum(kept) as quick_n,
           avg(case when kept = 1 then value end) as quick_mean
    from casuser.quick
    group by user_id;

  create table casuser.flags {options replace=true} as
    select distinct row_id, 'Validator v2' as cleaner from casuser.exceptions
    union all
    select distinct row_id, 'Validator v1' as cleaner from casuser.exceptions where rule <> 'UNLIKELY'
    union all
    select row_id, 'Quick clean' as cleaner from casuser.quick where kept = 0;

  create table casuser.truth_rows {options replace=true} as
    select distinct row_id from casuser.truth;

  create table casuser.detection {options replace=true} as
    select c.cleaner,
           sum(case when f.row_id is not null and t.row_id is not null then 1 else 0 end) as caught,
           sum(case when f.row_id is null     and t.row_id is not null then 1 else 0 end) as missed,
           sum(case when f.row_id is not null and t.row_id is null     then 1 else 0 end) as false_alarms
    from (select r.row_id, k.cleaner
          from casuser.tracker_raw as r,
               (select distinct cleaner from casuser.flags) as k) as c
         left join casuser.flags      as f on c.row_id = f.row_id and c.cleaner = f.cleaner
         left join casuser.truth_rows as t on c.row_id = t.row_id
    group by c.cleaner;

  create table casuser.by_family {options replace=true} as
    select t.family,
           count(*) as seeded,
           sum(case when e.row_id is not null then 1 else 0 end) as detected
    from casuser.truth as t
         left join casuser.exceptions as e
         on t.row_id = e.row_id
        and e.rule = case when t.family = 'MISLABEL' then 'UNLIKELY' else t.family end
    group by t.family;
quit;

title "Detection vs answer key (expect v2 22/0/0, v1 20/2/0, Quick clean 12/10/3)";
proc print data=casuser.detection noobs; run;

title "Validator v2 by defect family";
proc print data=casuser.by_family noobs; run;

title "Mean of logged readings by user (expect validated U01 151.2, U02 145.8)";
proc print data=casuser.summary_by_user noobs; format unchecked_mean validated_mean 8.1; run;
proc print data=casuser.quick_by_user noobs; format quick_mean 8.1; run;

title "Exception log (one row per row-rule problem)";
proc print data=casuser.exceptions noobs; run;

/*--- 7. Self-check against the answer key ---------------------------*/
data work.detection; set casuser.detection; run;
data _null_;
  set work.detection;
  if strip(cleaner) = 'Validator v2' then do;
    if caught = 22 and missed = 0 and false_alarms = 0
      then put 'NOTE: Validator v2 check PASSED against the answer key.';
      else put 'WARNING: Validator v2 check FAILED. Compare DETECTION with the answer key.';
  end;
run;

/*--- 8. Charts: one day, two stories -------------------------------*/
data work.day;
  set casuser.derived(where=(user_id = 'U02' and substr(ts_text, 1, 10) = '2026-01-01'));
  if retained then plot_mgdl = glucose_mgdl;
run;
proc sort data=work.day; by ts_utc; run;

title "User U02, 1 January 2026: unchecked numbers vs validated readings";
proc sgplot data=work.day;
  series  x=ts_utc y=value     / markers lineattrs=(color=red)
                                 markerattrs=(color=red symbol=circlefilled)
                                 legendlabel='Unchecked raw numbers' name='raw';
  scatter x=ts_utc y=plot_mgdl / markerattrs=(color=blue symbol=diamondfilled size=11)
                                 legendlabel='Validated (mg/dL)' name='ok';
  keylegend 'raw' 'ok';
  xaxis label="Time (UTC)";
  yaxis label="Value as plotted";
  format ts_utc tod5.;
run;

data work.det_long;
  set work.detection;
  length measure $14;
  measure='Caught';       n=caught;       output;
  measure='Missed';       n=missed;       output;
  measure='False alarms'; n=false_alarms; output;
run;
title "Detection on 22 seeded defects";
proc sgplot data=work.det_long;
  vbar measure / response=n group=cleaner groupdisplay=cluster datalabel;
  xaxis display=(nolabel);
  yaxis label="Rows";
run;
title;

/*--- 9. Share with SAS Visual Analytics -----------------------------*/
/*    Promoted tables stay available after this session ends, so a   */
/*    Visual Analytics report can use them. They go to CASUSER, which */
/*    every user can write to.                                        */
proc casutil;
  droptable casdata="TREND_DERIVED"    incaslib="casuser" quiet;
  droptable casdata="TREND_EXCEPTIONS" incaslib="casuser" quiet;
  droptable casdata="TREND_DETECTION"  incaslib="casuser" quiet;
  promote casdata="derived"    incaslib="casuser" outcaslib="casuser" casout="TREND_DERIVED";
  promote casdata="exceptions" incaslib="casuser" outcaslib="casuser" casout="TREND_EXCEPTIONS";
  promote casdata="detection"  incaslib="casuser" outcaslib="casuser" casout="TREND_DETECTION";
quit;

cas trend terminate;
