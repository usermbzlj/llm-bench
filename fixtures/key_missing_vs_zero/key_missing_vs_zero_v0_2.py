#!/usr/bin/env python3
"""KEY_MISSING_VS_ZERO v0.2

Hand-built, structure-only fixture (provenance=hand_built on every row; no
telemetry implied). v0.1 rows by Flux Scout. v0.2 adds, with credit:
  - PRESENT_BLANK as a 4th presence state (fn-deepseek-harness): "" / "  "
    is neither REAL_ZERO nor FIELD_ABSENT nor EXPLICIT_NULL. Flat rows carry
    a tri-state presence column `presence` in {present, present_blank,
    explicit_null, key_missing}; bool-only presence is accepted for v0.1
    compatibility but a bool cannot express PRESENT_BLANK.
  - STRICT_PRESENCE (fn-deepseek-harness): presence must be validated on the
    raw payload, not inferred from a normalizer default. A flat row whose
    presence disagrees with its value (presence=key_missing but value=0)
    -> PRESENCE_VALUE_CONFLICT, never green.
  - SEMANTICALLY_STALE (DuMate-小韭菜): well-formed response, key present,
    value 0, but as_of < requested_at -> SEMANTICALLY_STALE, not REAL_ZERO.
    Missing as_of when requested_at is set -> AS_OF_MISSING (UNDECIDABLE tier).
  - EXIT_CODE control (fn-deepseek-harness): process rc!=0 with empty stdout
    (e.g. rc=127 unknown command) -> CAPABILITY_MISSING, never parsed as an
    empty/zero payload. rc==0 + empty stdout -> EMPTY_OUTPUT (not REAL_ZERO).
analyze_only. Stdlib only.
"""
from __future__ import annotations
import json, sys

_MISSING = object()
PRESENCE = {"present", "present_blank", "explicit_null", "key_missing"}


def classify_payload(payload, key="exec_value", requested_at=None):
    if payload is None:
        return "UNDECIDABLE"
    v = payload.get(key, _MISSING)
    if v is _MISSING:
        return "FIELD_ABSENT"
    if v is None:
        return "EXPLICIT_NULL"
    if isinstance(v, str) and v.strip() == "":
        return "PRESENT_BLANK"
    if requested_at is not None:
        as_of = payload.get("as_of", _MISSING)
        if as_of is _MISSING or as_of is None:
            return "AS_OF_MISSING"
        if as_of < requested_at:
            return "SEMANTICALLY_STALE"
    if v == 0:
        return "REAL_ZERO"
    return "NONZERO"


def classify_flat(row):
    p = row.get("presence", _MISSING)
    if p is _MISSING:  # v0.1 bool compatibility
        fp = row.get("field_present", _MISSING)
        if fp is _MISSING or fp is None:
            return "UNDECIDABLE"
        p = "present" if fp is True else "key_missing" if fp is False else None
    if p not in PRESENCE:
        return "UNDECIDABLE"
    v = row.get("exec_value", _MISSING)
    if p == "key_missing":
        return "FIELD_ABSENT" if v is _MISSING else "PRESENCE_VALUE_CONFLICT"
    if p == "explicit_null":
        return "EXPLICIT_NULL" if v is None else "PRESENCE_VALUE_CONFLICT"
    if p == "present_blank":
        return "PRESENT_BLANK" if isinstance(v, str) and v.strip() == "" else "PRESENCE_VALUE_CONFLICT"
    if v is _MISSING or v is None or (isinstance(v, str) and v.strip() == ""):
        return "PRESENCE_VALUE_CONFLICT"
    return "REAL_ZERO" if v == 0 else "NONZERO"


def classify_process(rc, stdout):
    if rc != 0:
        return "CAPABILITY_MISSING" if not stdout.strip() else "PROCESS_FAILED"
    if not stdout.strip():
        return "EMPTY_OUTPUT"
    try:
        return classify_payload(json.loads(stdout))
    except ValueError:
        return "PARSE_FAILED"


def buggy_normalize(row):
    out = dict(row)
    out.setdefault("field_present", True)  # the v0.1 defect
    return out


def check_normalizer(normalize):
    return "NORMALIZER_OK" if classify_flat(normalize({"exec_value": 0})) == "UNDECIDABLE" \
        else "NORMALIZER_PRESENCE_DEFAULTED"


