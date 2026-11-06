#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.5

Adds one peer-supplied shape on top of v0.4 (prior files untouched; S7-S16
rows re-run here by import so one command checks S7-S17).

  S17 FLOAT64_MIXED_ID        JSON id fields that mix string and number, or
                              coerce large ints through IEEE-754 float64, can
                              look green when every observed id happens to be
                              a multiple of 64 (exact in float64 mantissa for
                              these magnitudes). Non-multiples lose low bits
                              (e.g. …279 -> …272, delta 7) with no error
                              surface. Naive that only parses JSON / checks
                              type presence -> OK. Struct:
                                - string id must round-trip exact bytes
                                - number id with (id % 64) != 0 ->
                                  FAIL/FLOAT64_PRECISION_LOSS
                                - number id with (id % 64) == 0 alone is
                                  UNDECIDABLE/MOD64_MASK (cannot prove loss)
                                - mixed string+number payload: dropping any
                                  id key -> FAIL/MIXED_ID_DROP
                              Observed desensitized shape credit: DeepSeek
                              Harness (five mod64==0 ids round-trip delta0;
                              …279 via float64 becomes …272; three-assert
                              fixture shape with string exact + mod64!=0
                              must-fail + mixed no-drop).

Each shape: must-fail arm (naive wrong) + green twin (+ undecidable where useful).
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_5.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_4 as v4

# Observed ids from DeepSeek Harness (desensitized public shape; not secrets).
OBS_MOD64_ZERO = [
    374108932257349632,
    375238840639553536,
    376988840805531648,
    376989689443254272,
    374801762109882368,
]
OBS_MOD64_NONZERO = 376989689443254279  # -> 376989689443254272 via float64


def _as_int(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str) and v.isdigit():
        return int(v)
    return None


def s17_naive(r):
    # Naive: JSON-shaped payload with any id-like fields present -> OK
    if r.get("parse_ok") is False:
        return "FAIL"
    ids = r.get("item_ids") or []
    if r.get("conv_id") is None and not ids:
        return "FAIL"
    return "OK"


def s17_struct(r):
    if r.get("parse_ok") is False:
        return "FAIL"
    expect = r.get("expect") or {}
    # Mixed drop: expected keys listed but missing after parse
    expected_keys = r.get("expected_id_keys") or []
    present_keys = set(r.get("present_id_keys") or [])
    for k in expected_keys:
        if k not in present_keys:
            return "FAIL/MIXED_ID_DROP"

    # String exact round-trip
    for s in r.get("string_ids") or []:
        if not isinstance(s, str):
            return "FAIL/STRING_ID_TYPE"
        if r.get("string_coerced_via_float64"):
            n = _as_int(s)
            if n is not None and str(int(float(n))) != s:
                return "FAIL/FLOAT64_PRECISION_LOSS"

    num_ids = r.get("number_ids") or []
    for n in num_ids:
        if _as_int(n) is None:
            return "FAIL/NUMBER_ID_TYPE"

    nonzero = [iv for iv in (_as_int(n) for n in num_ids) if iv is not None and iv % 64 != 0]
    zero_mod = [iv for iv in (_as_int(n) for n in num_ids) if iv is not None and iv % 64 == 0]

    # Negctl contract: claim "mod64!=0 must fail" but supply only mod64==0 -> missing negctl
    if expect.get("number_id_mod64_nonzero") == "fail" and not nonzero:
        return "FAIL/NEGCTL_MISSING_NONZERO_MOD"

    # Precision loss on nonzero-mod under float64 coercion
    if r.get("number_coerced_via_float64", True):
        for iv in nonzero:
            if int(float(iv)) != iv:
                return "FAIL/FLOAT64_PRECISION_LOSS"
        # nonzero present, expect fail, even if this platform somehow preserves bits
        if nonzero and expect.get("number_id_mod64_nonzero") == "fail":
            return "FAIL/FLOAT64_PRECISION_LOSS"

    # Only mod64==0 under coercion -> mask (cannot prove loss)
    if num_ids and zero_mod and not nonzero and r.get("number_coerced_via_float64", True):
        if all(int(float(iv)) == iv for iv in zero_mod):
            return "UNDECIDABLE/MOD64_MASK"

    if expect.get("string_ids") == "exact":
        for s in r.get("string_ids") or []:
            if not isinstance(s, str):
                return "FAIL/STRING_ID_TYPE"

    return "OK"


NEW_ROWS = [
  # Observed: only mod64==0 ids -> naive OK, struct UNDECIDABLE (mask)
  ("S17-mask", "S17", "observed_shape_desensitized",
   {"parse_ok": True, "conv_id": "376989689443254272",
    "string_ids": ["374108932257349632"],
    "number_ids": list(OBS_MOD64_ZERO),
    "number_coerced_via_float64": True,
    "expected_id_keys": ["conv_id", "item_ids"],
    "present_id_keys": ["conv_id", "item_ids"],
    "expect": {"string_ids": "exact"}},
   "UNDECIDABLE/MOD64_MASK", True),
  # Observed must-fail: nonzero mod id via float64
  ("S17-mf", "S17", "observed_shape_desensitized",
   {"parse_ok": True, "conv_id": "376989689443254272",
    "string_ids": ["374108932257349632"],
    "number_ids": [OBS_MOD64_NONZERO],
    "number_coerced_via_float64": True,
    "expected_id_keys": ["conv_id", "item_ids", "receipt.msg_id"],
    "present_id_keys": ["conv_id", "item_ids", "receipt.msg_id"],
    "expect": {"string_ids": "exact", "number_id_mod64_nonzero": "fail"}},
   "FAIL/FLOAT64_PRECISION_LOSS", True),
  # Mixed drop: number id present in source but dropped after typed parse
  ("S17-drop", "S17", "hand_built",
   {"parse_ok": True, "conv_id": "376989689443254272",
    "string_ids": ["374108932257349632"],
    "number_ids": [OBS_MOD64_NONZERO],
    "number_coerced_via_float64": True,
    "expected_id_keys": ["conv_id", "item_ids", "receipt.msg_id"],
    "present_id_keys": ["conv_id", "item_ids"],  # receipt.msg_id dropped
    "expect": {"string_ids": "exact", "number_id_mod64_nonzero": "fail"}},
   "FAIL/MIXED_ID_DROP", True),
  # Green twin: strings only, no float coercion
  ("S17-gt", "S17", "hand_built",
   {"parse_ok": True, "conv_id": "376989689443254272",
    "string_ids": ["374108932257349632", "376989689443254279"],
    "number_ids": [],
    "number_coerced_via_float64": False,
    "expected_id_keys": ["conv_id", "item_ids"],
    "present_id_keys": ["conv_id", "item_ids"],
    "expect": {"string_ids": "exact"}},
   "OK", False),
  # Hand-built: nonzero mod without coercion path but expect fail marker missing nonzero
  ("S17-mf2", "S17", "hand_built",
   {"parse_ok": True,
    "string_ids": [],
    "number_ids": [OBS_MOD64_ZERO[0]],  # only mod64==0
    "number_coerced_via_float64": True,
    "expected_id_keys": ["item_ids"],
    "present_id_keys": ["item_ids"],
    "expect": {"number_id_mod64_nonzero": "fail"}},
   "FAIL/NEGCTL_MISSING_NONZERO_MOD", True),
]

FNS = dict(v4.FNS)
FNS.update({"S17": (s17_naive, s17_struct)})
ROWS = list(v4.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S17" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.5", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_5.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
