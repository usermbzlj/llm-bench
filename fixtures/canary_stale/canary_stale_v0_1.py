#!/usr/bin/env python3
"""CANARY_STALE v0.1  (problem + field design credit: FTC, EigenFlux; impl Grok Bot)

Problem (FTC, observed in practice, found only by manual recompute): a
must-fail canary arm stayed GREEN while the criteria version drifted three
rounds; the arm was never re-seeded, so against any current criteria it was
stale. No column in the ledger could report that state.

Gate: a canary verdict is only evidence for the criteria version it was
built against.
  canary_built_against_version  pinned by the ISSUER when the arm is seeded
  run_criteria_version          written by the ISSUER for this run
Both must be issuer-written (not a local hash/recompute).
  either field missing                    -> NOT_EVALUABLE / CANARY_VERSION_MISSING
  either field self-computed (not issuer) -> NOT_EVALUABLE / SELF_COMPUTED_VERSION
  built != run                            -> VOID / CANARY_STALE  (green OR red)
  built == run                            -> VALID (arm result counts)
stale_rounds = number of distinct criteria versions run since the seed.
Naive baseline: "arm present and green -> VALID".
provenance: S1 values = FTC synthetic example (labelled synthetic); others hand_built.
analyze_only, stdlib only, exit 0 iff selftest all pass.
"""
from __future__ import annotations
import json, sys

def judge(r):
    b, run = r.get("canary_built_against_version"), r.get("run_criteria_version")
    hist = r.get("criteria_history", [])
    stale_rounds = len([v for v in dict.fromkeys(hist) if v != b]) if b and hist else None
    if b is None or run is None:
        return {"status": "NOT_EVALUABLE", "code": "CANARY_VERSION_MISSING", "stale_rounds": stale_rounds}
    if not (r.get("built_issuer_written") and r.get("run_issuer_written")):
        return {"status": "NOT_EVALUABLE", "code": "SELF_COMPUTED_VERSION", "stale_rounds": stale_rounds}
    if b != run:
        return {"status": "VOID", "code": "CANARY_STALE", "stale_rounds": stale_rounds}
    return {"status": "VALID", "code": "ARM_" + r["arm_result"], "stale_rounds": stale_rounds}

def naive(r):
    return "VALID" if r.get("arm_result") == "GREEN" else "INVALID"

W = dict(built_issuer_written=True, run_issuer_written=True)
ROWS = {
  "S1_ftc_synthetic_stale": (dict(canary_built_against_version="criteria-v0.3", run_criteria_version="criteria-v0.4", arm_result="GREEN", provenance="synthetic(FTC)", **W), "VOID"),
  "S1C_same_version_control": (dict(canary_built_against_version="criteria-v0.4", run_criteria_version="criteria-v0.4", arm_result="GREEN", provenance="hand_built", **W), "VALID"),
  "S2_built_missing": (dict(run_criteria_version="criteria-v0.4", arm_result="GREEN", provenance="hand_built", **W), "NOT_EVALUABLE"),
  "S3_run_version_self_hashed": (dict(canary_built_against_version="criteria-v0.4", run_criteria_version="criteria-v0.4", arm_result="GREEN", provenance="hand_built", built_issuer_written=True, run_issuer_written=False), "NOT_EVALUABLE"),
  "S4_three_round_drift": (dict(canary_built_against_version="criteria-v0.2", run_criteria_version="criteria-v0.5", criteria_history=["criteria-v0.3","criteria-v0.4","criteria-v0.5"], arm_result="GREEN", provenance="hand_built", **W), "VOID"),
  "S5_stale_but_red": (dict(canary_built_against_version="criteria-v0.2", run_criteria_version="criteria-v0.5", arm_result="RED", provenance="hand_built", **W), "VOID"),
  "S6_reseeded_after_drift": (dict(canary_built_against_version="criteria-v0.5", run_criteria_version="criteria-v0.5", criteria_history=["criteria-v0.3","criteria-v0.4","criteria-v0.5"], arm_result="GREEN", provenance="hand_built", **W), "VALID"),
}

def main():
    out, checks = {}, []
    for k, (row, exp) in ROWS.items():
        r = judge(row); r["naive"] = naive(row); out[k] = r
        checks.append((k, r["status"] == exp, f"{r['status']}/{r['code']} (expect {exp})"))
    s1, s1c = ROWS["S1_ftc_synthetic_stale"][0], ROWS["S1C_same_version_control"][0]
    diff = [f for f in set(s1) | set(s1c) if s1.get(f) != s1c.get(f) and f != "provenance"]
    checks.append(("P1_pair_differs_only_in_built_version", diff == ["canary_built_against_version"], f"diff fields={diff}"))
    checks.append(("P2_naive_cannot_split_S1_S1C", out["S1_ftc_synthetic_stale"]["naive"] == out["S1C_same_version_control"]["naive"] == "VALID", "naive VALID on both -> stale arm invisible"))
    fooled = sorted(k for k, (row, exp) in ROWS.items() if out[k]["naive"] == "VALID" and exp != "VALID")
    checks.append(("P3_naive_false_valid_count", fooled == ["S1_ftc_synthetic_stale","S2_built_missing","S3_run_version_self_hashed","S4_three_round_drift"], f"naive false-VALID={fooled}"))
    checks.append(("P4_stale_rounds_S4", out["S4_three_round_drift"]["stale_rounds"] == 3, f"stale_rounds={out['S4_three_round_drift']['stale_rounds']}"))
    checks.append(("P5_red_on_stale_is_not_evidence", out["S5_stale_but_red"]["code"] == "CANARY_STALE", "stale RED also VOID (red against old criteria proves nothing about current)"))
    ok = 0
    for name, good, msg in checks:
        ok += good; print(("PASS " if good else "FAIL ") + name + ": " + msg)
    json.dump(out, open("run_out_v0_1.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{len(checks)}")
    sys.exit(0 if ok == len(checks) else 1)

if __name__ == "__main__":
    main()
