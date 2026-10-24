#!/usr/bin/env python3
"""WINDOW_PAIRING v0.2

Extends v0.1. Structure from 李晨熙 (EigenFlux 2026-10-24 nearmiss_v3 +
follow-up PM on EMPTY_GATES_UNOBSERVED / offset_coordinate_system / layer):

  1. empty_payload_neg — empty / field-absent payload must not silent-pass
     as "three gates clear". Distinct from vector-layer empty-set META.
  2. arm5_arm7_closed_set — stale_three_gate + reuse_three_state share one
     closed reuse_state set {FRESH,REUSE,STALE}; unknown collapses both.
  3. offset_coordinate_system — name+version required on the same receipt
     that covers pre/post/product digests; missing → NOT_COMPARABLE (not
     in diff stats). Version mismatch with semantic equivalence map →
     remapped column; without map → NOT_COMPARABLE.
  4. EMPTY_GATES_UNOBSERVED — three gates never observed (no per-gate
     observation credentials) ≠ three gates observed-and-clear. Missing
     credential → EMPTY_GATES_UNOBSERVED; never default into PASS denom.
  5. per_gate_obs_cred — each gate that claims "clear" must echo a
     probe-generated observation credential produced AFTER taking input;
     gate may not mint a credential when input was never taken.
  6. compare_table_columns — required columns: axis_alignment,
     offset_coordinate_system, declared_normalization_stages, layer,
     neg_ctrl_source. Any missing → NOT_COMPARABLE at table entry.
  7. layer_split — vector-layer (M10 empty-set META) vs arm-layer
     (field-absent empty payload) must not substitute as same cell.

Retains v0.1 arms (write pairing, ordered seq, ACL ∩, unpaired parallel,
stale three-gate, sample_set batches, reuse three-state) via import of
judge paths re-implemented below for a self-contained file.

analyze_only. Stdlib only.
Credit: 李晨熙 (v0.2 structure + nearmiss_v3); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

REUSE_OK = frozenset({"FRESH", "REUSE", "STALE"})
COMPARE_COLS = (
    "axis_alignment",
    "offset_coordinate_system",
    "declared_normalization_stages",
    "layer",
    "neg_ctrl_source",
)
GATE_NAMES = ("ttl", "downstream_confirm", "reuse")
LAYER_OK = frozenset({"vector-layer", "arm-layer"})


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def _as_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _reuse_closed(reuse_state: str | None, reported: Any) -> dict[str, Any] | None:
    """Shared arm5/arm7 closed-set check. Returns a FAIL dict or None if OK."""
    if reuse_state is None:
        if reported == "PASS":
            return {"judge": "FAIL", "reason_code": "REUSE_STATE_MISSING_FALSE_PASS"}
        return {"judge": "FAIL", "reason_code": "REUSE_STATE_MISSING"}
    if reuse_state not in REUSE_OK:
        if reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "REUSE_STATE_UNKNOWN_FALSE_PASS",
                "detail": {"reuse_state": reuse_state},
            }
        return {
            "judge": "FAIL",
            "reason_code": "REUSE_STATE_UNKNOWN",
            "detail": {"reuse_state": reuse_state},
        }
    return None


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")

    # --- v0.2: empty payload negative control (arm-layer) ---
    if kind == "empty_payload_neg":
        # Field-absent empty payload claiming three gates clear.
        gates = receipt.get("gates")
        layer = _norm(receipt.get("layer"))
        if layer is None:
            layer = "arm-layer"
        if layer not in LAYER_OK:
            return {
                "judge": "FAIL",
                "reason_code": "LAYER_UNKNOWN",
                "detail": {"layer": layer},
            }
        # Empty / missing gates object → EMPTY_PAYLOAD; must not PASS
        if gates is None or gates == {} or gates == []:
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "EMPTY_PAYLOAD_FALSE_PASS",
                    "detail": {"layer": layer},
                }
            return {
                "judge": "FAIL",
                "reason_code": "EMPTY_PAYLOAD_NEG",
                "detail": {"layer": layer},
            }
        if not isinstance(gates, dict):
            return {"judge": "FAIL", "reason_code": "GATES_SHAPE_INVALID"}
        # All three gate fields absent → same family
        absent = [g for g in GATE_NAMES if g not in gates]
        if len(absent) == len(GATE_NAMES):
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "EMPTY_PAYLOAD_FALSE_PASS",
                    "detail": {"layer": layer, "absent": absent},
                }
            return {
                "judge": "FAIL",
                "reason_code": "EMPTY_PAYLOAD_NEG",
                "detail": {"layer": layer, "absent": absent},
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_NON_EMPTY_PAYLOAD"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    # --- v0.2: EMPTY_GATES_UNOBSERVED (per-gate observation credentials) ---
    if kind == "empty_gates_unobserved":
        gate_obs = receipt.get("gate_observations") or {}
        claimed_clear = bool(receipt.get("claimed_all_clear", False))
        if not isinstance(gate_obs, dict):
            return {"judge": "FAIL", "reason_code": "GATE_OBS_SHAPE_INVALID"}
        missing_cred = []
        fabricated = []
        for g in GATE_NAMES:
            entry = gate_obs.get(g)
            if entry is None or not isinstance(entry, dict):
                missing_cred.append(g)
                continue
            cred = _norm(entry.get("observation_credential"))
            input_taken = entry.get("input_taken")
            if cred is None:
                missing_cred.append(g)
                continue
            # Credential minted without taking input → fabricated
            if input_taken is False:
                fabricated.append(g)
            elif input_taken is not True:
                # Must be strict bool True to count as observed
                missing_cred.append(g)
        detail = {
            "missing_cred": missing_cred,
            "fabricated": fabricated,
            "claimed_all_clear": claimed_clear,
        }
        if missing_cred:
            # Never observed → EMPTY_GATES_UNOBSERVED; never into PASS denom
            if reported == "PASS" or claimed_clear:
                return {
                    "judge": "FAIL",
                    "reason_code": "EMPTY_GATES_UNOBSERVED",
                    "detail": detail,
                }
            return {
                "judge": "FAIL",
                "reason_code": "EMPTY_GATES_UNOBSERVED",
                "detail": detail,
            }
        if fabricated:
            if reported == "PASS" or claimed_clear:
                return {
                    "judge": "FAIL",
                    "reason_code": "GATE_CRED_FABRICATED",
                    "detail": detail,
                }
            return {
                "judge": "FAIL",
                "reason_code": "GATE_CRED_FABRICATED",
                "detail": detail,
            }
        # All three observed with real credentials
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_GATES_OBSERVED"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    # --- v0.2: offset_coordinate_system ---
    if kind == "offset_coordinate_system":
        ocs = receipt.get("offset_coordinate_system")
        stages = receipt.get("declared_normalization_stages")
        digests = receipt.get("digests") or {}
        same_batch = receipt.get("declaration_same_batch")
        version_map = receipt.get("semantic_equivalence_map")  # optional

        if ocs is None or not isinstance(ocs, dict):
            return {
                "judge": "FAIL",
                "reason_code": "NOT_COMPARABLE",
                "detail": {"why": "offset_coordinate_system_absent"},
            }
        name = _norm(ocs.get("name"))
        version = _norm(ocs.get("version"))
        if name is None or version is None:
            return {
                "judge": "FAIL",
                "reason_code": "NOT_COMPARABLE",
                "detail": {"why": "ocs_name_or_version_absent", "ocs": ocs},
            }
        if stages is None:
            return {
                "judge": "FAIL",
                "reason_code": "NOT_COMPARABLE",
                "detail": {"why": "declared_normalization_stages_absent"},
            }
        # Declaration must cover same batch as pre/post/product digests
        if not isinstance(digests, dict):
            return {"judge": "FAIL", "reason_code": "DIGESTS_SHAPE_INVALID"}
        needed = ("pre", "post", "product")
        missing_d = [k for k in needed if _norm(digests.get(k)) is None]
        if missing_d:
            return {
                "judge": "FAIL",
                "reason_code": "NOT_COMPARABLE",
                "detail": {"why": "digest_batch_incomplete", "missing": missing_d},
            }
        if same_batch is False:
            return {
                "judge": "FAIL",
                "reason_code": "NOT_COMPARABLE",
                "detail": {"why": "declaration_product_different_batch"},
            }
        # Version mismatch handling
        peer_version = _norm(receipt.get("peer_ocs_version"))
        if peer_version is not None and peer_version != version:
            if isinstance(version_map, dict) and (
                f"{version}->{peer_version}" in version_map
                or f"{peer_version}->{version}" in version_map
                or version_map.get("equivalent") is True
            ):
                if reported in ("PASS", "FAIL"):
                    return {
                        "judge": "PASS",
                        "reason_code": "OCS_REMAPPED_COMPARABLE",
                        "detail": {
                            "version": version,
                            "peer_version": peer_version,
                            "remapped_offset": receipt.get("remapped_offset"),
                        },
                    }
                return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}
            return {
                "judge": "FAIL",
                "reason_code": "NOT_COMPARABLE",
                "detail": {
                    "why": "ocs_version_semantic_mismatch",
                    "version": version,
                    "peer_version": peer_version,
                },
            }
        if reported in ("PASS", "FAIL"):
            return {
                "judge": "PASS",
                "reason_code": "HONEST_OCS_BOUND",
                "detail": {"name": name, "version": version},
            }
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    # --- v0.2: compare table required columns ---
    if kind == "compare_table_columns":
        row = receipt.get("compare_row") or {}
        if not isinstance(row, dict):
            return {"judge": "FAIL", "reason_code": "COMPARE_ROW_SHAPE_INVALID"}
        missing = [c for c in COMPARE_COLS if c not in row or _norm(row.get(c)) is None]
        if missing:
            return {
                "judge": "FAIL",
                "reason_code": "NOT_COMPARABLE",
                "detail": {"why": "compare_cols_missing", "missing": missing},
            }
        layer = _norm(row.get("layer"))
        if layer not in LAYER_OK:
            return {
                "judge": "FAIL",
                "reason_code": "LAYER_UNKNOWN",
                "detail": {"layer": layer},
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_COMPARE_ROW"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    # --- v0.2: layer_split (vector vs arm must not substitute) ---
    if kind == "layer_split":
        a = receipt.get("cell_a") or {}
        b = receipt.get("cell_b") or {}
        claimed_same_cover = bool(receipt.get("claimed_same_coverage", False))
        if not isinstance(a, dict) or not isinstance(b, dict):
            return {"judge": "FAIL", "reason_code": "LAYER_CELLS_MISSING"}
        la = _norm(a.get("layer"))
        lb = _norm(b.get("layer"))
        if la is None or lb is None:
            return {"judge": "FAIL", "reason_code": "LAYER_ABSENT"}
        if la != lb and claimed_same_cover:
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "LAYER_FALSE_COVERAGE",
                    "detail": {"cell_a_layer": la, "cell_b_layer": lb},
                }
            return {
                "judge": "FAIL",
                "reason_code": "LAYER_MISMATCH",
                "detail": {"cell_a_layer": la, "cell_b_layer": lb},
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_LAYER_SPLIT"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    # --- v0.2: arm5/arm7 closed-set unification ---
    if kind == "arm5_arm7_closed_set":
        reuse_state = _norm(receipt.get("reuse_state"))
        closed = _reuse_closed(reuse_state, reported)
        if closed is not None:
            return closed
        # Also require stale three-gate fields present when arm says clear
        ttl_exceeded = bool(receipt.get("ttl_exceeded", False))
        current_id = _norm(receipt.get("current_correction_id"))
        last_seen = _norm(receipt.get("last_seen_correction_id"))
        unconfirmed = (
            current_id is not None
            and last_seen is not None
            and current_id != last_seen
        ) or (current_id is not None and last_seen is None)
        stale_reuse = reuse_state == "STALE"
        tripped = ttl_exceeded or unconfirmed or stale_reuse
        if tripped and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "STALE_FALSE_PASS",
                "detail": {
                    "ttl_exceeded": ttl_exceeded,
                    "unconfirmed": unconfirmed,
                    "reuse_state": reuse_state,
                },
            }
        if tripped:
            return {
                "judge": "FAIL",
                "reason_code": "STALE_GATE_TRIP",
                "detail": {"reuse_state": reuse_state},
            }
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_ARM5_ARM7_CLOSED"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    # --- retain v0.1: write_at_key_fetch ---
    if kind == "write_at_key_fetch":
        writes = receipt.get("writes") or []
        reads = receipt.get("reads") or []
        if not isinstance(writes, list) or not isinstance(reads, list):
            return {"judge": "FAIL", "reason_code": "WINDOWS_MISSING"}
        write_pairs = {_norm(w.get("pair_id")) for w in writes if isinstance(w, dict)}
        read_pairs = {_norm(r.get("pair_id")) for r in reads if isinstance(r, dict)}
        write_pairs.discard(None)
        read_pairs.discard(None)
        unpaired_writes = write_pairs - read_pairs
        unpaired_reads = read_pairs - write_pairs
        unpaired = bool(unpaired_writes or unpaired_reads) or (
            (writes or reads) and (not write_pairs or not read_pairs)
        )
        bare_writes = any(
            isinstance(w, dict) and _norm(w.get("pair_id")) is None for w in writes
        )
        bare_reads = any(
            isinstance(r, dict) and _norm(r.get("pair_id")) is None for r in reads
        )
        unpaired = unpaired or bare_writes or bare_reads
        if unpaired and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "WINDOW_UNPAIRED_FALSE_PASS",
                "detail": {
                    "unpaired_writes": sorted(unpaired_writes),
                    "unpaired_reads": sorted(unpaired_reads),
                },
            }
        if unpaired:
            return {"judge": "FAIL", "reason_code": "WINDOW_UNPAIRED"}
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_PAIRING"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "ordered_sequence":
        events = receipt.get("events") or []
        if not isinstance(events, list) or not events:
            return {"judge": "FAIL", "reason_code": "EVENTS_MISSING"}
        seqs: list[int] = []
        for e in events:
            if not isinstance(e, dict):
                continue
            s = _as_int(e.get("seq"))
            if s is None:
                return {"judge": "FAIL", "reason_code": "SEQ_ABSENT"}
            seqs.append(s)
        broken = any(seqs[i] <= seqs[i - 1] for i in range(1, len(seqs)))
        if broken and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "SEQ_OUT_OF_ORDER_FALSE_PASS",
                "detail": {"seqs": seqs},
            }
        if broken:
            return {"judge": "FAIL", "reason_code": "SEQ_OUT_OF_ORDER", "detail": {"seqs": seqs}}
        if reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "HONEST_ORDERED_SEQ"}
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    if kind == "reuse_three_state":
        reuse_state = _norm(receipt.get("reuse_state"))
        closed = _reuse_closed(reuse_state, reported)
        if closed is not None:
            return closed
        if reported in ("PASS", "FAIL"):
            return {
                "judge": "PASS",
                "reason_code": "HONEST_REUSE_STATE",
                "detail": {"reuse_state": reuse_state},
            }
        return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND"}


CASES: list[dict[str, Any]] = [
    # --- v0.2 empty_payload_neg ---
    {
        "case_id": "wp2-empty-payload-false-pass",
        "kind": "empty_payload_neg",
        "reported_verdict": "PASS",
        "gates": {},
        "layer": "arm-layer",
        "expect_judge": "FAIL",
        "expect_reason": "EMPTY_PAYLOAD_FALSE_PASS",
    },
    {
        "case_id": "wp2-empty-payload-all-fields-absent",
        "kind": "empty_payload_neg",
        "reported_verdict": "FAIL",
        "gates": {},
        "layer": "arm-layer",
        "expect_judge": "FAIL",
        "expect_reason": "EMPTY_PAYLOAD_NEG",
    },
    {
        "case_id": "wp2-empty-payload-honest-present",
        "kind": "empty_payload_neg",
        "reported_verdict": "PASS",
        "gates": {"ttl": True, "downstream_confirm": True, "reuse": "FRESH"},
        "layer": "arm-layer",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_NON_EMPTY_PAYLOAD",
    },
    # --- v0.2 EMPTY_GATES_UNOBSERVED ---
    {
        "case_id": "wp2-gates-unobserved-claimed-clear",
        "kind": "empty_gates_unobserved",
        "reported_verdict": "PASS",
        "claimed_all_clear": True,
        "gate_observations": {
            "ttl": {"input_taken": True, "observation_credential": "probe-ttl-1"},
            "downstream_confirm": {"input_taken": True},  # missing cred
            "reuse": {"input_taken": True, "observation_credential": "probe-reuse-1"},
        },
        "expect_judge": "FAIL",
        "expect_reason": "EMPTY_GATES_UNOBSERVED",
    },
    {
        "case_id": "wp2-gates-cred-fabricated",
        "kind": "empty_gates_unobserved",
        "reported_verdict": "PASS",
        "claimed_all_clear": True,
        "gate_observations": {
            "ttl": {"input_taken": False, "observation_credential": "fake-ttl"},
            "downstream_confirm": {
                "input_taken": True,
                "observation_credential": "probe-dc-1",
            },
            "reuse": {"input_taken": True, "observation_credential": "probe-reuse-1"},
        },
        "expect_judge": "FAIL",
        "expect_reason": "GATE_CRED_FABRICATED",
    },
    {
        "case_id": "wp2-gates-honest-observed",
        "kind": "empty_gates_unobserved",
        "reported_verdict": "PASS",
        "claimed_all_clear": True,
        "gate_observations": {
            "ttl": {"input_taken": True, "observation_credential": "probe-ttl-1"},
            "downstream_confirm": {
                "input_taken": True,
                "observation_credential": "probe-dc-1",
            },
            "reuse": {"input_taken": True, "observation_credential": "probe-reuse-1"},
        },
        "expect_judge": "PASS",
        "expect_reason": "HONEST_GATES_OBSERVED",
    },
    # --- v0.2 offset_coordinate_system ---
    {
        "case_id": "wp2-ocs-absent-not-comparable",
        "kind": "offset_coordinate_system",
        "reported_verdict": "PASS",
        "declared_normalization_stages": ["raw", "aligned"],
        "digests": {"pre": "a", "post": "b", "product": "c"},
        "declaration_same_batch": True,
        "expect_judge": "FAIL",
        "expect_reason": "NOT_COMPARABLE",
    },
    {
        "case_id": "wp2-ocs-diff-batch-not-comparable",
        "kind": "offset_coordinate_system",
        "reported_verdict": "PASS",
        "offset_coordinate_system": {"name": "pre-post-v1", "version": "1.0"},
        "declared_normalization_stages": ["raw", "aligned"],
        "digests": {"pre": "a", "post": "b", "product": "c"},
        "declaration_same_batch": False,
        "expect_judge": "FAIL",
        "expect_reason": "NOT_COMPARABLE",
    },
    {
        "case_id": "wp2-ocs-version-mismatch-no-map",
        "kind": "offset_coordinate_system",
        "reported_verdict": "PASS",
        "offset_coordinate_system": {"name": "pre-post-v1", "version": "1.0"},
        "peer_ocs_version": "2.0",
        "declared_normalization_stages": ["raw", "aligned"],
        "digests": {"pre": "a", "post": "b", "product": "c"},
        "declaration_same_batch": True,
        "expect_judge": "FAIL",
        "expect_reason": "NOT_COMPARABLE",
    },
    {
        "case_id": "wp2-ocs-version-remap-ok",
        "kind": "offset_coordinate_system",
        "reported_verdict": "PASS",
        "offset_coordinate_system": {"name": "pre-post-v1", "version": "1.0"},
        "peer_ocs_version": "1.1",
        "semantic_equivalence_map": {"1.0->1.1": True, "equivalent": True},
        "remapped_offset": 0.0,
        "declared_normalization_stages": ["raw", "aligned"],
        "digests": {"pre": "a", "post": "b", "product": "c"},
        "declaration_same_batch": True,
        "expect_judge": "PASS",
        "expect_reason": "OCS_REMAPPED_COMPARABLE",
    },
    {
        "case_id": "wp2-ocs-honest-bound",
        "kind": "offset_coordinate_system",
        "reported_verdict": "PASS",
        "offset_coordinate_system": {"name": "pre-post-v1", "version": "1.0"},
        "declared_normalization_stages": ["raw", "aligned", "product"],
        "digests": {"pre": "a", "post": "b", "product": "c"},
        "declaration_same_batch": True,
        "expect_judge": "PASS",
        "expect_reason": "HONEST_OCS_BOUND",
    },
    # --- v0.2 compare_table_columns ---
    {
        "case_id": "wp2-compare-missing-layer",
        "kind": "compare_table_columns",
        "reported_verdict": "PASS",
        "compare_row": {
            "axis_alignment": "x",
            "offset_coordinate_system": "pre-post-v1@1.0",
            "declared_normalization_stages": "raw|aligned",
            "neg_ctrl_source": "peer",
        },
        "expect_judge": "FAIL",
        "expect_reason": "NOT_COMPARABLE",
    },
    {
        "case_id": "wp2-compare-honest-row",
        "kind": "compare_table_columns",
        "reported_verdict": "PASS",
        "compare_row": {
            "axis_alignment": "x",
            "offset_coordinate_system": "pre-post-v1@1.0",
            "declared_normalization_stages": "raw|aligned|product",
            "layer": "arm-layer",
            "neg_ctrl_source": "peer:李晨熙",
        },
        "expect_judge": "PASS",
        "expect_reason": "HONEST_COMPARE_ROW",
    },
    # --- v0.2 layer_split ---
    {
        "case_id": "wp2-layer-false-coverage",
        "kind": "layer_split",
        "reported_verdict": "PASS",
        "claimed_same_coverage": True,
        "cell_a": {"layer": "vector-layer", "code": "M10_EMPTY_SET"},
        "cell_b": {"layer": "arm-layer", "code": "EMPTY_PAYLOAD_NEG"},
        "expect_judge": "FAIL",
        "expect_reason": "LAYER_FALSE_COVERAGE",
    },
    {
        "case_id": "wp2-layer-honest-split",
        "kind": "layer_split",
        "reported_verdict": "PASS",
        "claimed_same_coverage": False,
        "cell_a": {"layer": "vector-layer", "code": "M10_EMPTY_SET"},
        "cell_b": {"layer": "arm-layer", "code": "EMPTY_PAYLOAD_NEG"},
        "expect_judge": "PASS",
        "expect_reason": "HONEST_LAYER_SPLIT",
    },
    # --- v0.2 arm5/arm7 closed-set ---
    {
        "case_id": "wp2-arm57-unknown-reuse-false-pass",
        "kind": "arm5_arm7_closed_set",
        "reported_verdict": "PASS",
        "ttl_exceeded": False,
        "current_correction_id": "c-9",
        "last_seen_correction_id": "c-9",
        "reuse_state": "CACHED",
        "expect_judge": "FAIL",
        "expect_reason": "REUSE_STATE_UNKNOWN_FALSE_PASS",
    },
    {
        "case_id": "wp2-arm57-stale-false-pass",
        "kind": "arm5_arm7_closed_set",
        "reported_verdict": "PASS",
        "ttl_exceeded": False,
        "current_correction_id": "c-9",
        "last_seen_correction_id": "c-7",
        "reuse_state": "FRESH",
        "expect_judge": "FAIL",
        "expect_reason": "STALE_FALSE_PASS",
    },
    {
        "case_id": "wp2-arm57-honest-closed",
        "kind": "arm5_arm7_closed_set",
        "reported_verdict": "PASS",
        "ttl_exceeded": False,
        "current_correction_id": "c-9",
        "last_seen_correction_id": "c-9",
        "reuse_state": "FRESH",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_ARM5_ARM7_CLOSED",
    },
    # --- retain smoke from v0.1 ---
    {
        "case_id": "wp2-pair-unpaired-false-pass",
        "kind": "write_at_key_fetch",
        "reported_verdict": "PASS",
        "writes": [{"pair_id": "p1", "key": "kA"}],
        "reads": [{"pair_id": "p2", "key": "kA"}],
        "expect_judge": "FAIL",
        "expect_reason": "WINDOW_UNPAIRED_FALSE_PASS",
    },
    {
        "case_id": "wp2-reuse-honest-fresh",
        "kind": "reuse_three_state",
        "reported_verdict": "PASS",
        "reuse_state": "FRESH",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_REUSE_STATE",
    },
]


def run_all() -> dict[str, Any]:
    results = []
    passed = 0
    for case in CASES:
        got = judge(case)
        ok = (
            got.get("judge") == case["expect_judge"]
            and got.get("reason_code") == case["expect_reason"]
        )
        if ok:
            passed += 1
        results.append(
            {
                "case_id": case["case_id"],
                "ok": ok,
                "expect_judge": case["expect_judge"],
                "expect_reason": case["expect_reason"],
                "got": got,
            }
        )
    payload = {
        "fixture": "WINDOW_PAIRING",
        "version": "v0.2",
        "total": len(CASES),
        "passed": passed,
        "failed": len(CASES) - passed,
        "results": results,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["run_out_sha256"] = hashlib.sha256(blob).hexdigest()
    return payload


def main() -> int:
    out = run_all()
    # also stamp script sha
    with open(__file__, "rb") as f:
        out["script_sha256"] = hashlib.sha256(f.read()).hexdigest()
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if out["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
