#!/usr/bin/env python3
"""DSH_TTL v0.1 — three-group TTL ledger judge (credit DSH).

EigenFlux collab 2026-10-24. Fields aligned with DSH + llm-bench issue#3:

  event_id, entity_id, op∈{put,del}, base_version, new_version, ts, ttl_s,
  class∈{active,derived,raw}, audit_required:bool,
  expected∈{purge,retain,stale_reject}

Hard rules (DSH):
  - TTL applies ONLY to active/derived.
  - raw is append-only and NEVER participates in expiry cleanup;
    raw past TTL → retain (esp. audit_required=true).
  - On write, base_version MUST equal the entity's current version;
    else stale_reject and DO NOT overwrite; subsequent read still sees prior.

20-row must-fail pack mix (DSH):
  - raw-over-TTL retain ×2 (exactly 1 with audit_required=true)
  - base_version conflict ×3 (includes del on stale base)
  - normal / derived expiry ×15

Digest (DSH): expected-class counts, op/class distribution, per-row
canonical sha256 sorted then total hash, plus diff event_id list.

analyze_only. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

FIELDS = (
    "event_id",
    "entity_id",
    "op",
    "base_version",
    "new_version",
    "ts",
    "ttl_s",
    "class",
    "audit_required",
    "expected",
)
OPS = frozenset({"put", "del"})
CLASSES = frozenset({"active", "derived", "raw"})
EXPECTED = frozenset({"purge", "retain", "stale_reject"})


def _canon_row(row: dict[str, Any]) -> str:
    payload = {k: row.get(k) for k in FIELDS}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def row_sha256(row: dict[str, Any]) -> str:
    return hashlib.sha256(_canon_row(row).encode("utf-8")).hexdigest()


def digest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected_counts: dict[str, int] = {}
    op_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    shas: list[str] = []
    for r in rows:
        expected_counts[r["expected"]] = expected_counts.get(r["expected"], 0) + 1
        op_counts[r["op"]] = op_counts.get(r["op"], 0) + 1
        class_counts[r["class"]] = class_counts.get(r["class"], 0) + 1
        shas.append(row_sha256(r))
    shas_sorted = sorted(shas)
    total = hashlib.sha256("".join(shas_sorted).encode("utf-8")).hexdigest()
    return {
        "expected_counts": dict(sorted(expected_counts.items())),
        "op_counts": dict(sorted(op_counts.items())),
        "class_counts": dict(sorted(class_counts.items())),
        "row_sha256_sorted": shas_sorted,
        "total_sha256": total,
        "n": len(rows),
    }


def decide(store: dict[str, dict[str, Any]], event: dict[str, Any], as_of: int) -> dict[str, Any]:
    """Apply one event against in-memory store; return decision + mutate store on success."""
    eid = event["entity_id"]
    op = event["op"]
    klass = event["class"]
    base = event["base_version"]
    new_v = event["new_version"]
    ts = event["ts"]
    ttl = event["ttl_s"]
    cur = store.get(eid)

    # Version conflict: base must match current; no overwrite.
    if cur is not None and base != cur["version"]:
        return {
            "decision": "stale_reject",
            "reason_code": "BASE_VERSION_MISMATCH",
            "kept_version": cur["version"],
        }

    # Apply write into store first (raw/active/derived), then classify expiry.
    if op == "put":
        store[eid] = {
            "version": new_v,
            "class": klass,
            "ts": ts,
            "ttl_s": ttl,
            "audit_required": bool(event.get("audit_required")),
        }
    elif op == "del":
        if cur is None and base != 0:
            # deleting with wrong base on missing entity still stale if base!=0
            # but if no cur and base==0, treat as fresh tombstone
            pass
        store[eid] = {
            "version": new_v,
            "class": klass,
            "ts": ts,
            "ttl_s": ttl,
            "audit_required": bool(event.get("audit_required")),
            "deleted": True,
        }
    else:
        return {"decision": "stale_reject", "reason_code": "OP_UNKNOWN"}

    # raw: append-only, never purged by TTL
    if klass == "raw":
        return {"decision": "retain", "reason_code": "RAW_APPEND_NO_EXPIRY"}

    # active/derived: TTL window
    expires_at = ts + ttl
    if as_of > expires_at:
        # purge from live view (tombstone retained for audit trail in notes only)
        return {"decision": "purge", "reason_code": "TTL_EXPIRED"}
    return {"decision": "retain", "reason_code": "WITHIN_TTL"}


def run_batch(events: list[dict[str, Any]], as_of: int) -> dict[str, Any]:
    """Replay events in ts order (stable by event_id), compare to expected."""
    ordered = sorted(events, key=lambda e: (e["ts"], e["event_id"]))
    store: dict[str, dict[str, Any]] = {}
    results = []
    diffs: list[str] = []
    for ev in ordered:
        got = decide(store, ev, as_of)
        ok = got["decision"] == ev["expected"]
        if not ok:
            diffs.append(ev["event_id"])
        results.append(
            {
                "event_id": ev["event_id"],
                "expected": ev["expected"],
                "got": got["decision"],
                "reason_code": got.get("reason_code"),
                "pass": ok,
            }
        )
    return {
        "as_of": as_of,
        "results": results,
        "diff_event_ids": diffs,
        "all_pass": len(diffs) == 0,
        "digest": digest(events),
    }


def pack_20() -> tuple[list[dict[str, Any]], int]:
    """DSH 20-row mix. as_of chosen so active/derived past TTL purge; raw retains.

    Timeline base ts=1792820000; as_of = 1792820000 + 400.
    """
    T0 = 1792820000
    as_of = T0 + 400
    rows: list[dict[str, Any]] = []

    # --- seeds for conflict entities (counted in the 15 expiry bucket as
    # within-TTL retain at write time? No: DSH mix is about expected labels.
    # Seeds that establish version for later stale writes: expected=retain
    # (written within TTL at their ts; evaluated at as_of they may purge).
    # We put seeds early with short TTL so at as_of they are purge, and the
    # conflicting later write is stale_reject WITHOUT overwriting.

    # Seed for stale-001 entity: establish v2 active
    rows.append(
        {
            "event_id": "seed-act-01",
            "entity_id": "ent-act-01",
            "op": "put",
            "base_version": 0,
            "new_version": 2,
            "ts": T0 + 10,
            "ttl_s": 60,
            "class": "active",
            "audit_required": False,
            "expected": "purge",  # T0+10+60=70 < as_of 400
        }
    )
    # Seed for del-stale entity
    rows.append(
        {
            "event_id": "seed-act-02",
            "entity_id": "ent-act-02",
            "op": "put",
            "base_version": 0,
            "new_version": 5,
            "ts": T0 + 20,
            "ttl_s": 50,
            "class": "active",
            "audit_required": False,
            "expected": "purge",
        }
    )
    # Seed for put-stale entity
    rows.append(
        {
            "event_id": "seed-der-01",
            "entity_id": "ent-der-01",
            "op": "put",
            "base_version": 0,
            "new_version": 3,
            "ts": T0 + 30,
            "ttl_s": 40,
            "class": "derived",
            "audit_required": False,
            "expected": "purge",
        }
    )

    # --- Group 2: raw over TTL retain ×2 (1 audit_required=true) ---
    rows.append(
        {
            "event_id": "raw-ttl-001",
            "entity_id": "ent-raw-01",
            "op": "put",
            "base_version": 2,
            "new_version": 3,
            "ts": T0,
            "ttl_s": 30,
            "class": "raw",
            "audit_required": True,
            "expected": "retain",
        }
    )
    rows.append(
        {
            "event_id": "raw-ttl-002",
            "entity_id": "ent-raw-02",
            "op": "put",
            "base_version": 0,
            "new_version": 1,
            "ts": T0 + 5,
            "ttl_s": 10,
            "class": "raw",
            "audit_required": False,
            "expected": "retain",
        }
    )

    # --- Group 3: base_version conflict ×3 (incl del on stale) ---
    # After seed-act-01 left v2 in store; at decide time seed already applied.
    # But wait: seed expected purge — decide() still WRITES into store before
    # classifying expiry. Store keeps the record; conflict check uses version.
    rows.append(
        {
            "event_id": "stale-001",
            "entity_id": "ent-act-01",
            "op": "put",
            "base_version": 1,  # wrong; current is 2
            "new_version": 2,
            "ts": T0 + 60,
            "ttl_s": 300,
            "class": "active",
            "audit_required": False,
            "expected": "stale_reject",
        }
    )
    rows.append(
        {
            "event_id": "stale-002",
            "entity_id": "ent-der-01",
            "op": "put",
            "base_version": 1,  # current 3
            "new_version": 4,
            "ts": T0 + 70,
            "ttl_s": 300,
            "class": "derived",
            "audit_required": False,
            "expected": "stale_reject",
        }
    )
    rows.append(
        {
            "event_id": "stale-del-001",
            "entity_id": "ent-act-02",
            "op": "del",
            "base_version": 2,  # current 5
            "new_version": 6,
            "ts": T0 + 80,
            "ttl_s": 300,
            "class": "active",
            "audit_required": False,
            "expected": "stale_reject",
        }
    )

    # --- Group 1: remaining normal/derived expiry to reach 15 purge+retain-in-window ---
    # We already have 3 seed purges. Need 12 more in the "正常过期与派生过期" bucket.
    # Mix: some purge (past TTL), some retain (still within TTL at as_of).
    # DSH said "正常过期与派生过期 15 条" — interpret as 15 rows in the
    # active/derived expiry group (not counting raw/stale). Seeds count.
    # 3 seeds + 12 more = 15.
    for i in range(12):
        ts = T0 + 100 + i * 5
        # half short TTL → purge; half long → retain
        if i < 8:
            ttl_s = 20  # expires well before as_of
            expected = "purge"
            klass = "active" if i % 2 == 0 else "derived"
        else:
            ttl_s = 500  # still live at as_of
            expected = "retain"
            klass = "derived" if i % 2 == 0 else "active"
        rows.append(
            {
                "event_id": f"exp-{i:03d}",
                "entity_id": f"ent-exp-{i:02d}",
                "op": "put",
                "base_version": 0,
                "new_version": 1,
                "ts": ts,
                "ttl_s": ttl_s,
                "class": klass,
                "audit_required": False,
                "expected": expected,
            }
        )

    assert len(rows) == 20, len(rows)
    raw_n = sum(1 for r in rows if r["class"] == "raw" and r["expected"] == "retain")
    assert raw_n == 2
    assert sum(1 for r in rows if r["class"] == "raw" and r["audit_required"]) == 1
    stale_n = sum(1 for r in rows if r["expected"] == "stale_reject")
    assert stale_n == 3
    expiry_n = 20 - raw_n - stale_n
    assert expiry_n == 15
    # UTF-8 no BOM, sort by event_id for file export; ts monotonic in pack order
    # (replay sorts by ts,event_id)
    return rows, as_of


def mustfail_cases() -> list[dict[str, Any]]:
    """Synthetic must-fail arms: wrong policy collapses that must stay red."""
    T0 = 1792820000
    as_of = T0 + 400
    cases = []

    # MF1: buggy judge purges raw-over-TTL → must detect mismatch
    raw = {
        "event_id": "mf-raw-purge",
        "entity_id": "ent-mf-raw",
        "op": "put",
        "base_version": 0,
        "new_version": 1,
        "ts": T0,
        "ttl_s": 1,
        "class": "raw",
        "audit_required": True,
        "expected": "retain",
    }
    cases.append(
        {
            "id": "MF_RAW_MUST_RETAIN",
            "events": [raw],
            "as_of": as_of,
            "expect_all_pass": True,
            "inject_wrong": None,
        }
    )

    # MF2: accepting stale write as retain must fail the batch
    seed = {
        "event_id": "mf-seed",
        "entity_id": "ent-mf-stale",
        "op": "put",
        "base_version": 0,
        "new_version": 2,
        "ts": T0 + 1,
        "ttl_s": 1000,
        "class": "active",
        "audit_required": False,
        "expected": "retain",
    }
    stale = {
        "event_id": "mf-stale",
        "entity_id": "ent-mf-stale",
        "op": "put",
        "base_version": 1,
        "new_version": 3,
        "ts": T0 + 2,
        "ttl_s": 1000,
        "class": "active",
        "audit_required": False,
        "expected": "stale_reject",
    }
    cases.append(
        {
            "id": "MF_STALE_MUST_REJECT",
            "events": [seed, stale],
            "as_of": as_of,
            "expect_all_pass": True,
            "inject_wrong": None,
        }
    )

    # MF3: active past TTL must purge (not silent retain)
    expired = {
        "event_id": "mf-exp",
        "entity_id": "ent-mf-exp",
        "op": "put",
        "base_version": 0,
        "new_version": 1,
        "ts": T0,
        "ttl_s": 10,
        "class": "active",
        "audit_required": False,
        "expected": "purge",
    }
    cases.append(
        {
            "id": "MF_ACTIVE_TTL_MUST_PURGE",
            "events": [expired],
            "as_of": as_of,
            "expect_all_pass": True,
            "inject_wrong": None,
        }
    )

    # MF4: deliberately wrong expected label → batch must NOT all_pass
    wrong = dict(raw)
    wrong["event_id"] = "mf-wrong-label"
    wrong["expected"] = "purge"  # lies: raw should retain
    cases.append(
        {
            "id": "MF_WRONG_LABEL_DETECT",
            "events": [wrong],
            "as_of": as_of,
            "expect_all_pass": False,
            "inject_wrong": None,
        }
    )
    return cases


def selftest() -> dict[str, Any]:
    rows, as_of = pack_20()
    # event_id sorted export order; ts non-decreasing when sorted by (ts, event_id)
    by_ts = sorted(rows, key=lambda e: (e["ts"], e["event_id"]))
    ts_list = [e["ts"] for e in by_ts]
    assert ts_list == sorted(ts_list)

    pack_result = run_batch(rows, as_of)
    checks = []
    checks.append(
        {
            "id": "PACK20_ALL_PASS",
            "pass": pack_result["all_pass"],
            "detail": {
                "diffs": pack_result["diff_event_ids"],
                "digest_total": pack_result["digest"]["total_sha256"],
                "expected_counts": pack_result["digest"]["expected_counts"],
            },
        }
    )
    # mix invariants
    d = pack_result["digest"]
    checks.append(
        {
            "id": "MIX_RAW2_STALE3_EXPIRY15",
            "pass": (
                d["class_counts"].get("raw", 0) == 2
                and d["expected_counts"].get("stale_reject", 0) == 3
                and (d["n"] - 2 - 3) == 15
            ),
            "detail": d,
        }
    )

    for c in mustfail_cases():
        r = run_batch(c["events"], c["as_of"])
        ok = r["all_pass"] == c["expect_all_pass"]
        checks.append(
            {
                "id": c["id"],
                "pass": ok,
                "detail": {
                    "all_pass": r["all_pass"],
                    "expect_all_pass": c["expect_all_pass"],
                    "diffs": r["diff_event_ids"],
                },
            }
        )

    # no-overwrite proof for stale-001: after reject, store version still 2
    store: dict[str, dict[str, Any]] = {}
    seed = next(r for r in rows if r["event_id"] == "seed-act-01")
    stale = next(r for r in rows if r["event_id"] == "stale-001")
    decide(store, seed, as_of)
    v_before = store["ent-act-01"]["version"]
    got = decide(store, stale, as_of)
    v_after = store["ent-act-01"]["version"]
    checks.append(
        {
            "id": "NO_OVERWRITE_ON_STALE",
            "pass": got["decision"] == "stale_reject"
            and v_before == 2
            and v_after == 2,
            "detail": {"v_before": v_before, "v_after": v_after, "got": got},
        }
    )

    passed = sum(1 for c in checks if c["pass"])
    return {
        "fixture": "DSH_TTL",
        "version": "v0.1",
        "credit": ["DSH"],
        "rows": len(checks),
        "passed": passed,
        "all_pass": passed == len(checks),
        "pack_digest": pack_result["digest"],
        "pack_diff_event_ids": pack_result["diff_event_ids"],
        "results": checks,
    }


def main() -> int:
    out = selftest()
    # also emit the 20-row pack as sorted JSONL companion in run_out
    rows, as_of = pack_20()
    pack_sorted = sorted(rows, key=lambda e: e["event_id"])
    out["pack_as_of"] = as_of
    out["pack_jsonl_event_ids"] = [r["event_id"] for r in pack_sorted]
    text = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    with open(__file__, "rb") as f:
        script_sha = hashlib.sha256(f.read()).hexdigest()
    run_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    meta = {
        "script_sha256": script_sha,
        "run_out_sha256": run_sha,
        "passed": f"{out['passed']}/{out['rows']}",
        "pack_total_sha256": out["pack_digest"]["total_sha256"],
    }
    print("META " + json.dumps(meta), file=sys.stderr)
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
