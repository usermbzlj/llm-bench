#!/usr/bin/env python3
"""NOT_APPLICABLE_AS_ZERO v0.2  (v0.1 shapes credit 码不停蹄; UNREADABLE bucket + empty-array shape credit 小鲸, EigenFlux; impl Grok Bot)

New in v0.2 (小鲸): missing silently becomes an EMPTY ARRAY. A reader whose parse
fails returns [] and the caller sees "no new content" -- same shape as "read
failed". Fifth bucket:
  UNREADABLE   read did not succeed -> not missing, not zero, not empty. UNKNOWN family,
               out of denominator, counted in undecided_n.
Typing rule: "read ok but empty" and "read failed" must be different return
types. An empty result with no explicit read_status="ok" is EMPTY_UNTYPED (UNKNOWN).
A read failure that still hands back [] is additionally flagged
ZERO_FALLBACK_ON_READ_FAIL (the reader, not just the row, is defective).
Rows U1-U4 synthetic (小鲸 shape, de-identified), U*C controls hand_built.
Naive baseline (v0.1 + "empty list -> nothing new -> PASS").
analyze_only, stdlib only. exit 0 iff selftest all pass.
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import not_applicable_as_zero_v0_1 as v1

def judge(r):
    if "items" in r or "read_status" in r:          # list-returning reader path (v0.2)
        st = r.get("read_status")
        if st == "failed":
            code = "ZERO_FALLBACK_ON_READ_FAIL" if r.get("items") == [] else "UNREADABLE"
            return {"status": "UNKNOWN", "code": code, "bucket": "UNREADABLE"}
        if st != "ok":
            if r.get("items") == []:
                return {"status": "UNKNOWN", "code": "EMPTY_UNTYPED", "bucket": "UNREADABLE"}
            return {"status": "UNKNOWN", "code": "READ_STATUS_ABSENT", "bucket": "UNREADABLE"}
        items = r.get("items")
        if items is None:
            return {"status": "UNKNOWN", "code": "OK_BUT_NO_PAYLOAD", "bucket": "UNREADABLE"}
        bad = [i for i in items if i.get("is_error")]
        return {"status": "FAIL" if bad else "PASS", "code": "APPLIED_EMPTY" if not items else "APPLIED"}
    return v1.judge(r)

def naive(r):
    if "items" in r or "read_status" in r:
        return "FAIL" if any(i.get("is_error") for i in (r.get("items") or [])) else "PASS"
    return v1.naive(r)

def report(rows, include_undecided=True):
    res = [judge(r) for r in rows]
    st = [x["status"] for x in res]
    denom = [s for s in st if s in ("PASS", "FAIL")]
    unk = st.count("UNKNOWN")
    rep = {"pass": st.count("PASS"), "fail": st.count("FAIL"), "denominator": len(denom),
           "not_required": st.count("NOT_REQUIRED"),
           "pass_rate": (st.count("PASS") / len(denom)) if denom else None}
    if include_undecided:
        rep["undecided_n"] = unk
        rep["unreadable_n"] = sum(1 for x in res if x.get("bucket") == "UNREADABLE")
        rep["undecided_rate"] = unk / len(st) if st else None
    rep["gate"] = "REPORT_HIDES_UNKNOWN" if unk and not include_undecided else "OK"
    return rep

CV = v1.CV
ROWS = dict(v1.ROWS)
ROWS.update({
  "U1_parse_fail_returns_empty": (dict(check="new_content", read_status="failed", items=[], criteria_version=CV, provenance="synthetic(小鲸)"), "UNKNOWN"),
  "U1C_read_ok_empty": (dict(check="new_content", read_status="ok", items=[], criteria_version=CV, provenance="hand_built"), "PASS"),
  "U2_empty_no_status": (dict(check="new_content", items=[], criteria_version=CV, provenance="synthetic(小鲸)"), "UNKNOWN"),
  "U3_read_fail_raises_no_items": (dict(check="new_content", read_status="failed", criteria_version=CV, provenance="synthetic(小鲸)"), "UNKNOWN"),
  "U4_ok_but_items_absent": (dict(check="new_content", read_status="ok", criteria_version=CV, provenance="hand_built"), "UNKNOWN"),
  "U5C_read_ok_with_error_item": (dict(check="new_content", read_status="ok", items=[{"is_error": True}], criteria_version=CV, provenance="hand_built"), "FAIL"),
})
EXPECT_CODE = {"U1_parse_fail_returns_empty": "ZERO_FALLBACK_ON_READ_FAIL", "U2_empty_no_status": "EMPTY_UNTYPED",
               "U3_read_fail_raises_no_items": "UNREADABLE", "U4_ok_but_items_absent": "OK_BUT_NO_PAYLOAD"}

def main():
    out, checks = {}, []
    for k, (row, exp) in ROWS.items():
        r = judge(row); r["naive"] = naive(row); out[k] = r
        ok = r["status"] == exp and (k not in EXPECT_CODE or r["code"] == EXPECT_CODE[k])
        checks.append((k, ok, f"{r['status']}/{r['code']} (expect {exp}{'/' + EXPECT_CODE[k] if k in EXPECT_CODE else ''})"))
    false_pass = [k for k, (row, exp) in ROWS.items() if exp != "PASS" and naive(row) == "PASS"]
    checks.append(("P1_naive_false_pass_count", len(false_pass) == 10, f"naive PASS on {len(false_pass)}: {false_pass}"))
    rows = [r for r, _ in ROWS.values()]
    full, hidden = report(rows, True), report(rows, False)
    checks.append(("P2_unknown_out_of_denominator", full["denominator"] == 4 and full["undecided_n"] == 9 and full["unreadable_n"] == 4, json.dumps(full)))
    checks.append(("P3_hidden_unknown_gated", hidden["gate"] == "REPORT_HIDES_UNKNOWN", json.dumps(hidden)))
    a, b = ROWS["U1_parse_fail_returns_empty"][0], ROWS["U1C_read_ok_empty"][0]
    diff = sorted(f for f in set(a) | set(b) if a.get(f) != b.get(f) and f != "provenance")
    checks.append(("P4_U1_pair_differs_only_in_read_status", diff == ["read_status"], f"diff={diff}"))
    checks.append(("P5_never_pass_on_excluded", all(judge(r)["status"] != "PASS" for r, _ in ROWS.values() if r.get("excluded")), "excluded rows never PASS"))
    checks.append(("P6_empty_pass_requires_typed_ok", all(judge(r)["status"] != "PASS" for r, _ in ROWS.values() if r.get("items") == [] and r.get("read_status") != "ok"), "untyped/failed empty never PASS"))
    checks.append(("P7_v0_1_rows_unchanged", all(judge(r) == v1.judge(r) for r, _ in v1.ROWS.values()), "v0.1 verdicts preserved"))
    ok = sum(c[1] for c in checks)
    json.dump({"rows": out, "report_full": full, "report_hidden": hidden, "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks], "selftest": f"{ok}/{len(checks)}"},
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_out_v0_2.json"), "w"), ensure_ascii=False, indent=1)
    for n, o, d in checks: print(("PASS " if o else "FAIL ") + n + " " + d)
    print(f"selftest {ok}/{len(checks)}")
    sys.exit(0 if ok == len(checks) else 1)

if __name__ == "__main__":
    main()
