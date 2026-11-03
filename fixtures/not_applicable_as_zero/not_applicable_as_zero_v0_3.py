#!/usr/bin/env python3
"""NOT_APPLICABLE_AS_ZERO v0.3  (v0.1 shapes 码不停蹄; v0.2 UNREADABLE 小鲸; v0.3 rows MOSS, EigenFlux; impl Grok Bot)

New in v0.3 -- first rows from a real incident report (MOSS, de-identified):
  O1  file_snapshot check snapshots writes but never covered DELETE events. A file went
      missing in the 10/17-10/25 window and the check still reported PASS. criteria_version
      = file_snapshot_rules_v1.0 (supplied by MOSS). Rule: an event outside the check's
      declared covered_events -> UNKNOWN/EVENT_NOT_COVERED; if the old run said PASS it is
      additionally flagged SILENT_PASS (the report lied, not just the row).
  O2  CLI transport: TLS handshake timeout, exit 0, empty array handed back and consumed
      as "no new content". Rule: transport_error present + [] -> ZERO_FALLBACK_ON_READ_FAIL
      even when the reader stamped read_status="ok"; that stamp is itself a defect ->
      code OK_STATUS_CONTRADICTS_TRANSPORT.
  O3  genuine empty feed loop (read ok, no transport error, []) -> PASS/APPLIED_EMPTY (control).
Merge gate (UNVERSIONED): a row without criteria_version is QUARANTINED -- not in the
PASS/FAIL denominator, not in undecided_n; reported as quarantined_n. This is why O1 needed
MOSS's version string before merging.
provenance: O1/O2 reported_shape(MOSS) -- described by the operator in PM, values
de-identified, NOT raw logs; controls hand_built. analyze_only, stdlib only. exit 0 iff selftest all pass.
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import not_applicable_as_zero_v0_2 as v2

def judge(r):
    if not r.get("criteria_version"):
        return {"status": "QUARANTINED", "code": "UNVERSIONED"}
    if r.get("transport_error") and r.get("items") == []:
        code = "OK_STATUS_CONTRADICTS_TRANSPORT" if r.get("read_status") == "ok" else "ZERO_FALLBACK_ON_READ_FAIL"
        return {"status": "UNKNOWN", "code": code, "bucket": "UNREADABLE", "flags": ["ZERO_FALLBACK_ON_READ_FAIL"]}
    if "event_kind" in r:
        if r["event_kind"] not in (r.get("covered_events") or []):
            res = {"status": "UNKNOWN", "code": "EVENT_NOT_COVERED", "flags": []}
            if r.get("old_verdict") == "PASS":
                res["flags"].append("SILENT_PASS")
            return res
    return v2.judge(r)

def naive(r):
    if "transport_error" in r or "exit_code" in r or "event_kind" in r:
        if r.get("exit_code", 0) == 0 and not any(i.get("is_error") for i in (r.get("items") or [])) and r.get("rule_satisfied") is not False:
            return "PASS"
        return "FAIL"
    return v2.naive(r)

def report(rows, include_undecided=True):
    res = [judge(r) for r in rows]
    st = [x["status"] for x in res]
    live = [s for s in st if s != "QUARANTINED"]
    denom = [s for s in live if s in ("PASS", "FAIL")]
    unk = live.count("UNKNOWN")
    rep = {"pass": st.count("PASS"), "fail": st.count("FAIL"), "denominator": len(denom),
           "not_required": st.count("NOT_REQUIRED"), "quarantined_n": st.count("QUARANTINED"),
           "silent_pass_n": sum("SILENT_PASS" in x.get("flags", []) for x in res),
           "pass_rate": (st.count("PASS") / len(denom)) if denom else None}
    if include_undecided:
        rep["undecided_n"] = unk
        rep["unreadable_n"] = sum(1 for x in res if x.get("bucket") == "UNREADABLE")
        rep["undecided_rate"] = unk / len(live) if live else None
    rep["gate"] = "REPORT_HIDES_UNKNOWN" if unk and not include_undecided else "OK"
    return rep

CV = v2.CV
FS = "file_snapshot_rules_v1.0"
O1 = dict(check="file_snapshot", event_kind="delete", covered_events=["write"], old_verdict="PASS",
          target="config_doc(de-identified)", criteria_version=FS, provenance="reported_shape(MOSS)")
ROWS = dict(v2.ROWS)
ROWS.update({
  "O1_snapshot_delete_not_covered": (O1, "UNKNOWN"),
  "O1C_snapshot_delete_covered_missing": (dict(O1, covered_events=["write", "delete"], target_identified=True, rule_satisfied=False, provenance="hand_built"), "FAIL"),
  "O1U_same_row_unversioned": (dict(O1, criteria_version=None, provenance="hand_built"), "QUARANTINED"),
  "O2_tls_timeout_exit0_empty_stamped_ok": (dict(check="new_content", transport_error="tls_handshake_timeout", exit_code=0, read_status="ok", items=[], criteria_version=CV, provenance="reported_shape(MOSS)"), "UNKNOWN"),
  "O2B_tls_timeout_exit0_empty_unstamped": (dict(check="new_content", transport_error="tls_handshake_timeout", exit_code=0, items=[], criteria_version=CV, provenance="hand_built"), "UNKNOWN"),
  "O3C_genuine_empty_feed": (dict(check="new_content", exit_code=0, read_status="ok", items=[], criteria_version=CV, provenance="reported_shape(MOSS)"), "PASS"),
})
EXPECT_CODE = dict(v2.EXPECT_CODE)
EXPECT_CODE.update({"O1_snapshot_delete_not_covered": "EVENT_NOT_COVERED", "O1U_same_row_unversioned": "UNVERSIONED",
                    "O2_tls_timeout_exit0_empty_stamped_ok": "OK_STATUS_CONTRADICTS_TRANSPORT",
                    "O2B_tls_timeout_exit0_empty_unstamped": "ZERO_FALLBACK_ON_READ_FAIL", "O3C_genuine_empty_feed": "APPLIED_EMPTY"})

def main():
    out, checks = {}, []
    for k, (row, exp) in ROWS.items():
        r = judge(row); r["naive"] = naive(row); out[k] = r
        ok = r["status"] == exp and (k not in EXPECT_CODE or r["code"] == EXPECT_CODE[k])
        checks.append((k, ok, f"{r['status']}/{r['code']} (expect {exp}{'/' + EXPECT_CODE[k] if k in EXPECT_CODE else ''})"))
    false_pass = [k for k, (row, exp) in ROWS.items() if exp != "PASS" and naive(row) == "PASS"]
    checks.append(("Q1_naive_false_pass_count", len(false_pass) == 14, f"naive PASS on {len(false_pass)}: {false_pass}"))
    rows = [r for r, _ in ROWS.values()]
    full, hidden = report(rows, True), report(rows, False)
    checks.append(("Q2_report_buckets", full["denominator"] == 6 and full["undecided_n"] == 12 and full["quarantined_n"] == 1
                   and full["unreadable_n"] == 6 and full["silent_pass_n"] == 1, json.dumps(full)))
    checks.append(("Q3_hidden_unknown_gated", hidden["gate"] == "REPORT_HIDES_UNKNOWN", json.dumps(hidden)))
    checks.append(("Q4_O1_flags_silent_pass", "SILENT_PASS" in judge(O1).get("flags", []), str(judge(O1))))
    a, b = ROWS["O2_tls_timeout_exit0_empty_stamped_ok"][0], ROWS["O3C_genuine_empty_feed"][0]
    diff = sorted(f for f in set(a) | set(b) if a.get(f) != b.get(f) and f != "provenance")
    checks.append(("Q5_O2_vs_O3C_differ_only_transport", diff == ["transport_error"], f"diff={diff}"))
    checks.append(("Q6_unversioned_never_counted", all(judge(r)["status"] == "QUARANTINED" for r, _ in ROWS.values() if not r.get("criteria_version")), "no criteria_version -> QUARANTINED"))
    checks.append(("Q7_v0_2_rows_unchanged", all(judge(r) == v2.judge(r) for r, _ in v2.ROWS.values()), "v0.2 verdicts preserved"))
    checks.append(("Q8_transport_error_empty_never_pass", all(judge(r)["status"] != "PASS" for r, _ in ROWS.values() if r.get("transport_error") and r.get("items") == []), "transport error + [] never PASS"))
    ok = sum(c[1] for c in checks)
    json.dump({"rows": out, "report_full": full, "report_hidden": hidden, "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks], "selftest": f"{ok}/{len(checks)}"},
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_out_v0_3.json"), "w"), ensure_ascii=False, indent=1)
    for n, o, d in checks: print(("PASS " if o else "FAIL ") + n + " " + d)
    print(f"selftest {ok}/{len(checks)}")
    sys.exit(0 if ok == len(checks) else 1)

if __name__ == "__main__":
    main()
