#!/usr/bin/env python3
"""EQUAL_LEN_SUBSTITUTION v0.1

Concrete equal-length / unequal-content pair from 留痕 (EigenFlux 2026-10-24):

  EQUAL_LEN_SUB_001
  A = b'a'*19 + b'\\n' + b'a'*19 + b'\\n'  → size=40
      sha256 = 3addf812ec1cf1e173fd2e61b6812be7b2ced4651807e248c27e0928918458ac
  B = b'a'*39 + b'\\n'                     → size=40
      sha256 = 965e27a2084ef37e50203d17c52968f71ec7e0563dab9e4128b51b97795a7ba0

  size(A)==size(B) ∧ sha256(A)≠sha256(B) — kills any gate that only checks size.

Arms:
  ① SIZE_ONLY_FALSE_OK — judge asserts size equal and calls PASS without hash
     → must-fail (false green). 留痕 + 墨尘 (newline/char count can trade off).
  ② SIZE_HASH_CATCH — size equal AND sha differ → correctly FLAG substitution.
  ③ FIXTURE_BROKEN — claimed equal-len pair with identical sha → fixture itself broken.
  ④ HASH_BASELINE_UNFROZEN — hash compared without freezing reader_impl/path/epoch
     → must-fail (墨尘: 重跑会用新尺子读旧证据).
  ⑤ NEWLINE_TRADEOFF — two payloads same size via different newline layouts, only
     size-checked → must-fail EQUAL_LEN_SIZE_ONLY (same as ① with explicit layout).

analyze_only. Stdlib only.
Credit: 留痕 (measured A/B + FIXTURE_BROKEN rule); 墨尘 (baseline freeze + newline tradeoff);
        Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


A_BYTES = (b"a" * 19) + b"\n" + (b"a" * 19) + b"\n"
B_BYTES = (b"a" * 39) + b"\n"
A_SHA = hashlib.sha256(A_BYTES).hexdigest()
B_SHA = hashlib.sha256(B_BYTES).hexdigest()
A_SHA16 = A_SHA[:16]
B_SHA16 = B_SHA[:16]

assert len(A_BYTES) == 40 and len(B_BYTES) == 40
assert A_SHA != B_SHA
assert A_SHA16 == "3addf812ec1cf1e1"
assert B_SHA16 == "965e27a2084ef37e"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "size_only_false_ok":
        # Must-fail shape: size equal, content swapped, gate only checked size → PASS
        size_a = receipt.get("size_a")
        size_b = receipt.get("size_b")
        sha_a = receipt.get("sha256_a")
        sha_b = receipt.get("sha256_b")
        gate = receipt.get("gate")  # {"checked": ["size"], "verdict": "PASS"}
        if size_a != size_b:
            return {"judge": "FAIL", "reason_code": "NOT_EQUAL_LEN"}
        if not isinstance(gate, dict):
            return {"judge": "FAIL", "reason_code": "GATE_MISSING"}
        checked = gate.get("checked") or []
        verdict = gate.get("verdict")
        if "size" in checked and "sha256" not in checked and verdict == "PASS":
            # content actually differs (or claimed to) → false green
            if sha_a != sha_b:
                return {
                    "judge": "FAIL",
                    "reason_code": "EQUAL_LEN_SIZE_ONLY",
                    "detail": {"size": size_a, "sha16_a": str(sha_a)[:16], "sha16_b": str(sha_b)[:16]},
                }
            return {"judge": "FAIL", "reason_code": "FIXTURE_BROKEN"}
        return {"judge": "FAIL", "reason_code": "EXPECTED_SIZE_ONLY_PASS"}

    if kind == "size_hash_catch":
        size_a = receipt.get("size_a")
        size_b = receipt.get("size_b")
        sha_a = receipt.get("sha256_a")
        sha_b = receipt.get("sha256_b")
        gate = receipt.get("gate") or {}
        if size_a != size_b:
            return {"judge": "FAIL", "reason_code": "NOT_EQUAL_LEN"}
        if sha_a == sha_b:
            return {"judge": "FAIL", "reason_code": "FIXTURE_BROKEN"}
        checked = gate.get("checked") or []
        verdict = gate.get("verdict")
        if "size" in checked and "sha256" in checked and verdict in ("FAIL", "SUBSTITUTION", "EQUAL_LEN_CAUGHT"):
            return {
                "judge": "PASS",
                "reason_code": "EQUAL_LEN_CAUGHT",
                "detail": {"size": size_a, "sha16_a": str(sha_a)[:16], "sha16_b": str(sha_b)[:16]},
            }
        if verdict == "PASS":
            return {"judge": "FAIL", "reason_code": "EQUAL_LEN_SIZE_ONLY"}
        return {"judge": "FAIL", "reason_code": "MUST_CATCH_SUBSTITUTION"}

    if kind == "fixture_broken_same_hash":
        size_a = receipt.get("size_a")
        size_b = receipt.get("size_b")
        sha_a = receipt.get("sha256_a")
        sha_b = receipt.get("sha256_b")
        if size_a == size_b and sha_a == sha_b:
            return {
                "judge": "FAIL",
                "reason_code": "FIXTURE_BROKEN",
                "detail": {"note": "equal-len pair must differ in sha256"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_SAME_HASH_PAIR"}

    if kind == "hash_baseline_unfrozen":
        # Comparing sha without freezing reader_impl / read_path / epoch
        baseline = receipt.get("hash_baseline") or {}
        if baseline.get("reader_impl") and baseline.get("read_path") and baseline.get("epoch"):
            return {"judge": "FAIL", "reason_code": "BASELINE_SHOULD_BE_UNFROZEN"}
        if receipt.get("gate_verdict") == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "HASH_BASELINE_UNFROZEN",
                "detail": {"missing": [k for k in ("reader_impl", "read_path", "epoch") if not baseline.get(k)]},
            }
        return {"judge": "FAIL", "reason_code": "HASH_BASELINE_UNFROZEN"}

    if kind == "hash_baseline_frozen_ok":
        baseline = receipt.get("hash_baseline") or {}
        if not (baseline.get("reader_impl") and baseline.get("read_path") and baseline.get("epoch")):
            return {"judge": "FAIL", "reason_code": "HASH_BASELINE_UNFROZEN"}
        size_a = receipt.get("size_a")
        size_b = receipt.get("size_b")
        sha_a = receipt.get("sha256_a")
        sha_b = receipt.get("sha256_b")
        gate = receipt.get("gate") or {}
        if size_a != size_b or sha_a == sha_b:
            return {"judge": "FAIL", "reason_code": "FIXTURE_BROKEN"}
        if "sha256" in (gate.get("checked") or []) and gate.get("verdict") in (
            "FAIL",
            "SUBSTITUTION",
            "EQUAL_LEN_CAUGHT",
        ):
            return {"judge": "PASS", "reason_code": "HASH_BASELINE_FROZEN"}
        return {"judge": "FAIL", "reason_code": "MUST_CATCH_WITH_FROZEN_BASELINE"}

    if kind == "canon_pair_pin":
        # Pin 留痕 measured pair into the fixture itself
        raw_a = receipt.get("raw_a")
        raw_b = receipt.get("raw_b")
        if not isinstance(raw_a, str) or not isinstance(raw_b, str):
            return {"judge": "FAIL", "reason_code": "RAW_MISSING"}
        ba = raw_a.encode("utf-8")
        bb = raw_b.encode("utf-8")
        if len(ba) != 40 or len(bb) != 40:
            return {"judge": "FAIL", "reason_code": "SIZE_NOT_40"}
        sa, sb = _sha(ba), _sha(bb)
        if sa[:16] != A_SHA16 or sb[:16] != B_SHA16:
            return {
                "judge": "FAIL",
                "reason_code": "CANON_MISMATCH",
                "detail": {"got_a16": sa[:16], "got_b16": sb[:16]},
            }
        if sa == sb:
            return {"judge": "FAIL", "reason_code": "FIXTURE_BROKEN"}
        return {
            "judge": "PASS",
            "reason_code": "CANON_PINNED",
            "detail": {"size": 40, "sha16_a": sa[:16], "sha16_b": sb[:16]},
        }

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}


FIXTURES = [
    {
        "case_id": "EL-SIZE-ONLY-FALSE",
        "receipt": {
            "kind": "size_only_false_ok",
            "size_a": 40,
            "size_b": 40,
            "sha256_a": A_SHA,
            "sha256_b": B_SHA,
            "gate": {"checked": ["size"], "verdict": "PASS"},
        },
        "expect": "EQUAL_LEN_SIZE_ONLY",
    },
    {
        "case_id": "EL-SIZE-HASH-CATCH",
        "receipt": {
            "kind": "size_hash_catch",
            "size_a": 40,
            "size_b": 40,
            "sha256_a": A_SHA,
            "sha256_b": B_SHA,
            "gate": {"checked": ["size", "sha256"], "verdict": "SUBSTITUTION"},
        },
        "expect": "EQUAL_LEN_CAUGHT",
    },
    {
        "case_id": "EL-FIXTURE-BROKEN",
        "receipt": {
            "kind": "fixture_broken_same_hash",
            "size_a": 40,
            "size_b": 40,
            "sha256_a": A_SHA,
            "sha256_b": A_SHA,
        },
        "expect": "FIXTURE_BROKEN",
    },
    {
        "case_id": "EL-BASELINE-UNFROZEN",
        "receipt": {
            "kind": "hash_baseline_unfrozen",
            "hash_baseline": {"reader_impl": None, "read_path": "/tmp/x", "epoch": None},
            "gate_verdict": "PASS",
        },
        "expect": "HASH_BASELINE_UNFROZEN",
    },
    {
        "case_id": "EL-BASELINE-FROZEN-OK",
        "receipt": {
            "kind": "hash_baseline_frozen_ok",
            "size_a": 40,
            "size_b": 40,
            "sha256_a": A_SHA,
            "sha256_b": B_SHA,
            "hash_baseline": {
                "reader_impl": "sha256-stdio/v1",
                "read_path": "fixtures/equal_len_substitution/A.bin",
                "epoch": "2026-10-24T17:33:00+08:00",
            },
            "gate": {"checked": ["size", "sha256"], "verdict": "EQUAL_LEN_CAUGHT"},
        },
        "expect": "HASH_BASELINE_FROZEN",
    },
    {
        "case_id": "EL-CANON-PIN",
        "receipt": {
            "kind": "canon_pair_pin",
            "raw_a": "a" * 19 + "\n" + "a" * 19 + "\n",
            "raw_b": "a" * 39 + "\n",
        },
        "expect": "CANON_PINNED",
    },
    {
        "case_id": "EL-NEWLINE-TRADEOFF-SIZE-ONLY",
        "receipt": {
            "kind": "size_only_false_ok",
            "size_a": 40,
            "size_b": 40,
            "sha256_a": A_SHA,
            "sha256_b": B_SHA,
            "gate": {"checked": ["size"], "verdict": "PASS"},
            "note": "A has two LF mid/end; B has one trailing LF — same size, different content",
        },
        "expect": "EQUAL_LEN_SIZE_ONLY",
    },
]


def main() -> int:
    rows = []
    ok = True
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        match = got.get("reason_code") == fx["expect"]
        ok = ok and match
        rows.append(
            {
                "case_id": fx["case_id"],
                "expect": fx["expect"],
                "got": got.get("reason_code"),
                "match": match,
                "judge": got,
            }
        )
    out = {
        "version": "EQUAL_LEN_SUBSTITUTION/v0.1",
        "canon": {
            "fixture_id": "EQUAL_LEN_SUB_001",
            "size": 40,
            "sha256_a": A_SHA,
            "sha256_b": B_SHA,
            "sha16_a": A_SHA16,
            "sha16_b": B_SHA16,
            "credit": "留痕",
        },
        "all_match": ok,
        "n": len(rows),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
