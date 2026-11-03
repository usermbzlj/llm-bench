#!/usr/bin/env python3
"""KEY_MISSING_VS_ZERO v0.1

Structure-only, hand-built fixture. Rows authored by Flux Scout (EigenFlux),
NOT telemetry: provenance=hand_built on every row so nothing implies an
observed source.

Case: same source numeric value 0, two encodings.
  row_a  {"exec_value": 0}            -> REAL_ZERO      (key present, explicit 0)
  row_b  {}                           -> FIELD_ABSENT   (key omitted outright)
Twin:
  row_n  {"exec_value": null}         -> EXPLICIT_NULL  (must NOT pass as FIELD_ABSENT)
Negative controls:
  NC1  presence bit stripped from the judge input (no raw payload, only
       exec_value=0) -> MUST be UNDECIDABLE specifically, never GREEN and
       never a guessed REAL_ZERO/FIELD_ABSENT.
  NC2  buggy normalizer that defaults a missing presence bit to present ->
       harness MUST flag NORMALIZER_PRESENCE_DEFAULTED (the defect this
       case exists to catch).
analyze_only. Stdlib only.
"""
from __future__ import annotations
import json, sys

_MISSING = object()


def classify_payload(payload: dict | None, key: str = "exec_value") -> str:
    """Classify from the raw payload (presence is observable)."""
    if payload is None:
        return "UNDECIDABLE"
    v = payload.get(key, _MISSING)
    if v is _MISSING:
        return "FIELD_ABSENT"
    if v is None:
        return "EXPLICIT_NULL"
    if v == 0:
        return "REAL_ZERO"
    return "NONZERO"


def classify_flat(row: dict) -> str:
    """Classify from flattened columns; presence must be explicit."""
    fp = row.get("field_present", _MISSING)
    if fp is _MISSING or fp is None:
        return "UNDECIDABLE"
    if fp is False:
        return "FIELD_ABSENT"
    v = row.get("exec_value", _MISSING)
    if v is None:
        return "EXPLICIT_NULL"
    if v == 0:
        return "REAL_ZERO"
    return "NONZERO"


def buggy_normalize(row: dict) -> dict:
    out = dict(row)
    out.setdefault("field_present", True)  # the defect
    return out


def check_normalizer(normalize) -> str:
    probe = {"exec_value": 0}  # presence bit absent
    got = classify_flat(normalize(probe))
    return "NORMALIZER_OK" if got == "UNDECIDABLE" else "NORMALIZER_PRESENCE_DEFAULTED"


CASES = [
    {"id": "row_a", "provenance": "hand_built", "author": "Flux Scout",
     "payload": {"exec_value": 0}, "expect": "REAL_ZERO"},
    {"id": "row_b", "provenance": "hand_built", "author": "Flux Scout",
     "payload": {}, "expect": "FIELD_ABSENT"},
    {"id": "row_n", "provenance": "hand_built", "author": "Flux Scout",
     "payload": {"exec_value": None}, "expect": "EXPLICIT_NULL"},
    {"id": "flat_a", "provenance": "hand_built", "author": "Flux Scout",
     "flat": {"field_present": True, "exec_value": 0}, "expect": "REAL_ZERO"},
    {"id": "flat_b", "provenance": "hand_built", "author": "Flux Scout",
     "flat": {"field_present": False, "exec_value": 0}, "expect": "FIELD_ABSENT"},
    {"id": "NC1_stripped_a", "provenance": "hand_built", "author": "Flux Scout",
     "flat": {"exec_value": 0}, "expect": "UNDECIDABLE"},
    {"id": "NC1_stripped_b", "provenance": "hand_built", "author": "Flux Scout",
     "flat": {"exec_value": 0}, "expect": "UNDECIDABLE"},
]


def run() -> dict:
    results, ok = [], 0
    for c in CASES:
        got = classify_payload(c["payload"]) if "payload" in c else classify_flat(c["flat"])
        passed = got == c["expect"]
        ok += passed
        results.append({"id": c["id"], "expect": c["expect"], "got": got,
                        "pass": passed, "provenance": c["provenance"]})
    # twin guard: null must never be read as absent
    twin = classify_payload({"exec_value": None}) != "FIELD_ABSENT"
    nc2_honest = check_normalizer(lambda r: dict(r)) == "NORMALIZER_OK"
    nc2_buggy = check_normalizer(buggy_normalize) == "NORMALIZER_PRESENCE_DEFAULTED"
    extra = [("TWIN_NULL_NOT_ABSENT", twin), ("NC2_HONEST_NORMALIZER", nc2_honest),
             ("NC2_BUGGY_NORMALIZER_CAUGHT", nc2_buggy)]
    for name, p in extra:
        ok += p
        results.append({"id": name, "pass": p})
    total = len(results)
    return {"fixture": "KEY_MISSING_VS_ZERO", "version": "0.1",
            "selftest": f"{ok}/{total}", "all_pass": ok == total, "results": results}


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out["all_pass"] else 1)
