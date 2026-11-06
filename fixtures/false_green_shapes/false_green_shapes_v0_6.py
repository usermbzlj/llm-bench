#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.6

Adds one peer-supplied shape on top of v0.5 (prior files untouched; S7-S17
rows re-run here by import so one command checks S7-S18).

  S18 SAFE_INTEGER_BOUNDARY   JSON number ids above JS/IEEE Number.MAX_SAFE_INTEGER
                              (2^53-1 = 9007199254740991) silently lose low bits when
                              coerced through float64 / JS Number. HTTP 200 + parse_ok
                              still looks green while the ledger key no longer matches
                              the business id (accepted ≠ mutated). Struct:
                                - number id with abs(id) > SAFE -> FAIL/SAFE_INTEGER_OVERFLOW
                                - number id with abs(id) <= SAFE alone is OK for this shape
                                  (mod64 mask remains S17)
                                - string id of any magnitude that round-trips exact -> OK
                                - status 200 + parse_ok but ledger_id != source_id ->
                                  FAIL/LEDGER_ID_MISMATCH (read-after-write)
                              Synthetic boundary credit: 麦麦 (owe synth ID>2^53).
                              Observed corroboration (desensitized public shape): xiaoyou的dsh
                              (IEEE-754 JSON number id corruption; HTTP accepted but ledger
                              not updated; treat non-arithmetic ids as strings + verify via
                              read-back / business key).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_6.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_5 as v5

SAFE = 2**53 - 1  # 9007199254740991
# Odd integers above SAFE are not float64-exact (2^53+1 collapses).
ABOVE = SAFE + 1  # 9007199254740992 via float64 on many platforms; != ABOVE
AT_SAFE = SAFE
# Observed snowflake that loses low bits under float64 (DeepSeek/S17 family; also xiaoyou shape)
SNOW = 376989689443254279
SNOW_CORRUPTED = int(float(SNOW))  # -> 376989689443254272


def _as_int(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str) and v.lstrip("-").isdigit():
        return int(v)
    return None


def s18_naive(r):
    # Naive: HTTP accepted + JSON parse ok + any id present -> OK
    if r.get("http_status", 200) != 200:
        return "FAIL"
    if r.get("parse_ok") is False:
        return "FAIL"
    if r.get("source_id") is None and not (r.get("number_ids") or r.get("string_ids")):
        return "FAIL"
    return "OK"


def s18_struct(r):
    if r.get("parse_ok") is False:
        return "FAIL"
    # Read-after-write: accepted response must match ledger/business key
    src = r.get("source_id")
    led = r.get("ledger_id")
    if src is not None and led is not None and str(src) != str(led):
        return "FAIL/LEDGER_ID_MISMATCH"

    for s in r.get("string_ids") or []:
        if not isinstance(s, str):
            return "FAIL/STRING_ID_TYPE"
        # string must round-trip; if marked coerced via float, check loss
        if r.get("string_coerced_via_float64"):
            n = _as_int(s)
            if n is not None and str(int(float(n))) != s:
                return "FAIL/SAFE_INTEGER_OVERFLOW"

    for n in r.get("number_ids") or []:
        iv = _as_int(n)
        if iv is None:
            return "FAIL/NUMBER_ID_TYPE"
        if abs(iv) > SAFE:
            # Prove loss under float64 when platform would coerce
            if r.get("number_coerced_via_float64", True):
                if int(float(iv)) != iv:
                    return "FAIL/SAFE_INTEGER_OVERFLOW"
                # even if this CPython preserves (unlikely for ABOVE), contract says overflow
                return "FAIL/SAFE_INTEGER_OVERFLOW"
            return "FAIL/SAFE_INTEGER_OVERFLOW"

    return "OK"


NEW_ROWS = [
  # Synthetic must-fail: number id just above SAFE
  ("S18-mf-above", "S18", "synthetic(麦麦)",
   {"parse_ok": True, "http_status": 200,
    "source_id": str(ABOVE), "ledger_id": str(ABOVE),
    "number_ids": [ABOVE], "string_ids": [],
    "number_coerced_via_float64": True},
   "FAIL/SAFE_INTEGER_OVERFLOW", True),
  # Observed corroboration: snowflake as number -> corrupted ledger key
  ("S18-mf-ledger", "S18", "observed_shape_desensitized(xiaoyou的dsh)",
   {"parse_ok": True, "http_status": 200,
    "source_id": str(SNOW), "ledger_id": str(SNOW_CORRUPTED),
    "number_ids": [SNOW], "string_ids": [],
    "number_coerced_via_float64": True},
   "FAIL/LEDGER_ID_MISMATCH", True),
  # At SAFE boundary as number: still exact -> OK for this shape
  ("S18-gt-at-safe", "S18", "synthetic(麦麦)",
   {"parse_ok": True, "http_status": 200,
    "source_id": str(AT_SAFE), "ledger_id": str(AT_SAFE),
    "number_ids": [AT_SAFE], "string_ids": [],
    "number_coerced_via_float64": True},
   "OK", False),
  # Green twin: string ids above SAFE, no float coercion
  ("S18-gt-string", "S18", "hand_built",
   {"parse_ok": True, "http_status": 200,
    "source_id": str(ABOVE), "ledger_id": str(ABOVE),
    "number_ids": [], "string_ids": [str(ABOVE), str(SNOW)],
    "number_coerced_via_float64": False},
   "OK", False),
  # Negctl: claim overflow expected but only supply <=SAFE numbers and matching ledger
  # (should be OK — not a must-fail; kept as green twin control)
  ("S18-gt-below", "S18", "hand_built",
   {"parse_ok": True, "http_status": 200,
    "source_id": "42", "ledger_id": "42",
    "number_ids": [42, AT_SAFE], "string_ids": [],
    "number_coerced_via_float64": True},
   "OK", False),
]

FNS = dict(v5.FNS)
FNS.update({"S18": (s18_naive, s18_struct)})
ROWS = list(v5.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S18" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.6", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_6.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    # debug failures
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
