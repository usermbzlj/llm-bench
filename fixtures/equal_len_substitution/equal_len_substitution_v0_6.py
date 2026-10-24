"""EQUAL_LEN_SUBSTITUTION v0.6

Retains v0.1–v0.5 canon and all prior arms.

New in v0.6 (peer review EigenFlux 2026-10-24 ~23:40–00:05 CST):
  ㉜ ISSUER_REACHABILITY_OUT_OF_PROCESS — issuer line must survive after
     SUT write perms revoked; requires four cols: issuer_source
     (fd|inode|append_only), writer_pid_ns, snapshot_digest, monotonic_seq
     (credit 屎山工程师).
  ㉝ ISSUER_COLS_INCOMPLETE — PASS with any of the four cols missing
     → must-fail ISSUER_COLS_INCOMPLETE (credit 屎山工程师).
  ㉞ MONOTONIC_SEQ_GAP_UNKNOWN — monotonic_seq jump under multi-writer
     → UNKNOWN (not FAIL) to avoid chronic false-red (credit 屎山工程师).
  ㉟ CHANNEL_ID_INJECTOR_SELF — channel_id filled by injector/SUT, not
     consumer writeback → must-fail CHANNEL_ID_INJECTOR_SELF (credit WorkBuddy).
  ㊱ LINE_ENDING_CANON_UNDECLARED — only EOL differs; normalize policy not
     in digest input; claimed PASS → must-fail LINE_ENDING_CANON_UNDECLARED
     (credit WorkBuddy third cell beside ENCODING_LOSS/MIXED_CHAR).
  ㊲ INJECTOR_VERSION_NO_DIGEST — injector version string without self-digest
     → must-fail INJECTOR_VERSION_NO_DIGEST (credit WorkBuddy).

analyze_only. Stdlib only.
Credit: 屎山工程师 (ISSUER_REACHABILITY 4-col + MONOTONIC_SEQ_GAP_UNKNOWN);
        WorkBuddy (CHANNEL_ID_INJECTOR_SELF + LINE_ENDING_CANON_UNDECLARED +
        INJECTOR_VERSION_NO_DIGEST); prior v0.1–v0.5 credits retained; Grok Bot (impl).
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


    # --- v0.5 new arms ---

    if kind == "dual_compute_alias_second":
        # ㉔ Second arm is alias of first → must-fail (both-broken looks stronger).
        arm_a = receipt.get("arm_a") or {}
        arm_b = receipt.get("arm_b") or {}
        gate_verdict = receipt.get("gate_verdict")
        fa, fb = arm_a.get("function_id") or arm_a.get("code_path_id"), arm_b.get("function_id") or arm_b.get("code_path_id")
        alias = bool(receipt.get("arm_b_is_alias_of_a")) or (fa and fb and fa == fb)
        if gate_verdict == "PASS" and alias:
            return {
                "judge": "FAIL",
                "reason_code": "DUAL_COMPUTE_ALIAS_SECOND",
                "detail": {
                    "function_id": fa,
                    "note": "aliased second compute shares bugs with first — DUAL_COMPUTE_OK is decorative",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_ALIAS_SECOND"}

    if kind == "prefix_bits_sample_n":
        # ㉕ prefix_bits claim without sample_n + expected_fp_rate → must-fail.
        prefix_bits = receipt.get("prefix_bits")
        sample_n = receipt.get("sample_n")
        expected_fp = receipt.get("expected_fp_rate")
        claimed = receipt.get("claimed_verdict")
        if not isinstance(prefix_bits, int):
            return {"judge": "FAIL", "reason_code": "PREFIX_BITS_MISSING"}
        if claimed in ("PREFIX_BITS_TOO_SHORT", "FIXTURE_BROKEN", "PASS") and (
            sample_n is None or expected_fp is None
        ):
            return {
                "judge": "FAIL",
                "reason_code": "PREFIX_BITS_SAMPLE_N_REQUIRED",
                "detail": {
                    "prefix_bits": prefix_bits,
                    "sample_n": sample_n,
                    "expected_fp_rate": expected_fp,
                    "note": "need (prefix_bits, n, expected_fp_rate) to separate short-param from thin-sample",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_PREFIX_SAMPLE_N"}

    if kind == "normalizer_asymmetry":
        # ㉖ Identical bytes; only one side normalized; claimed hash_neq → must-fail.
        raw_identical = receipt.get("bytes_identical_pre_norm")
        norm_a = receipt.get("normalize_a")
        norm_b = receipt.get("normalize_b")
        claimed_hash_neq = receipt.get("claimed_hash_neq")
        gate_verdict = receipt.get("gate_verdict")
        if (
            raw_identical is True
            and bool(norm_a) != bool(norm_b)
            and claimed_hash_neq is True
            and gate_verdict == "PASS"
        ):
            return {
                "judge": "FAIL",
                "reason_code": "NORMALIZER_ASYMMETRY_FALSE_NEQ",
                "detail": {
                    "normalize_a": norm_a,
                    "normalize_b": norm_b,
                    "note": "hash_neq produced by asymmetric normalizer, not by data",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_NORMALIZER_ASYMMETRY"}

    if kind == "expected_issued_by_sut":
        # ㉗ Expectation issued by SUT → must-fail (disjoint issuer required).
        expect_issuer = receipt.get("expect_issuer")
        expect_party = receipt.get("expect_party")
        gate_verdict = receipt.get("gate_verdict")
        if gate_verdict == "PASS" and (
            expect_issuer == "sut"
            or expect_party == "sut"
            or receipt.get("expect_from_channel") is True
        ):
            return {
                "judge": "FAIL",
                "reason_code": "EXPECTED_ISSUED_BY_SUT",
                "detail": {
                    "expect_issuer": expect_issuer or expect_party,
                    "note": "disjoint issuer required; absent → UNKNOWN not default no-collision",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_SUT_ISSUER_CASE"}

    if kind == "arm_not_run_false_pass":
        # ㉘ Arm skipped/not_run but reported PASS → must-fail.
        ledger = receipt.get("arm_ledger") or {}
        status = ledger.get("status") or receipt.get("arm_status")
        gate_verdict = receipt.get("gate_verdict")
        if gate_verdict == "PASS" and status in ("skipped", "not_run", "absent"):
            return {
                "judge": "FAIL",
                "reason_code": "ARM_NOT_RUN_FALSE_PASS",
                "detail": {"arm_status": status, "note": "skipped arm must not look like PASS"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_ARM_NOT_RUN"}

    if kind == "size_eq_norm_undeclared":
        # ㉙ size_eq after CRLF→LF (or other) without normalize_policy / size_delta.
        size_eq = receipt.get("size_equal")
        norm_applied = receipt.get("normalize_applied")
        policy = receipt.get("normalize_policy")
        size_delta = receipt.get("size_delta_pre_post")
        gate_verdict = receipt.get("gate_verdict")
        if (
            size_eq is True
            and norm_applied is True
            and gate_verdict == "PASS"
            and (not policy or size_delta is None)
        ):
            return {
                "judge": "FAIL",
                "reason_code": "SIZE_EQ_NORM_UNDECLARED",
                "detail": {
                    "normalize_applied": norm_applied,
                    "normalize_policy": policy,
                    "size_delta_pre_post": size_delta,
                    "note": "CRLF→LF changes byte length; declare policy and pre/post delta",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_NORM_UNDECLARED"}

    if kind == "writer_self_issued":
        # ㉚ writer_id issued by SUT capture layer → must-fail.
        writer_issuer = receipt.get("writer_issuer")
        gate_verdict = receipt.get("gate_verdict")
        if gate_verdict == "PASS" and writer_issuer in ("sut", "capture_layer", "self"):
            return {
                "judge": "FAIL",
                "reason_code": "WRITER_SELF_ISSUED",
                "detail": {
                    "writer_issuer": writer_issuer,
                    "note": "writer_id must come from outside SUT (fd/inode/append-only ledger)",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_WRITER_SELF_ISSUED"}

    if kind == "length_change_pos_ctrl":
        # ㉛ Positive control: length *does* change and gate catches it.
        size_a, size_b = receipt.get("size_a"), receipt.get("size_b")
        gate = receipt.get("gate") or {}
        if size_a is None or size_b is None or size_a == size_b:
            return {"judge": "FAIL", "reason_code": "EXPECTED_LENGTH_CHANGE"}
        if "size" in (gate.get("checked") or []) and gate.get("verdict") in (
            "FAIL",
            "LENGTH_CHANGED",
            "NOT_EQUAL_LEN",
        ):
            return {
                "judge": "PASS",
                "reason_code": "LENGTH_CHANGE_POS_CTRL",
                "detail": {"size_a": size_a, "size_b": size_b},
            }
        if gate.get("verdict") == "PASS":
            return {"judge": "FAIL", "reason_code": "LENGTH_CHANGE_MISSED"}
        return {"judge": "FAIL", "reason_code": "MUST_CATCH_LENGTH_CHANGE"}


    if kind == "issuer_reachability_out_of_process":
        # ㉜ Issuer lines must appear even after SUT write perms revoked.
        cols = receipt.get("issuer_cols") or {}
        required = ("issuer_source", "writer_pid_ns", "snapshot_digest", "monotonic_seq")
        missing = [k for k in required if not cols.get(k)]
        sut_write_revoked = receipt.get("sut_write_revoked") is True
        issuer_lines_present = receipt.get("issuer_lines_present") is True
        gate_verdict = receipt.get("gate_verdict")
        src = cols.get("issuer_source")
        if src not in ("fd", "inode", "append_only"):
            return {"judge": "FAIL", "reason_code": "ISSUER_SOURCE_INVALID"}
        if missing:
            return {
                "judge": "FAIL",
                "reason_code": "ISSUER_COLS_INCOMPLETE",
                "detail": {"missing": missing},
            }
        if sut_write_revoked and not issuer_lines_present:
            return {
                "judge": "FAIL",
                "reason_code": "ISSUER_REACHABILITY_OUT_OF_PROCESS",
                "detail": {
                    "note": "issuer vanished after SUT write revoke → issuer was inside product",
                },
            }
        if sut_write_revoked and issuer_lines_present and gate_verdict in (
            "PASS",
            "ISSUER_OK",
            "OUT_OF_PROCESS_OK",
        ):
            return {
                "judge": "PASS",
                "reason_code": "ISSUER_OUT_OF_PROCESS_OK",
                "detail": {"issuer_source": src},
            }
        if gate_verdict == "PASS" and not sut_write_revoked:
            # Claimed PASS without running the revoke probe → must-fail
            return {
                "judge": "FAIL",
                "reason_code": "ISSUER_REACHABILITY_OUT_OF_PROCESS",
                "detail": {"note": "PASS without sut_write_revoked probe"},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_ISSUER_REACHABILITY"}

    if kind == "issuer_cols_incomplete":
        # ㉝ Any of four cols missing under PASS → must-fail.
        cols = receipt.get("issuer_cols") or {}
        required = ("issuer_source", "writer_pid_ns", "snapshot_digest", "monotonic_seq")
        missing = [k for k in required if not cols.get(k)]
        if receipt.get("gate_verdict") == "PASS" and missing:
            return {
                "judge": "FAIL",
                "reason_code": "ISSUER_COLS_INCOMPLETE",
                "detail": {"missing": missing},
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_ISSUER_COLS_INCOMPLETE"}

    if kind == "monotonic_seq_gap":
        # ㉞ Gap under multi-writer → UNKNOWN (never FAIL alone, never PASS).
        gap = receipt.get("monotonic_seq_gap") is True
        multi_writer = receipt.get("multi_writer") is True
        claimed = receipt.get("claimed_verdict")
        if gap and multi_writer:
            if claimed == "FAIL":
                return {
                    "judge": "FAIL",
                    "reason_code": "MONOTONIC_SEQ_GAP_FALSE_FAIL",
                    "detail": {"note": "gap under concurrency must not chronic-false-red"},
                }
            if claimed == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "MONOTONIC_SEQ_GAP_FALSE_PASS",
                }
            if claimed == "UNKNOWN":
                return {
                    "judge": "PASS",
                    "reason_code": "MONOTONIC_SEQ_GAP_UNKNOWN",
                }
        return {"judge": "FAIL", "reason_code": "EXPECTED_MONOTONIC_SEQ_GAP"}

    if kind == "channel_id_injector_self":
        # ㉟ channel_id filled by injector/SUT, not consumer writeback.
        filler = receipt.get("channel_id_filler")
        gate_verdict = receipt.get("gate_verdict")
        if gate_verdict == "PASS" and filler in ("injector", "sut", "self", "write_side"):
            return {
                "judge": "FAIL",
                "reason_code": "CHANNEL_ID_INJECTOR_SELF",
                "detail": {
                    "channel_id_filler": filler,
                    "note": "channel_id must be consumer-side writeback",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_CHANNEL_ID_INJECTOR_SELF"}

    if kind == "line_ending_canon_undeclared":
        # ㊱ Only EOL differs; normalize policy absent from digest input.
        only_eol_differs = receipt.get("only_eol_differs") is True
        norm_in_digest = receipt.get("normalize_policy_in_digest_input") is True
        gate_verdict = receipt.get("gate_verdict")
        if only_eol_differs and not norm_in_digest and gate_verdict == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "LINE_ENDING_CANON_UNDECLARED",
                "detail": {
                    "note": "EOL canon must enter digest input; third cell beside ENCODING_LOSS/MIXED_CHAR",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_LINE_ENDING_CANON"}

    if kind == "injector_version_no_digest":
        # ㊲ Injector version string without self-digest.
        ver = receipt.get("injector_version")
        digest = receipt.get("injector_self_digest")
        gate_verdict = receipt.get("gate_verdict")
        if gate_verdict == "PASS" and ver and not digest:
            return {
                "judge": "FAIL",
                "reason_code": "INJECTOR_VERSION_NO_DIGEST",
                "detail": {
                    "injector_version": ver,
                    "note": "version bump without digest cannot detect silent injector edits",
                },
            }
        return {"judge": "FAIL", "reason_code": "EXPECTED_INJECTOR_VERSION_DIGEST"}

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
    # --- v0.5 new ---
    {
        "case_id": "EL-ALIAS-SECOND",
        "receipt": {
            "kind": "dual_compute_alias_second",
            "gate_verdict": "PASS",
            "arm_b_is_alias_of_a": True,
            "arm_a": {"function_id": "compute_size_hash_v1", "code_path_id": "path/compute.py:42"},
            "arm_b": {"function_id": "compute_size_hash_v1", "code_path_id": "path/compute.py:42"},
        },
        "expect": "DUAL_COMPUTE_ALIAS_SECOND",
    },
    {
        "case_id": "EL-PREFIX-SAMPLE-N",
        "receipt": {
            "kind": "prefix_bits_sample_n",
            "prefix_bits": 32,
            "sample_n": None,
            "expected_fp_rate": None,
            "claimed_verdict": "PREFIX_BITS_TOO_SHORT",
        },
        "expect": "PREFIX_BITS_SAMPLE_N_REQUIRED",
    },
    {
        "case_id": "EL-NORMALIZER-ASYMMETRY",
        "receipt": {
            "kind": "normalizer_asymmetry",
            "bytes_identical_pre_norm": True,
            "normalize_a": "CRLF_TO_LF",
            "normalize_b": None,
            "claimed_hash_neq": True,
            "gate_verdict": "PASS",
        },
        "expect": "NORMALIZER_ASYMMETRY_FALSE_NEQ",
    },
    {
        "case_id": "EL-EXPECTED-BY-SUT",
        "receipt": {
            "kind": "expected_issued_by_sut",
            "expect_issuer": "sut",
            "gate_verdict": "PASS",
        },
        "expect": "EXPECTED_ISSUED_BY_SUT",
    },
    {
        "case_id": "EL-ARM-NOT-RUN",
        "receipt": {
            "kind": "arm_not_run_false_pass",
            "arm_ledger": {"status": "skipped", "arm_id": "dual_compute"},
            "gate_verdict": "PASS",
        },
        "expect": "ARM_NOT_RUN_FALSE_PASS",
    },
    {
        "case_id": "EL-NORM-UNDECLARED",
        "receipt": {
            "kind": "size_eq_norm_undeclared",
            "size_equal": True,
            "normalize_applied": True,
            "normalize_policy": None,
            "size_delta_pre_post": None,
            "gate_verdict": "PASS",
        },
        "expect": "SIZE_EQ_NORM_UNDECLARED",
    },
    {
        "case_id": "EL-WRITER-SELF-ISSUED",
        "receipt": {
            "kind": "writer_self_issued",
            "writer_issuer": "capture_layer",
            "gate_verdict": "PASS",
        },
        "expect": "WRITER_SELF_ISSUED",
    },
    {
        "case_id": "EL-LENGTH-CHANGE-POS",
        "receipt": {
            "kind": "length_change_pos_ctrl",
            "size_a": 40,
            "size_b": 41,
            "gate": {"checked": ["size"], "verdict": "LENGTH_CHANGED"},
        },
        "expect": "LENGTH_CHANGE_POS_CTRL",
    },
    # --- v0.6 new ---
    {
        "case_id": "EL-ISSUER-REACHABILITY-VANISHED",
        "receipt": {
            "kind": "issuer_reachability_out_of_process",
            "sut_write_revoked": True,
            "issuer_lines_present": False,
            "gate_verdict": "PASS",
            "issuer_cols": {
                "issuer_source": "append_only",
                "writer_pid_ns": "pidns:1001",
                "snapshot_digest": "a" * 64,
                "monotonic_seq": 7,
            },
        },
        "expect": "ISSUER_REACHABILITY_OUT_OF_PROCESS",
    },
    {
        "case_id": "EL-ISSUER-OUT-OF-PROCESS-OK",
        "receipt": {
            "kind": "issuer_reachability_out_of_process",
            "sut_write_revoked": True,
            "issuer_lines_present": True,
            "gate_verdict": "OUT_OF_PROCESS_OK",
            "issuer_cols": {
                "issuer_source": "fd",
                "writer_pid_ns": "pidns:1001",
                "snapshot_digest": "b" * 64,
                "monotonic_seq": 8,
            },
        },
        "expect": "ISSUER_OUT_OF_PROCESS_OK",
    },
    {
        "case_id": "EL-ISSUER-COLS-INCOMPLETE",
        "receipt": {
            "kind": "issuer_cols_incomplete",
            "gate_verdict": "PASS",
            "issuer_cols": {
                "issuer_source": "append_only",
                "writer_pid_ns": None,
                "snapshot_digest": "c" * 64,
                "monotonic_seq": 9,
            },
        },
        "expect": "ISSUER_COLS_INCOMPLETE",
    },
    {
        "case_id": "EL-MONOTONIC-SEQ-GAP-UNKNOWN",
        "receipt": {
            "kind": "monotonic_seq_gap",
            "monotonic_seq_gap": True,
            "multi_writer": True,
            "claimed_verdict": "UNKNOWN",
        },
        "expect": "MONOTONIC_SEQ_GAP_UNKNOWN",
    },
    {
        "case_id": "EL-MONOTONIC-SEQ-GAP-FALSE-FAIL",
        "receipt": {
            "kind": "monotonic_seq_gap",
            "monotonic_seq_gap": True,
            "multi_writer": True,
            "claimed_verdict": "FAIL",
        },
        "expect": "MONOTONIC_SEQ_GAP_FALSE_FAIL",
    },
    {
        "case_id": "EL-CHANNEL-ID-INJECTOR-SELF",
        "receipt": {
            "kind": "channel_id_injector_self",
            "channel_id_filler": "injector",
            "gate_verdict": "PASS",
        },
        "expect": "CHANNEL_ID_INJECTOR_SELF",
    },
    {
        "case_id": "EL-LINE-ENDING-CANON-UNDECLARED",
        "receipt": {
            "kind": "line_ending_canon_undeclared",
            "only_eol_differs": True,
            "normalize_policy_in_digest_input": False,
            "gate_verdict": "PASS",
        },
        "expect": "LINE_ENDING_CANON_UNDECLARED",
    },
    {
        "case_id": "EL-INJECTOR-VERSION-NO-DIGEST",
        "receipt": {
            "kind": "injector_version_no_digest",
            "injector_version": "inj-v3.2",
            "injector_self_digest": None,
            "gate_verdict": "PASS",
        },
        "expect": "INJECTOR_VERSION_NO_DIGEST",
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
        "version": "EQUAL_LEN_SUBSTITUTION/v0.6",
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
