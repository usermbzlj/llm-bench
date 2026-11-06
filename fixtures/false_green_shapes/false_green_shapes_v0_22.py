#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.22

Adds one peer-supplied shape on top of v0.21 (prior files untouched; S7-S33
rows re-run here by import so one command checks S7-S34).

  S34 DIRECTION_FLIP_PRESERVE_NUMBERS  A summary that preserves the numeric
                              threshold but inverts the decision direction
                              (e.g. 「低于阈值禁止入场」→「低于阈值允许入场」)
                              must not green-wash under keyword/number match.
                              Naive treats
                              (threshold_value matches source AND
                               polarity_token_present) as OK.
                              Struct:
                                - source_direction or summary_direction
                                  undeclared -> UNKNOWN/DIRECTION_UNDECLARED
                                - both declared and opposite ->
                                  FAIL/DIRECTION_FLIP_PRESERVE_NUMBERS
                                  (even when threshold_value identical)
                                - both declared and same + threshold match
                                  + rule_version present -> OK
                                - rule_version missing while claiming
                                  dual-path pass -> UNKNOWN/RULE_VERSION_UNDECLARED
                                - source_fields / summary_fields provenance
                                  absent while claiming dual-path ->
                                  UNKNOWN/FIELD_SOURCE_UNDECLARED
                              Credit: 凯瑞's Agent / Kyrie (EigenFlux —
                              「摘要把『低于阈值禁止入场』写成『低于阈值允许入场』，
                              数值没变、决策方向反了；原文/摘要同判据负控」).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_22.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_21 as v21


def _norm_dir(d):
    if d is None:
        return None
    if not isinstance(d, str):
        return None
    s = d.strip().lower()
    if s in ("prohibit", "forbid", "deny", "block", "禁止", "否决", "拦截"):
        return "prohibit"
    if s in ("allow", "permit", "pass", "批准", "允许", "放行"):
        return "allow"
    return s


def s34_naive(r):
    # Naive: threshold number match + some polarity token present => OK
    tv = r.get("threshold_value")
    stv = r.get("source_threshold_value")
    if tv is not None and stv is not None and tv == stv:
        # any polarity-ish token presence counts as "checked"
        if r.get("polarity_token_present") is True or r.get("keyword_hit") is True:
            return "OK"
        if r.get("dual_path_claimed") is True:
            return "OK"
    if r.get("dual_path_claimed") is True and r.get("threshold_value") is not None:
        return "OK"
    return "FAIL"


def s34_struct(r):
    src = _norm_dir(r.get("source_direction"))
    smy = _norm_dir(r.get("summary_direction"))
    if src is None or smy is None:
        return "UNKNOWN/DIRECTION_UNDECLARED"

    if r.get("dual_path_claimed") is True:
        if r.get("rule_version") is None:
            return "UNKNOWN/RULE_VERSION_UNDECLARED"
        sf = r.get("source_fields")
        mf = r.get("summary_fields")
        if sf is None or mf is None:
            return "UNKNOWN/FIELD_SOURCE_UNDECLARED"

    if src != smy:
        return "FAIL/DIRECTION_FLIP_PRESERVE_NUMBERS"

    tv = r.get("threshold_value")
    stv = r.get("source_threshold_value", tv)
    if tv is not None and stv is not None and tv != stv:
        return "FAIL/DIRECTION_FLIP_PRESERVE_NUMBERS"

    if r.get("rule_version") is None and r.get("dual_path_claimed") is True:
        return "UNKNOWN/RULE_VERSION_UNDECLARED"

    return "OK"


NEW_ROWS = [
  # Observed: numbers intact, decision polarity inverted
  ("S34-mf-polarity-flip", "S34", "observed_shape_desensitized(Kyrie)",
   {"threshold_value": 0.3, "source_threshold_value": 0.3,
    "source_direction": "prohibit", "summary_direction": "allow",
    "polarity_token_present": True, "keyword_hit": True,
    "dual_path_claimed": True, "rule_version": "risk-gate-v2",
    "source_fields": ["threshold", "direction"],
    "summary_fields": ["threshold", "direction"]},
   "FAIL/DIRECTION_FLIP_PRESERVE_NUMBERS", True),
  # Direction undeclared while claiming dual-path
  ("S34-ct-direction-undeclared", "S34", "hand_built",
   {"threshold_value": 0.3, "source_threshold_value": 0.3,
    "polarity_token_present": True, "dual_path_claimed": True,
    "rule_version": "risk-gate-v2"},
   "UNKNOWN/DIRECTION_UNDECLARED", True),
  # Dual-path claimed but rule_version missing
  ("S34-ct-rule-version-undeclared", "S34", "hand_built",
   {"threshold_value": 0.3, "source_threshold_value": 0.3,
    "source_direction": "prohibit", "summary_direction": "prohibit",
    "dual_path_claimed": True,
    "source_fields": ["threshold", "direction"],
    "summary_fields": ["threshold", "direction"]},
   "UNKNOWN/RULE_VERSION_UNDECLARED", True),
  # Dual-path claimed but field provenance missing
  ("S34-ct-field-source-undeclared", "S34", "hand_built",
   {"threshold_value": 0.3, "source_threshold_value": 0.3,
    "source_direction": "allow", "summary_direction": "allow",
    "dual_path_claimed": True, "rule_version": "risk-gate-v2"},
   "UNKNOWN/FIELD_SOURCE_UNDECLARED", True),
  # Green: same direction, numbers match, dual-path with provenance
  ("S34-gt-same-direction", "S34", "hand_built",
   {"threshold_value": 0.3, "source_threshold_value": 0.3,
    "source_direction": "prohibit", "summary_direction": "prohibit",
    "dual_path_claimed": True, "rule_version": "risk-gate-v2",
    "source_fields": ["threshold", "direction"],
    "summary_fields": ["threshold", "direction"]},
   "OK", False),
  # Green: allow/allow with Chinese tokens normalized
  ("S34-gt-zh-allow", "S34", "hand_built",
   {"threshold_value": 100, "source_threshold_value": 100,
    "source_direction": "允许", "summary_direction": "放行",
    "dual_path_claimed": True, "rule_version": "entry-v1",
    "source_fields": ["阈值", "方向"],
    "summary_fields": ["阈值", "方向"]},
   "OK", False),
]

FNS = dict(v21.FNS)
FNS.update({"S34": (s34_naive, s34_struct)})
ROWS = list(v21.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S34" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.22", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_22.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL", r["id"], "struct", r["struct"], "naive", r["naive"], "exp", r["expected"])
    if not ctl:
        print("FAIL forced-verdict-control", forced, "of", len(ct))
    sys.exit(0 if ok == total else 1)

if __name__ == "__main__":
    main()
