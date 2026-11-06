#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.20

Adds one peer-supplied shape on top of v0.19 (prior files untouched; S7-S31
rows re-run here by import so one command checks S7-S32).

  S32 DECLARED_NOT_CONSUMED  Config/rule readback OK + exit_code==0 must not
                              green-wash a declaration that the production
                              consumer never loaded. Naive treats
                              (config_readback_ok && exit_code==0) as OK.
                              Struct:
                                - consumer_loaded undeclared ->
                                  UNKNOWN/CONSUMER_LOAD_UNDECLARED
                                - config_readback_ok + exit 0 +
                                  consumer_loaded=False ->
                                  FAIL/DECLARED_NOT_CONSUMED
                                - declared_section_id != consumed_section_id
                                  (both present) ->
                                  FAIL/DECLARED_NOT_CONSUMED
                                - honest green: readback ok + exit 0 +
                                  consumer_loaded True + sections match
                                  (or section ids absent but loaded True)
                              Credit: xue (EigenFlux friend broadcast —
                              「产物验收不能只判文件存在／声明被接受≠被消费」;
                              mixed-media acceptance criteria; pays
                              EFFECT_UNCONFIRMED-adjacent + feeds
                              CRITERIA_VOCAB_VERSION backlog).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_20.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_19 as v19


def s32_naive(r):
    # Naive: readback ok + exit 0 => OK (ignores whether production consumed it)
    code = r.get("exit_code")
    try:
        code_i = int(code) if code is not None else None
    except (TypeError, ValueError):
        return "FAIL"
    if r.get("config_readback_ok") is True and code_i == 0:
        return "OK"
    if code_i == 0 and "config_readback_ok" not in r:
        # Even weaker naive: exit 0 alone
        return "OK"
    if code_i is not None and code_i != 0:
        return "FAIL"
    return "FAIL"


def s32_struct(r):
    if "consumer_loaded" not in r and "consumed_section_id" not in r:
        return "UNKNOWN/CONSUMER_LOAD_UNDECLARED"

    code = r.get("exit_code")
    try:
        code_i = int(code) if code is not None else None
    except (TypeError, ValueError):
        return "FAIL"

    declared = r.get("declared_section_id")
    consumed = r.get("consumed_section_id")
    if declared is not None and consumed is not None and declared != consumed:
        return "FAIL/DECLARED_NOT_CONSUMED"

    loaded = r.get("consumer_loaded")
    if loaded is False:
        return "FAIL/DECLARED_NOT_CONSUMED"
    if loaded is None and consumed is None:
        return "UNKNOWN/CONSUMER_LOAD_UNDECLARED"

    readback = r.get("config_readback_ok")
    if code_i == 0 and (readback is True or readback is None) and loaded is True:
        if declared is not None and consumed is not None and declared == consumed:
            return "OK"
        if declared is None and consumed is None:
            return "OK"
        if declared is not None and consumed is None:
            return "FAIL/DECLARED_NOT_CONSUMED"
        return "OK"

    if code_i is not None and code_i != 0:
        return "FAIL"

    if loaded is True and code_i == 0:
        return "OK"

    return "UNKNOWN/CONSUMER_LOAD_UNDECLARED"


NEW_ROWS = [
  # Observed: readback OK + exit 0 but production read another section
  ("S32-mf-section-mismatch", "S32", "observed_shape_desensitized(xue)",
   {"exit_code": 0, "config_readback_ok": True, "consumer_loaded": True,
    "declared_section_id": "prod.v3", "consumed_section_id": "prod.v2-legacy"},
   "FAIL/DECLARED_NOT_CONSUMED", True),
  # Readback OK + exit 0 + consumer never loaded
  ("S32-mf-not-loaded", "S32", "observed_shape_desensitized(xue)",
   {"exit_code": 0, "config_readback_ok": True, "consumer_loaded": False,
    "declared_section_id": "rules.a"},
   "FAIL/DECLARED_NOT_CONSUMED", True),
  # Exit 0 alone, undeclared consumer channel
  ("S32-ct-undeclared", "S32", "hand_built",
   {"exit_code": 0, "config_readback_ok": True},
   "UNKNOWN/CONSUMER_LOAD_UNDECLARED", True),
  # Declared present, consumed missing while claiming loaded
  ("S32-mf-consumed-missing", "S32", "hand_built",
   {"exit_code": 0, "config_readback_ok": True, "consumer_loaded": True,
    "declared_section_id": "rules.a", "consumed_section_id": None},
   "FAIL/DECLARED_NOT_CONSUMED", True),
  # Green: loaded + matching sections
  ("S32-gt-matched-sections", "S32", "hand_built",
   {"exit_code": 0, "config_readback_ok": True, "consumer_loaded": True,
    "declared_section_id": "prod.v3", "consumed_section_id": "prod.v3"},
   "OK", False),
  # Green: loaded True, no section ids needed
  ("S32-gt-loaded-no-sections", "S32", "hand_built",
   {"exit_code": 0, "config_readback_ok": True, "consumer_loaded": True},
   "OK", False),
]

FNS = dict(v19.FNS)
FNS.update({"S32": (s32_naive, s32_struct)})
ROWS = list(v19.ROWS) + NEW_ROWS
CANT_TELL = ("UNKNOWN", "UNDECIDABLE", "RETRYABLE")

def main():
    ok = 0; out = []; naive_wrong = 0
    for rid, shape, prov, arg, exp, mf in ROWS:
        naive, struct = FNS[shape]
        g, n = struct(arg), naive(arg)
        passed = (g == exp) and ((n != exp) if mf else (n == exp))
        naive_wrong += (n != exp)
        ok += passed
        out.append({"id": rid, "shape": shape, "provenance": prov, "expected": exp,
                    "struct": g, "naive": n, "must_fail_arm": mf, "pass": passed})
    ct = [r for r in out if r["expected"].split("/")[0] in CANT_TELL]
    forced = sum(1 for r in ct if r["naive"] in ("OK", "FAIL"))
    ctl = forced == len(ct)
    ok += ctl
    total = len(ROWS) + 1
    new_wrong = sum(1 for r in out if r["shape"] == "S32" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.20", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_20.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL", r["id"], "struct", r["struct"], "naive", r["naive"], "exp", r["expected"])
    if not ctl:
        print("FAIL forced-verdict-control", forced, "of", len(ct))
    sys.exit(0 if ok == total else 1)

if __name__ == "__main__":
    main()
