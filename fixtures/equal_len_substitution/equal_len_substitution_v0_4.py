#!/usr/bin/env python3
"""EQUAL_LEN_SUBSTITUTION v0.4

Retains v0.1 canon pair EQUAL_LEN_SUB_001 (留痕 measured A/B size=40, distinct sha256).

Retains all v0.2 + v0.3 arms.

New in v0.4 (peer review EigenFlux 2026-10-24):
  ⑲ SHARED_READ_PATH — dual-compute both arms declare same read_path_id
     → must-fail DUAL_COMPUTE_SHARED_READ_PATH (credit WorkBuddy: 前缀取自同一落盘文件).
  ⑳ SAME_IMPL_TWICE — dual-compute same compute_impl_id invoked twice
     → must-fail DUAL_COMPUTE_NOT_INDEPENDENT (credit DSH: shared parsing bug passes both).
  ㉑ SAME_WRITER_ID — both arms same writer_id → must-fail DUAL_COMPUTE_SAME_WRITER
     (credit 屎山工程师/龟龟: bytes_origin/writer_id independence).
  ㉒ SAME_PREFIX_FALSE_DUAL — size_eq ∧ prefix_eq claimed as dual-evidence PASS
     → must-fail SAME_PREFIX_FALSE_DUAL (credit WorkBuddy: 长度相等且前缀相同必须失败).
  ㉓ INDEPENDENT_DUAL_OK — distinct read_path_id + compute_impl_id + writer_id,
     size_eq ∧ hash_neq → PASS INDEPENDENT_DUAL_OK.

New in v0.3 (peer review EigenFlux 2026-10-24):
  ⑫ AMBIGUOUS_COLLISION — short prefix inevitable collision → must conclude
     AMBIGUOUS, never PASS (credit 小清新).
  ⑬ SHORT_PREFIX_FALSE_PASS — short prefix collision claimed PASS → must-fail.
  ⑭ NAME_MISMATCH — equal-len, different names (hash-collision shape) →
     EQUAL_LEN_NAME_MISMATCH (credit 工具人; separate from DUP).
  ⑮ NAME_DUP — equal-len, same name registered twice → EQUAL_LEN_NAME_DUP.
  ⑯ DUAL_COMPUTE_VERSION_MISSING — dual-compute reports green without
     dual_compute_version in fixture header → must-fail (credit Ultron).
  ⑰ HASH_EXPECT_POSTWRITE — hash_neq expectation computed after write
     (not from readonly preimage) → must-fail (credit 团子).
  ⑱ CANON_REQUIRED — dual-compute green without canonicalize_id /
     hash_algo declaration → must-fail (credit 星玄).

New in v0.2 (credit 留痕, EigenFlux 2026-10-24):
  ⑥ DUAL_COMPUTE_OK — same input recomputes size AND hash; assert
     size_equal ∧ hash_unequal as two independent conditions. An arm that
     only checks "validator reported green" goes silent when the fixture
     itself is broken; dual-compute gives FIXTURE_BROKEN a second criterion.
  ⑦ DUAL_COMPUTE_FIXTURE_BROKEN — dual-compute finds size_eq but hash_eq
     → FIXTURE_BROKEN (independent of any gate verdict).
  ⑧ VALIDATOR_GREEN_ONLY — gate_verdict=PASS with no dual-compute of
     size/hash → must-fail (silent when fixture is broken).
  ⑨ PREFIX_BITS_OK — prefix comparison parameterized; assert prefix_bits≥64
     before treating prefix equality as evidence.
  ⑩ PREFIX_BITS_TOO_SHORT — prefix_bits<64 used to claim equality / broken
     → must-fail (sha16 collision risk rises with sample size).
  ⑪ SHORT_PREFIX_FALSE_BROKEN — short prefix collides while full sha differs,
     system declared FIXTURE_BROKEN → must-fail FALSE_FIXTURE_BROKEN_SHORT_PREFIX.

Retained from v0.1: SIZE_ONLY_FALSE_OK, SIZE_HASH_CATCH, FIXTURE_BROKEN,
HASH_BASELINE_UNFROZEN/FROZEN, CANON_PIN, NEWLINE_TRADEOFF.

analyze_only. Stdlib only.
Credit: WorkBuddy (SHARED_READ_PATH + SAME_PREFIX_FALSE_DUAL);
        DSH (SAME_IMPL_TWICE / vendored independent impl);
        屎山工程师/龟龟 (SAME_WRITER_ID / bytes_origin);
        小清新 (AMBIGUOUS_COLLISION + size_eq→hash_neq order);
        工具人的小工具 (NAME_MISMATCH vs NAME_DUP two codes);
        Ultron (dual_compute_version);
        团子 (HASH_EXPECT_POSTWRITE / compute_path);
        星玄 (canonicalize before hash);
        留痕 (v0.2 dual-compute + prefix_bits); 墨尘 (v0.1); Grok Bot (impl).
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

# Synthetic short-prefix collision pair for arm ⑪:
# same first 8 hex (32 bits), different full sha — demonstrates false FIXTURE_BROKEN.
SHORT_PREFIX_A = "deadbeef" + ("0" * 56)
SHORT_PREFIX_B = "deadbeef" + ("1" * 56)
assert SHORT_PREFIX_A[:8] == SHORT_PREFIX_B[:8]
assert SHORT_PREFIX_A != SHORT_PREFIX_B

assert len(A_BYTES) == 40 and len(B_BYTES) == 40
assert A_SHA != B_SHA
assert A_SHA16 == "3addf812ec1cf1e1"
assert B_SHA16 == "965e27a2084ef37e"

MIN_PREFIX_BITS = 64


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _dual_compute(raw_a: Any, raw_b: Any) -> dict[str, Any]:
    """Recompute size and hash from raw payloads — independent of any gate."""
    if isinstance(raw_a, str):
        ba = raw_a.encode("utf-8")
    elif isinstance(raw_a, (bytes, bytearray)):
        ba = bytes(raw_a)
    else:
        return {"ok": False, "reason_code": "RAW_MISSING"}
    if isinstance(raw_b, str):
        bb = raw_b.encode("utf-8")
    elif isinstance(raw_b, (bytes, bytearray)):
        bb = bytes(raw_b)
    else:
        return {"ok": False, "reason_code": "RAW_MISSING"}
    sa, sb = _sha(ba), _sha(bb)
    return {
        "ok": True,
        "size_a": len(ba),
        "size_b": len(bb),
        "size_equal": len(ba) == len(bb),
        "sha256_a": sa,
        "sha256_b": sb,
        "hash_unequal": sa != sb,
        "sha16_a": sa[:16],
        "sha16_b": sb[:16],
    }


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "size_only_false_ok":
        size_a = receipt.get("size_a")
        size_b = receipt.get("size_b")
        sha_a = receipt.get("sha256_a")
        sha_b = receipt.get("sha256_b")
        gate = receipt.get("gate")
        if size_a != size_b:
            return {"judge": "FAIL", "reason_code": "NOT_EQUAL_LEN"}
        if not isinstance(gate, dict):
            return {"judge": "FAIL", "reason_code": "GATE_MISSING"}
        checked = gate.get("checked") or []
        verdict = gate.get("verdict")
        if "size" in checked and "sha256" not in checked and verdict == "PASS":
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
        if "size" in checked and "sha256" in checked and verdict in (
            "FAIL",
            "SUBSTITUTION",
            "EQUAL_LEN_CAUGHT",
        ):
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
        baseline = receipt.get("hash_baseline") or {}
        if baseline.get("reader_impl") and baseline.get("read_path") and baseline.get("epoch"):
            return {"judge": "FAIL", "reason_code": "BASELINE_SHOULD_BE_UNFROZEN"}
        if receipt.get("gate_verdict") == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "HASH_BASELINE_UNFROZEN",
                "detail": {
                    "missing": [k for k in ("reader_impl", "read_path", "epoch") if not baseline.get(k)]
                },
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

    # --- v0.2 new arms ---

    if kind == "dual_compute_ok":
        # ⑥ Healthy dual-compute: independently recompute; both conditions must hold.
        dc = _dual_compute(receipt.get("raw_a"), receipt.get("raw_b"))
        if not dc.get("ok"):
            return {"judge": "FAIL", "reason_code": dc.get("reason_code", "RAW_MISSING")}
        if not dc["size_equal"]:
            return {"judge": "FAIL", "reason_code": "NOT_EQUAL_LEN", "detail": dc}
        if not dc["hash_unequal"]:
            return {"judge": "FAIL", "reason_code": "FIXTURE_BROKEN", "detail": dc}
        # Both independent conditions true — dual-compute arm healthy.
        return {
            "judge": "PASS",
            "reason_code": "DUAL_COMPUTE_OK",
            "detail": {
                "size": dc["size_a"],
                "sha16_a": dc["sha16_a"],
                "sha16_b": dc["sha16_b"],
                "asserted": ["size_equal", "hash_unequal"],
            },
        }

    if kind == "dual_compute_fixture_broken":
        # ⑦ Dual-compute finds size_eq ∧ hash_eq → FIXTURE_BROKEN (no gate needed).
        dc = _dual_compute(receipt.get("raw_a"), receipt.get("raw_b"))
        if not dc.get("ok"):
            return {"judge": "FAIL", "reason_code": dc.get("reason_code", "RAW_MISSING")}
        if dc["size_equal"] and not dc["hash_unequal"]:
            return {
                "judge": "FAIL",
                "reason_code": "FIXTURE_BROKEN",
                "detail": {
                    "note": "dual-compute: size_eq but hash_eq — fixture never produced a substitution",
                    "size": dc["size_a"],
                    "sha16": dc["sha16_a"],
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_FIXTURE_BROKEN_VIA_DUAL"}

    if kind == "validator_green_only":
        # ⑧ Only "validator reported green" — silent when fixture itself is broken.
        gate_verdict = receipt.get("gate_verdict")
        has_dual = receipt.get("dual_compute") is not None
        raw_a, raw_b = receipt.get("raw_a"), receipt.get("raw_b")
        if gate_verdict == "PASS" and not has_dual and raw_a is None and raw_b is None:
            return {
                "judge": "FAIL",
                "reason_code": "VALIDATOR_GREEN_ONLY",
                "detail": {
                    "note": "no dual-compute of size/hash — FIXTURE_BROKEN would be silent",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_VALIDATOR_GREEN_ONLY"}

    if kind == "prefix_bits_ok":
        # ⑨ Parameterized prefix; require ≥64 bits before trusting prefix equality.
        prefix_bits = receipt.get("prefix_bits")
        sha_a = str(receipt.get("sha256_a") or "")
        sha_b = str(receipt.get("sha256_b") or "")
        if not isinstance(prefix_bits, int):
            return {"judge": "FAIL", "reason_code": "PREFIX_BITS_MISSING"}
        if prefix_bits < MIN_PREFIX_BITS:
            return {
                "judge": "FAIL",
                "reason_code": "PREFIX_BITS_TOO_SHORT",
                "detail": {"prefix_bits": prefix_bits, "min": MIN_PREFIX_BITS},
            }
        n_hex = prefix_bits // 4
        if len(sha_a) < n_hex or len(sha_b) < n_hex:
            return {"judge": "FAIL", "reason_code": "SHA_TOO_SHORT_FOR_PREFIX"}
        if sha_a[:n_hex] == sha_b[:n_hex]:
            return {"judge": "FAIL", "reason_code": "FIXTURE_BROKEN"}
        size_a, size_b = receipt.get("size_a"), receipt.get("size_b")
        if size_a != size_b:
            return {"judge": "FAIL", "reason_code": "NOT_EQUAL_LEN"}
        return {
            "judge": "PASS",
            "reason_code": "PREFIX_BITS_OK",
            "detail": {"prefix_bits": prefix_bits, "n_hex": n_hex},
        }

    if kind == "prefix_bits_too_short":
        # ⑩ Using prefix_bits<64 to claim equality / broken → must-fail.
        prefix_bits = receipt.get("prefix_bits")
        if not isinstance(prefix_bits, int):
            return {"judge": "FAIL", "reason_code": "PREFIX_BITS_MISSING"}
        claimed = receipt.get("claimed_verdict")  # e.g. FIXTURE_BROKEN from short prefix match
        if prefix_bits < MIN_PREFIX_BITS and claimed in ("FIXTURE_BROKEN", "EQUAL", "PASS"):
            return {
                "judge": "FAIL",
                "reason_code": "PREFIX_BITS_TOO_SHORT",
                "detail": {
                    "prefix_bits": prefix_bits,
                    "min": MIN_PREFIX_BITS,
                    "claimed_verdict": claimed,
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_PREFIX_BITS_TOO_SHORT"}

    if kind == "short_prefix_false_broken":
        # ⑪ Short prefix collides, full sha differs, system said FIXTURE_BROKEN → false.
        prefix_bits = receipt.get("prefix_bits", 32)
        sha_a = str(receipt.get("sha256_a") or "")
        sha_b = str(receipt.get("sha256_b") or "")
        claimed = receipt.get("claimed_verdict")
        n_hex = int(prefix_bits) // 4
        if n_hex <= 0 or len(sha_a) < n_hex or len(sha_b) < n_hex:
            return {"judge": "FAIL", "reason_code": "SHA_TOO_SHORT_FOR_PREFIX"}
        prefix_eq = sha_a[:n_hex] == sha_b[:n_hex]
        full_eq = sha_a == sha_b
        if (
            prefix_bits < MIN_PREFIX_BITS
            and prefix_eq
            and not full_eq
            and claimed == "FIXTURE_BROKEN"
        ):
            return {
                "judge": "FAIL",
                "reason_code": "FALSE_FIXTURE_BROKEN_SHORT_PREFIX",
                "detail": {
                    "prefix_bits": prefix_bits,
                    "prefix_eq": True,
                    "full_eq": False,
                    "note": "short-prefix collision misread as fixture broken",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_FALSE_BROKEN_SHORT_PREFIX"}


    # --- v0.3 new arms ---

    if kind == "ambiguous_collision":
        # ⑫ Short prefix inevitable collision → must be AMBIGUOUS, not PASS/FIXTURE_BROKEN.
        prefix_bits = receipt.get("prefix_bits", 0)
        claimed = receipt.get("claimed_verdict")
        sha_a = str(receipt.get("sha256_a") or "")
        sha_b = str(receipt.get("sha256_b") or "")
        n_hex = int(prefix_bits) // 4 if isinstance(prefix_bits, int) else 0
        prefix_eq = n_hex > 0 and len(sha_a) >= n_hex and len(sha_b) >= n_hex and sha_a[:n_hex] == sha_b[:n_hex]
        full_eq = sha_a == sha_b and sha_a != ""
        if (
            isinstance(prefix_bits, int)
            and prefix_bits < MIN_PREFIX_BITS
            and prefix_eq
            and not full_eq
            and claimed == "AMBIGUOUS"
        ):
            return {
                "judge": "PASS",
                "reason_code": "AMBIGUOUS_COLLISION",
                "detail": {"prefix_bits": prefix_bits, "note": "short-prefix collision correctly left undecided"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_AMBIGUOUS_COLLISION"}

    if kind == "short_prefix_false_pass":
        # ⑬ Short prefix collision claimed PASS → must-fail (not covered by false-broken alone).
        prefix_bits = receipt.get("prefix_bits", 0)
        claimed = receipt.get("claimed_verdict")
        sha_a = str(receipt.get("sha256_a") or "")
        sha_b = str(receipt.get("sha256_b") or "")
        n_hex = int(prefix_bits) // 4 if isinstance(prefix_bits, int) else 0
        prefix_eq = n_hex > 0 and len(sha_a) >= n_hex and len(sha_b) >= n_hex and sha_a[:n_hex] == sha_b[:n_hex]
        full_eq = sha_a == sha_b and sha_a != ""
        if (
            isinstance(prefix_bits, int)
            and prefix_bits < MIN_PREFIX_BITS
            and prefix_eq
            and not full_eq
            and claimed == "PASS"
        ):
            return {
                "judge": "FAIL",
                "reason_code": "SHORT_PREFIX_FALSE_PASS",
                "detail": {"prefix_bits": prefix_bits, "note": "short-prefix collision misread as PASS"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_SHORT_PREFIX_FALSE_PASS"}

    if kind == "name_mismatch":
        # ⑭ Equal-len, different names (hash-collision shape) — separate code from DUP.
        size_a, size_b = receipt.get("size_a"), receipt.get("size_b")
        name_a, name_b = receipt.get("name_a"), receipt.get("name_b")
        sha_a, sha_b = receipt.get("sha256_a"), receipt.get("sha256_b")
        if size_a != size_b:
            return {"judge": "FAIL", "reason_code": "NOT_EQUAL_LEN"}
        if not name_a or not name_b or name_a == name_b:
            return {"judge": "FAIL", "reason_code": "EXPECTED_DISTINCT_NAMES"}
        if sha_a == sha_b:
            return {"judge": "FAIL", "reason_code": "FIXTURE_BROKEN"}
        gate = receipt.get("gate") or {}
        if gate.get("verdict") == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "EQUAL_LEN_NAME_MISMATCH",
                "detail": {"name_a": name_a, "name_b": name_b, "size": size_a},
            }
        if gate.get("verdict") in ("FAIL", "SUBSTITUTION", "EQUAL_LEN_NAME_MISMATCH"):
            return {"judge": "PASS", "reason_code": "EQUAL_LEN_NAME_MISMATCH_CAUGHT"}
        return {"judge": "FAIL", "reason_code": "EQUAL_LEN_NAME_MISMATCH"}

    if kind == "name_dup":
        # ⑮ Equal-len, same name registered twice — registration shape, not collision.
        size_a, size_b = receipt.get("size_a"), receipt.get("size_b")
        name_a, name_b = receipt.get("name_a"), receipt.get("name_b")
        if size_a != size_b:
            return {"judge": "FAIL", "reason_code": "NOT_EQUAL_LEN"}
        if not name_a or name_a != name_b:
            return {"judge": "FAIL", "reason_code": "EXPECTED_SAME_NAME_DUP"}
        gate = receipt.get("gate") or {}
        if gate.get("verdict") == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "EQUAL_LEN_NAME_DUP",
                "detail": {"name": name_a, "size": size_a, "note": "same-name duplicate registration"},
            }
        if gate.get("verdict") in ("FAIL", "DUP", "EQUAL_LEN_NAME_DUP"):
            return {"judge": "PASS", "reason_code": "EQUAL_LEN_NAME_DUP_CAUGHT"}
        return {"judge": "FAIL", "reason_code": "EQUAL_LEN_NAME_DUP"}

    if kind == "dual_compute_version_missing":
        # ⑯ Dual-compute green without dual_compute_version → must-fail.
        header = receipt.get("fixture_header") or {}
        gate_verdict = receipt.get("gate_verdict")
        has_dual = receipt.get("dual_compute") is not None or receipt.get("raw_a") is not None
        if gate_verdict == "PASS" and has_dual and not header.get("dual_compute_version"):
            return {
                "judge": "FAIL",
                "reason_code": "DUAL_COMPUTE_VERSION_MISSING",
                "detail": {"note": "dual-compute arm must declare dual_compute_version in fixture header"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_DUAL_COMPUTE_VERSION_MISSING"}

    if kind == "hash_expect_postwrite":
        # ⑰ Expectation hashed after write (not from readonly preimage) → must-fail.
        expect_source = receipt.get("expect_source")  # "postwrite" | "readonly_preimage"
        gate_verdict = receipt.get("gate_verdict")
        if expect_source == "postwrite" and gate_verdict in ("PASS", "SUBSTITUTION", "EQUAL_LEN_CAUGHT"):
            return {
                "judge": "FAIL",
                "reason_code": "HASH_EXPECT_POSTWRITE",
                "detail": {"note": "hash_neq expectation must be precomputed from readonly preimage before write"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_HASH_EXPECT_POSTWRITE"}

    if kind == "canon_required":
        # ⑱ Dual-compute green without canonicalize_id / hash_algo → must-fail.
        header = receipt.get("fixture_header") or {}
        gate_verdict = receipt.get("gate_verdict")
        has_dual = receipt.get("dual_compute") is not None or receipt.get("raw_a") is not None
        missing = [k for k in ("canonicalize_id", "hash_algo") if not header.get(k)]
        if gate_verdict == "PASS" and has_dual and missing:
            return {
                "judge": "FAIL",
                "reason_code": "CANON_REQUIRED",
                "detail": {"missing": missing, "note": "canonicalize before hash; declare canonicalize_id + hash_algo"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_CANON_REQUIRED"}


    if kind == "shared_read_path":
        # ⑲ Both dual-compute arms same read_path_id → must-fail.
        arm_a = receipt.get("arm_a") or {}
        arm_b = receipt.get("arm_b") or {}
        gate_verdict = receipt.get("gate_verdict")
        pa, pb = arm_a.get("read_path_id"), arm_b.get("read_path_id")
        if gate_verdict == "PASS" and pa and pb and pa == pb:
            return {
                "judge": "FAIL",
                "reason_code": "DUAL_COMPUTE_SHARED_READ_PATH",
                "detail": {"read_path_id": pa, "note": "dual arms must not share one on-disk source"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_SHARED_READ_PATH"}

    if kind == "same_impl_twice":
        # ⑳ Same compute_impl_id invoked twice → must-fail.
        arm_a = receipt.get("arm_a") or {}
        arm_b = receipt.get("arm_b") or {}
        gate_verdict = receipt.get("gate_verdict")
        ia, ib = arm_a.get("compute_impl_id"), arm_b.get("compute_impl_id")
        if gate_verdict == "PASS" and ia and ib and ia == ib:
            return {
                "judge": "FAIL",
                "reason_code": "DUAL_COMPUTE_NOT_INDEPENDENT",
                "detail": {"compute_impl_id": ia, "note": "same impl twice is decorative dual-compute"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_SAME_IMPL_TWICE"}

    if kind == "same_writer_id":
        # ㉑ Both arms same writer_id → must-fail.
        arm_a = receipt.get("arm_a") or {}
        arm_b = receipt.get("arm_b") or {}
        gate_verdict = receipt.get("gate_verdict")
        wa, wb = arm_a.get("writer_id"), arm_b.get("writer_id")
        if gate_verdict == "PASS" and wa and wb and wa == wb:
            return {
                "judge": "FAIL",
                "reason_code": "DUAL_COMPUTE_SAME_WRITER",
                "detail": {"writer_id": wa, "note": "bytes_origin/writer_id must differ across dual arms"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_SAME_WRITER_ID"}

    if kind == "same_prefix_false_dual":
        # ㉒ size_eq ∧ prefix_eq claimed as dual-evidence PASS → must-fail.
        size_a, size_b = receipt.get("size_a"), receipt.get("size_b")
        prefix_a, prefix_b = receipt.get("prefix_a"), receipt.get("prefix_b")
        prefix_bits = receipt.get("prefix_bits") or 0
        gate_verdict = receipt.get("gate_verdict")
        if size_a is None or size_b is None or size_a != size_b:
            return {"judge": "FAIL", "reason_code": "NOT_EQUAL_LEN"}
        if not prefix_a or not prefix_b or prefix_a != prefix_b:
            return {"judge": "FAIL", "reason_code": "EXPECTED_SAME_PREFIX"}
        if gate_verdict == "PASS" and int(prefix_bits) >= MIN_PREFIX_BITS:
            return {
                "judge": "FAIL",
                "reason_code": "SAME_PREFIX_FALSE_DUAL",
                "detail": {
                    "size": size_a,
                    "prefix_bits": prefix_bits,
                    "note": "equal-len + equal-prefix cannot count as independent dual evidence",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_SAME_PREFIX_FALSE_DUAL"}

    if kind == "independent_dual_ok":
        # ㉓ Distinct read_path / compute_impl / writer + size_eq ∧ hash_neq → PASS.
        arm_a = receipt.get("arm_a") or {}
        arm_b = receipt.get("arm_b") or {}
        size_a, size_b = receipt.get("size_a"), receipt.get("size_b")
        sha_a, sha_b = receipt.get("sha256_a"), receipt.get("sha256_b")
        if size_a != size_b:
            return {"judge": "FAIL", "reason_code": "NOT_EQUAL_LEN"}
        if not sha_a or not sha_b or sha_a == sha_b:
            return {"judge": "FAIL", "reason_code": "FIXTURE_BROKEN"}
        for key in ("read_path_id", "compute_impl_id", "writer_id"):
            if not arm_a.get(key) or not arm_b.get(key) or arm_a.get(key) == arm_b.get(key):
                return {"judge": "FAIL", "reason_code": "DUAL_COMPUTE_NOT_INDEPENDENT", "detail": {"field": key}}
        return {
            "judge": "PASS",
            "reason_code": "INDEPENDENT_DUAL_OK",
            "detail": {
                "read_path_a": arm_a["read_path_id"],
                "read_path_b": arm_b["read_path_id"],
                "impl_a": arm_a["compute_impl_id"],
                "impl_b": arm_b["compute_impl_id"],
            },
        }

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}


FIXTURES = [
    # --- retained v0.1 ---
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
    # --- v0.2 new ---
    {
        "case_id": "EL-DUAL-COMPUTE-OK",
        "receipt": {
            "kind": "dual_compute_ok",
            "raw_a": "a" * 19 + "\n" + "a" * 19 + "\n",
            "raw_b": "a" * 39 + "\n",
        },
        "expect": "DUAL_COMPUTE_OK",
    },
    {
        "case_id": "EL-DUAL-COMPUTE-FIXTURE-BROKEN",
        "receipt": {
            "kind": "dual_compute_fixture_broken",
            "raw_a": "a" * 39 + "\n",
            "raw_b": "a" * 39 + "\n",  # identical → size_eq ∧ hash_eq
        },
        "expect": "FIXTURE_BROKEN",
    },
    {
        "case_id": "EL-VALIDATOR-GREEN-ONLY",
        "receipt": {
            "kind": "validator_green_only",
            "gate_verdict": "PASS",
            # no raw_a/raw_b, no dual_compute
        },
        "expect": "VALIDATOR_GREEN_ONLY",
    },
    {
        "case_id": "EL-PREFIX-BITS-OK",
        "receipt": {
            "kind": "prefix_bits_ok",
            "prefix_bits": 64,
            "size_a": 40,
            "size_b": 40,
            "sha256_a": A_SHA,
            "sha256_b": B_SHA,
        },
        "expect": "PREFIX_BITS_OK",
    },
    {
        "case_id": "EL-PREFIX-BITS-TOO-SHORT",
        "receipt": {
            "kind": "prefix_bits_too_short",
            "prefix_bits": 32,
            "claimed_verdict": "FIXTURE_BROKEN",
        },
        "expect": "PREFIX_BITS_TOO_SHORT",
    },
    {
        "case_id": "EL-SHORT-PREFIX-FALSE-BROKEN",
        "receipt": {
            "kind": "short_prefix_false_broken",
            "prefix_bits": 32,
            "sha256_a": SHORT_PREFIX_A,
            "sha256_b": SHORT_PREFIX_B,
            "claimed_verdict": "FIXTURE_BROKEN",
        },
        "expect": "FALSE_FIXTURE_BROKEN_SHORT_PREFIX",
    },

    # --- v0.3 new ---
    {
        "case_id": "EL-AMBIGUOUS-COLLISION",
        "receipt": {
            "kind": "ambiguous_collision",
            "prefix_bits": 32,
            "sha256_a": SHORT_PREFIX_A,
            "sha256_b": SHORT_PREFIX_B,
            "claimed_verdict": "AMBIGUOUS",
        },
        "expect": "AMBIGUOUS_COLLISION",
    },
    {
        "case_id": "EL-SHORT-PREFIX-FALSE-PASS",
        "receipt": {
            "kind": "short_prefix_false_pass",
            "prefix_bits": 32,
            "sha256_a": SHORT_PREFIX_A,
            "sha256_b": SHORT_PREFIX_B,
            "claimed_verdict": "PASS",
        },
        "expect": "SHORT_PREFIX_FALSE_PASS",
    },
    {
        "case_id": "EL-NAME-MISMATCH",
        "receipt": {
            "kind": "name_mismatch",
            "size_a": 40,
            "size_b": 40,
            "name_a": "artifact_A",
            "name_b": "artifact_B",
            "sha256_a": A_SHA,
            "sha256_b": B_SHA,
            "gate": {"verdict": "PASS"},
        },
        "expect": "EQUAL_LEN_NAME_MISMATCH",
    },
    {
        "case_id": "EL-NAME-DUP",
        "receipt": {
            "kind": "name_dup",
            "size_a": 40,
            "size_b": 40,
            "name_a": "artifact_X",
            "name_b": "artifact_X",
            "sha256_a": A_SHA,
            "sha256_b": B_SHA,
            "gate": {"verdict": "PASS"},
        },
        "expect": "EQUAL_LEN_NAME_DUP",
    },
    {
        "case_id": "EL-DUAL-COMPUTE-VERSION-MISSING",
        "receipt": {
            "kind": "dual_compute_version_missing",
            "gate_verdict": "PASS",
            "raw_a": "a" * 19 + "\n" + "a" * 19 + "\n",
            "raw_b": "a" * 39 + "\n",
            "fixture_header": {},  # missing dual_compute_version
        },
        "expect": "DUAL_COMPUTE_VERSION_MISSING",
    },
    {
        "case_id": "EL-HASH-EXPECT-POSTWRITE",
        "receipt": {
            "kind": "hash_expect_postwrite",
            "expect_source": "postwrite",
            "gate_verdict": "PASS",
        },
        "expect": "HASH_EXPECT_POSTWRITE",
    },
    {
        "case_id": "EL-CANON-REQUIRED",
        "receipt": {
            "kind": "canon_required",
            "gate_verdict": "PASS",
            "raw_a": "a" * 19 + "\n" + "a" * 19 + "\n",
            "raw_b": "a" * 39 + "\n",
            "fixture_header": {"dual_compute_version": "v0.3"},  # missing canonicalize_id/hash_algo
        },
        "expect": "CANON_REQUIRED",
    },
    # --- v0.4 new ---
    {
        "case_id": "EL-SHARED-READ-PATH",
        "receipt": {
            "kind": "shared_read_path",
            "gate_verdict": "PASS",
            "arm_a": {"read_path_id": "file:///var/data/payload.bin", "compute_impl_id": "sha-local/v1", "writer_id": "w-api"},
            "arm_b": {"read_path_id": "file:///var/data/payload.bin", "compute_impl_id": "sha-remote/v1", "writer_id": "w-disk"},
        },
        "expect": "DUAL_COMPUTE_SHARED_READ_PATH",
    },
    {
        "case_id": "EL-SAME-IMPL-TWICE",
        "receipt": {
            "kind": "same_impl_twice",
            "gate_verdict": "PASS",
            "arm_a": {"read_path_id": "api://resp", "compute_impl_id": "hashlib.sha256/v1", "writer_id": "w-api"},
            "arm_b": {"read_path_id": "file://local", "compute_impl_id": "hashlib.sha256/v1", "writer_id": "w-disk"},
        },
        "expect": "DUAL_COMPUTE_NOT_INDEPENDENT",
    },
    {
        "case_id": "EL-SAME-WRITER-ID",
        "receipt": {
            "kind": "same_writer_id",
            "gate_verdict": "PASS",
            "arm_a": {"read_path_id": "api://resp", "compute_impl_id": "sha-A/v1", "writer_id": "writer-X"},
            "arm_b": {"read_path_id": "file://local", "compute_impl_id": "sha-B/v1", "writer_id": "writer-X"},
        },
        "expect": "DUAL_COMPUTE_SAME_WRITER",
    },
    {
        "case_id": "EL-SAME-PREFIX-FALSE-DUAL",
        "receipt": {
            "kind": "same_prefix_false_dual",
            "size_a": 40,
            "size_b": 40,
            "prefix_bits": 64,
            "prefix_a": A_SHA[:16],
            "prefix_b": A_SHA[:16],
            "gate_verdict": "PASS",
        },
        "expect": "SAME_PREFIX_FALSE_DUAL",
    },
    {
        "case_id": "EL-INDEPENDENT-DUAL-OK",
        "receipt": {
            "kind": "independent_dual_ok",
            "size_a": 40,
            "size_b": 40,
            "sha256_a": A_SHA,
            "sha256_b": B_SHA,
            "arm_a": {"read_path_id": "api://resp", "compute_impl_id": "sha-stdlib/v1", "writer_id": "w-api"},
            "arm_b": {"read_path_id": "file://local", "compute_impl_id": "sha-vendored/v2", "writer_id": "w-disk"},
        },
        "expect": "INDEPENDENT_DUAL_OK",
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
        "version": "EQUAL_LEN_SUBSTITUTION/v0.4",
        "min_prefix_bits": MIN_PREFIX_BITS,
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
