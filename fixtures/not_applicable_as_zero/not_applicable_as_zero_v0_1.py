#!/usr/bin/env python3
"""NOT_APPLICABLE_AS_ZERO v0.1  (shapes + verdict axes credit: 码不停蹄, EigenFlux; impl Grok Bot)

Problem: a check that could not be applied (no target, unparseable input,
excluded by a list) is folded into PASS. "Couldn't test" silently becomes
"tested and passed", and the undecided rate vanishes from the report.

Three tri-state outcomes, orthogonal:
  PASS / FAIL         check applied, verdict counts in denominator
  UNKNOWN             check could not decide -> counted separately, OUT of denominator,
                      but MUST appear in report (undecided_rate visible)
  NOT_REQUIRED        only when the exemption list is ISSUER-signed and versioned with
                      the criteria; a local/mutable list -> UNKNOWN
Shapes (码不停蹄, de-identified, labelled synthetic):
  N1 VAE filename filter: axis = does the filename really point at VAE weights,
     not "did the call error". Cannot tell -> UNKNOWN (old: PASS).
  N2 subgraph parse fail: read but cannot parse = cannot test -> UNDECIDABLE (UNKNOWN
     family), out of denominator. run-id zero and evidence zero judged separately.
  N3 custom-node exclusion: excluded = environment-arm fact, not rule-arm satisfied.
     issuer-signed list -> NOT_REQUIRED; local list -> UNKNOWN. Never PASS.
Report gate: if any UNKNOWN exists and report omits undecided_n -> REPORT_HIDES_UNKNOWN.
Naive baseline: "no FAIL raised -> PASS".
provenance: N1-N3 synthetic (码不停蹄 shapes), rest hand_built. analyze_only, stdlib only.
exit 0 iff selftest all pass.
"""
from __future__ import annotations
import json, sys

def judge(r):
    if r.get("excluded"):
        if r.get("exclusion_list_issuer_signed") and r.get("exclusion_list_criteria_version") == r.get("criteria_version"):
            return {"status": "NOT_REQUIRED", "code": "ISSUER_EXEMPT"}
        if r.get("exclusion_list_issuer_signed"):
            return {"status": "UNKNOWN", "code": "EXEMPT_LIST_VERSION_STALE"}
        return {"status": "UNKNOWN", "code": "LOCAL_EXEMPT_LIST"}
    if r.get("parse_ok") is False:
        return {"status": "UNKNOWN", "code": "UNDECIDABLE_PARSE"}
    if r.get("target_identified") is not True:
        return {"status": "UNKNOWN", "code": "TARGET_UNRESOLVED"}
    if r.get("rule_satisfied") is True:
        return {"status": "PASS", "code": "APPLIED"}
    if r.get("rule_satisfied") is False:
        return {"status": "FAIL", "code": "APPLIED"}
    return {"status": "UNKNOWN", "code": "NO_EVIDENCE"}

def naive(r):
    return "FAIL" if r.get("rule_satisfied") is False and not r.get("excluded") else "PASS"

def report(rows, include_undecided=True):
    res = [judge(r)["status"] for r in rows]
    denom = [s for s in res if s in ("PASS", "FAIL")]
    unk = res.count("UNKNOWN")
    rep = {"pass": res.count("PASS"), "fail": res.count("FAIL"), "denominator": len(denom),
           "not_required": res.count("NOT_REQUIRED"),
           "pass_rate": (res.count("PASS") / len(denom)) if denom else None}
    if include_undecided:
        rep["undecided_n"] = unk
        rep["undecided_rate"] = unk / len(res) if res else None
    rep["gate"] = "REPORT_HIDES_UNKNOWN" if unk and not include_undecided else "OK"
    return rep

CV = "criteria-v0.9"
ROWS = {
  "N1_vae_name_unresolved": (dict(check="vae_filename", target_identified=False, call_errored=False, criteria_version=CV, provenance="synthetic(码不停蹄)"), "UNKNOWN"),
  "N1C_vae_name_resolved_ok": (dict(check="vae_filename", target_identified=True, rule_satisfied=True, call_errored=False, criteria_version=CV, provenance="hand_built"), "PASS"),
  "N2_subgraph_parse_fail": (dict(check="subgraph", parse_ok=False, target_identified=True, criteria_version=CV, provenance="synthetic(码不停蹄)"), "UNKNOWN"),
  "N2C_subgraph_parsed_fail": (dict(check="subgraph", parse_ok=True, target_identified=True, rule_satisfied=False, criteria_version=CV, provenance="hand_built"), "FAIL"),
  "N3_excluded_local_list": (dict(check="custom_node", excluded=True, exclusion_list_issuer_signed=False, criteria_version=CV, provenance="synthetic(码不停蹄)"), "UNKNOWN"),
  "N3C_excluded_issuer_list": (dict(check="custom_node", excluded=True, exclusion_list_issuer_signed=True, exclusion_list_criteria_version=CV, criteria_version=CV, provenance="hand_built"), "NOT_REQUIRED"),
  "N3S_issuer_list_stale_version": (dict(check="custom_node", excluded=True, exclusion_list_issuer_signed=True, exclusion_list_criteria_version="criteria-v0.8", criteria_version=CV, provenance="hand_built"), "UNKNOWN"),
  "N4_applied_no_evidence": (dict(check="generic", target_identified=True, parse_ok=True, criteria_version=CV, provenance="hand_built"), "UNKNOWN"),
}

def main():
    out, checks = {}, []
    for k, (row, exp) in ROWS.items():
        r = judge(row); r["naive"] = naive(row); out[k] = r
        checks.append((k, r["status"] == exp, f"{r['status']}/{r['code']} (expect {exp})"))
    false_pass = [k for k, (row, exp) in ROWS.items() if exp != "PASS" and naive(row) == "PASS"]
    checks.append(("P1_naive_false_pass_count", len(false_pass) == 6, f"naive PASS on {false_pass}"))
    rows = [r for r, _ in ROWS.values()]
    full, hidden = report(rows, True), report(rows, False)
    checks.append(("P2_unknown_out_of_denominator", full["denominator"] == 2 and full["undecided_n"] == 5, json.dumps(full)))
    checks.append(("P3_hidden_unknown_gated", hidden["gate"] == "REPORT_HIDES_UNKNOWN", json.dumps(hidden)))
    a, b = ROWS["N3_excluded_local_list"][0], ROWS["N3C_excluded_issuer_list"][0]
    diff = sorted(f for f in set(a) | set(b) if a.get(f) != b.get(f) and f != "provenance")
    checks.append(("P4_N3_pair_differs_only_in_list_authority", diff == ["exclusion_list_criteria_version", "exclusion_list_issuer_signed"], f"diff={diff}"))
    checks.append(("P5_never_pass_on_excluded", all(judge(r)["status"] != "PASS" for r, _ in ROWS.values() if r.get("excluded")), "excluded rows never PASS"))
    ok = sum(c[1] for c in checks)
    json.dump({"rows": out, "report_full": full, "report_hidden": hidden, "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks], "selftest": f"{ok}/{len(checks)}"}, open("run_out_v0_1.json", "w"), ensure_ascii=False, indent=1)
    for n, o, d in checks: print(("PASS " if o else "FAIL ") + n + " " + d)
    print(f"selftest {ok}/{len(checks)}")
    sys.exit(0 if ok == len(checks) else 1)

if __name__ == "__main__":
    main()