H = {"provenance": "hand_built"}
CASES = [
    # v0.1 (Flux Scout)
    dict(H, id="row_a", author="Flux Scout", payload={"exec_value": 0}, expect="REAL_ZERO"),
    dict(H, id="row_b", author="Flux Scout", payload={}, expect="FIELD_ABSENT"),
    dict(H, id="row_n", author="Flux Scout", payload={"exec_value": None}, expect="EXPLICIT_NULL"),
    dict(H, id="flat_a", author="Flux Scout", flat={"field_present": True, "exec_value": 0}, expect="REAL_ZERO"),
    dict(H, id="flat_b", author="Flux Scout", flat={"field_present": False}, expect="FIELD_ABSENT"),
    dict(H, id="NC1_stripped", author="Flux Scout", flat={"exec_value": 0}, expect="UNDECIDABLE"),
    # v0.2 PRESENT_BLANK + strict tri-state (fn-deepseek-harness)
    dict(H, id="blank_payload", author="fn-deepseek-harness", payload={"exec_value": ""}, expect="PRESENT_BLANK"),
    dict(H, id="ws_payload", author="fn-deepseek-harness", payload={"exec_value": "  "}, expect="PRESENT_BLANK"),
    dict(H, id="flat_blank", author="fn-deepseek-harness", flat={"presence": "present_blank", "exec_value": ""}, expect="PRESENT_BLANK"),
    dict(H, id="flat_null", author="fn-deepseek-harness", flat={"presence": "explicit_null", "exec_value": None}, expect="EXPLICIT_NULL"),
    dict(H, id="flat_missing", author="fn-deepseek-harness", flat={"presence": "key_missing"}, expect="FIELD_ABSENT"),
    dict(H, id="MF_conflict_missing_but_zero", author="fn-deepseek-harness", flat={"presence": "key_missing", "exec_value": 0}, expect="PRESENCE_VALUE_CONFLICT"),
    dict(H, id="MF_conflict_present_but_blank", author="fn-deepseek-harness", flat={"presence": "present", "exec_value": ""}, expect="PRESENCE_VALUE_CONFLICT"),
    dict(H, id="MF_unknown_presence", author="fn-deepseek-harness", flat={"presence": "maybe", "exec_value": 0}, expect="UNDECIDABLE"),
    # v0.2 SEMANTICALLY_STALE (DuMate-小韭菜)
    dict(H, id="fresh_zero", author="DuMate-小韭菜", payload={"exec_value": 0, "as_of": 1000}, requested_at=1000, expect="REAL_ZERO"),
    dict(H, id="stale_zero", author="DuMate-小韭菜", payload={"exec_value": 0, "as_of": 940}, requested_at=1000, expect="SEMANTICALLY_STALE"),
    dict(H, id="as_of_missing", author="DuMate-小韭菜", payload={"exec_value": 0}, requested_at=1000, expect="AS_OF_MISSING"),
    # v0.2 exit-code controls (fn-deepseek-harness)
    dict(H, id="rc127_empty", author="fn-deepseek-harness", proc=(127, ""), expect="CAPABILITY_MISSING"),
    dict(H, id="rc0_empty", author="fn-deepseek-harness", proc=(0, ""), expect="EMPTY_OUTPUT"),
    dict(H, id="rc0_zero", author="fn-deepseek-harness", proc=(0, '{"exec_value": 0}'), expect="REAL_ZERO"),
    dict(H, id="rc1_stderrish", author="fn-deepseek-harness", proc=(1, "error: boom"), expect="PROCESS_FAILED"),
]


def run():
    results, ok = [], 0
    for c in CASES:
        if "proc" in c:
            got = classify_process(*c["proc"])
        elif "payload" in c:
            got = classify_payload(c["payload"], requested_at=c.get("requested_at"))
        else:
            got = classify_flat(c["flat"])
        p = got == c["expect"]
        ok += p
        results.append({"id": c["id"], "author": c["author"], "expect": c["expect"],
                        "got": got, "pass": p, "provenance": c["provenance"]})
    extra = [
        ("TWIN_NULL_NOT_ABSENT", classify_payload({"exec_value": None}) != "FIELD_ABSENT"),
        ("TWIN_BLANK_NOT_ZERO", classify_payload({"exec_value": ""}) != "REAL_ZERO"),
        ("TWIN_STALE_NOT_ZERO", classify_payload({"exec_value": 0, "as_of": 1}, requested_at=2) != "REAL_ZERO"),
        ("NC2_HONEST_NORMALIZER", check_normalizer(lambda r: dict(r)) == "NORMALIZER_OK"),
        ("NC2_BUGGY_NORMALIZER_CAUGHT", check_normalizer(buggy_normalize) == "NORMALIZER_PRESENCE_DEFAULTED"),
    ]
    for name, p in extra:
        ok += p
        results.append({"id": name, "pass": p})
    return {"fixture": "KEY_MISSING_VS_ZERO", "version": "0.2",
            "selftest": f"{ok}/{len(results)}", "all_pass": ok == len(results), "results": results}


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out["all_pass"] else 1)
