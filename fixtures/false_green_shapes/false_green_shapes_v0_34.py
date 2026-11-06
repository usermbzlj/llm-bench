#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.34

Adds two peer-supplied shapes on top of v0.33 (prior files untouched; S7-S50
rows re-run here by import so one command checks S7-S52).

  S51 TRI_STATE_FLATTENED_TO_BOOL / CONSUMER_BOOL_FLATTEN_FALSE_GREEN
      Schema may declare tri-state (unknown/true/false), but consumer sites
      silently flatten unknown→bool. Four common flatten points:
        - serialization default (missing → False/True)
        - null-as-unsupported → False
        - enum else-fallback → bool
        - multi-path aggregation with `or` (unknown or False → False)
      Any flatten means upstream fine-grained judgment is wasted AND no error
      is raised — classic silent false green.
      Green only when ALL hold while claiming ok:
        - tri_state_schema is True (schema declares tri-state)
        - consumer_preserves_unknown is True
        - flatten_site is None or "none"
      Rules:
        - claiming OK with tri_state_schema True and consumer_preserves_unknown
          False → FAIL/TRI_STATE_FLATTENED_TO_BOOL
        - claiming OK with flatten_site in known sites → FAIL/TRI_STATE_FLATTENED_TO_BOOL
        - claiming OK with tri_state_schema True but consumer_preserves_unknown
          undeclared → UNKNOWN/CONSUMER_PRESERVES_UNKNOWN_UNDECLARED
        - claiming OK with tri_state_schema undeclared → UNKNOWN/TRI_STATE_SCHEMA_UNDECLARED
      Naive greens: status==ok / exit_code==0 / ok True / bool(value) alone.
      Credit: 青禾 (EigenFlux broadcast — four silent flatten sites).

  S52 PARAM_PREFREEZE_DRIFT / EFFECTIVE_OR_DECLARED_DRIFT_FALSE_GREEN
      After params are pre-frozen, claiming a run OK must compare three digests:
        declared_params_digest, frozen_params_digest, effective_params_digest
      Rules (credit 码不停蹄 field list + ABC):
        A. declared==frozen and effective!=frozen → FAIL/EFFECTIVE_DRIFT
        B. effective==frozen but readback_hit_rate < 1.0 → UNKNOWN/UNVERIFIED
           (not counted in pass denominator; not a positive)
        C. declared!=frozen without explicit override → FAIL/DECLARED_DRIFT
        - claiming OK with any digest undeclared → UNKNOWN/*_UNDECLARED
        - claiming OK with digests equal and hit_rate==1.0 → OK
      Naive greens: status==ok / exit_code==0 / ok True / frozen_at present alone.
      Credit: 码不停蹄 (EigenFlux PM — 10-field structure + ABC rules).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_34.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_33 as v33

FLATTEN_SITES = (
    "serialization_default",
    "null_as_unsupported",
    "enum_else_fallback",
    "multipath_or",
)


def s51_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    if isinstance(r.get("value"), bool):
        return "OK"
    return "FAIL"


def s51_struct(r):
    claiming = (
        r.get("exit_code") == 0
        or r.get("status") == "ok"
        or r.get("ok") is True
    )
    if not claiming:
        return "FAIL"
    if "tri_state_schema" not in r:
        return "UNKNOWN/TRI_STATE_SCHEMA_UNDECLARED"
    if r.get("tri_state_schema") is not True:
        # not a tri-state schema claim path
        return "OK"
    site = r.get("flatten_site")
    if site in FLATTEN_SITES:
        return "FAIL/TRI_STATE_FLATTENED_TO_BOOL"
    if "consumer_preserves_unknown" not in r:
        return "UNKNOWN/CONSUMER_PRESERVES_UNKNOWN_UNDECLARED"
    if r.get("consumer_preserves_unknown") is not True:
        return "FAIL/TRI_STATE_FLATTENED_TO_BOOL"
    return "OK"


def s52_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    if r.get("frozen_at") is not None:
        return "OK"
    return "FAIL"


def s52_struct(r):
    claiming = (
        r.get("exit_code") == 0
        or r.get("status") == "ok"
        or r.get("ok") is True
    )
    if not claiming:
        return "FAIL"
    for k in (
        "declared_params_digest",
        "frozen_params_digest",
        "effective_params_digest",
    ):
        if k not in r:
            return f"UNKNOWN/{k.upper()}_UNDECLARED"
    declared = r.get("declared_params_digest")
    frozen = r.get("frozen_params_digest")
    effective = r.get("effective_params_digest")
    if not all(isinstance(x, str) for x in (declared, frozen, effective)):
        return "UNKNOWN/DIGEST_NOT_STR"
    explicit_override = r.get("explicit_override") is True
    if declared != frozen and not explicit_override:
        return "FAIL/DECLARED_DRIFT"
    if declared == frozen and effective != frozen:
        return "FAIL/EFFECTIVE_DRIFT"
    if "readback_hit_rate" not in r:
        return "UNKNOWN/READBACK_HIT_RATE_UNDECLARED"
    try:
        hit = float(r["readback_hit_rate"])
    except (TypeError, ValueError):
        return "UNKNOWN/READBACK_HIT_RATE_NOT_FLOAT"
    if effective == frozen and hit < 1.0:
        return "UNKNOWN/UNVERIFIED"
    return "OK"


NEW_ROWS = [
  ("S51-mf-serialize-default", "S51", "observed_shape_desensitized(青禾)",
   {"tri_state_schema": True, "flatten_site": "serialization_default",
    "consumer_preserves_unknown": False, "value": False,
    "status": "ok", "exit_code": 0},
   "FAIL/TRI_STATE_FLATTENED_TO_BOOL", True),
  ("S51-mf-multipath-or", "S51", "observed_shape_desensitized(青禾)",
   {"tri_state_schema": True, "flatten_site": "multipath_or",
    "consumer_preserves_unknown": False, "status": "ok", "ok": True},
   "FAIL/TRI_STATE_FLATTENED_TO_BOOL", True),
  ("S51-mf-null-unsupported", "S51", "hand_built",
   {"tri_state_schema": True, "flatten_site": "null_as_unsupported",
    "status": "ok", "exit_code": 0},
   "FAIL/TRI_STATE_FLATTENED_TO_BOOL", True),
  ("S51-gt-preserves-unknown", "S51", "hand_built",
   {"tri_state_schema": True, "flatten_site": "none",
    "consumer_preserves_unknown": True, "value": None,
    "status": "ok", "exit_code": 0},
   "OK", False),
  ("S51-ct-preserves-undeclared", "S51", "observed_shape_desensitized(青禾)",
   {"tri_state_schema": True, "status": "ok", "exit_code": 0},
   "UNKNOWN/CONSUMER_PRESERVES_UNKNOWN_UNDECLARED", True),
  ("S51-ct-schema-undeclared", "S51", "hand_built",
   {"status": "ok", "exit_code": 0, "value": False},
   "UNKNOWN/TRI_STATE_SCHEMA_UNDECLARED", True),
  ("S52-mf-effective-drift", "S52", "observed_shape_desensitized(码不停蹄)",
   {"declared_params_digest": "aaa", "frozen_params_digest": "aaa",
    "effective_params_digest": "bbb", "readback_hit_rate": 1.0,
    "status": "ok", "exit_code": 0},
   "FAIL/EFFECTIVE_DRIFT", True),
  ("S52-mf-declared-drift", "S52", "observed_shape_desensitized(码不停蹄)",
   {"declared_params_digest": "aaa", "frozen_params_digest": "ccc",
    "effective_params_digest": "ccc", "readback_hit_rate": 1.0,
    "status": "ok", "ok": True},
   "FAIL/DECLARED_DRIFT", True),
  ("S52-ct-unverified-hitrate", "S52", "observed_shape_desensitized(码不停蹄)",
   {"declared_params_digest": "aaa", "frozen_params_digest": "aaa",
    "effective_params_digest": "aaa", "readback_hit_rate": 0.75,
    "frozen_at": 1, "status": "ok"},
   "UNKNOWN/UNVERIFIED", True),
  ("S52-gt-aligned", "S52", "hand_built",
   {"declared_params_digest": "aaa", "frozen_params_digest": "aaa",
    "effective_params_digest": "aaa", "readback_hit_rate": 1.0,
    "status": "ok", "exit_code": 0},
   "OK", False),
  ("S52-ct-effective-undeclared", "S52", "hand_built",
   {"declared_params_digest": "aaa", "frozen_params_digest": "aaa",
    "status": "ok", "exit_code": 0},
   "UNKNOWN/EFFECTIVE_PARAMS_DIGEST_UNDECLARED", True),
]

FNS = dict(v33.FNS)
FNS.update({"S51": (s51_naive, s51_struct), "S52": (s52_naive, s52_struct)})
ROWS = list(v33.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S51", "S52") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.34", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_34.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
