#!/usr/bin/env python3
"""RAG_SILENT_MISS v0.1 — credit 布雷登-Brayden

Three assertions (from mutual pin):
  A. MISSING negctl must carry expected_failure_reason (prevent collapse with
     explicit-empty).
  B. Triple-column criterion: (issued_raw, recomputed_digest, criterion_version);
     when sample_revision changes, old interval is NOT_COMPARABLE (no backfill).
  C. Silent miss: retrieval returns empty/zero-hit while gold has a hit → FAIL
     with reason RAG_SILENT_MISS (not PASS / not EMPTY_OK).

analyze_only. Stdlib only.
"""
from __future__ import annotations
import hashlib, json, sys
from typing import Any


def digest_of(obj: Any) -> str:
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def judge(row: dict[str, Any]) -> dict[str, Any]:
    kind = row.get("kind")
    if kind == "MISSING_NEGCTL":
        if not row.get("expected_failure_reason"):
            return {
                "judge": "FAIL",
                "reason_code": "MISSING_WITHOUT_EXPECTED_REASON",
            }
        return {"judge": "PASS", "reason_code": "MISSING_NEGCTL_DECLARED"}

    if kind == "REVISION_COMPARE":
        a = row.get("sample_revision_a")
        b = row.get("sample_revision_b")
        if a != b:
            return {"judge": "PASS", "reason_code": "NOT_COMPARABLE"}
        # same revision: compare digests under pinned criterion_version
        if row.get("issued_raw_digest") != row.get("recomputed_digest"):
            return {"judge": "FAIL", "reason_code": "DIGEST_MISMATCH"}
        if not row.get("criterion_version"):
            return {"judge": "FAIL", "reason_code": "CRITERION_VERSION_ABSENT"}
        return {"judge": "PASS", "reason_code": "DIGEST_MATCH"}

    if kind == "RETRIEVAL":
        gold_hits = int(row.get("gold_hit_count") or 0)
        got_hits = int(row.get("retrieved_hit_count") or 0)
        if gold_hits > 0 and got_hits == 0:
            return {"judge": "FAIL", "reason_code": "RAG_SILENT_MISS"}
        if gold_hits == 0 and got_hits == 0:
            # explicit empty must be declared
            if row.get("empty_declared") is True:
                return {"judge": "PASS", "reason_code": "EMPTY_OK"}
            return {"judge": "FAIL", "reason_code": "EMPTY_UNDECLARED"}
        return {"judge": "PASS", "reason_code": "RETRIEVAL_OK"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}


FIXTURES = [
    {
        "case_id": "RSM-MISSING-DECLARED",
        "row": {
            "kind": "MISSING_NEGCTL",
            "expected_failure_reason": "index_key_absent",
        },
        "expect": "MISSING_NEGCTL_DECLARED",
    },
    {
        "case_id": "RSM-MISSING-COLLAPSE",
        "row": {"kind": "MISSING_NEGCTL"},
        "expect": "MISSING_WITHOUT_EXPECTED_REASON",
    },
    {
        "case_id": "RSM-REV-NOT-COMPARABLE",
        "row": {
            "kind": "REVISION_COMPARE",
            "sample_revision_a": "s1",
            "sample_revision_b": "s2",
            "issued_raw_digest": "aaa",
            "recomputed_digest": "bbb",
            "criterion_version": "c1",
        },
        "expect": "NOT_COMPARABLE",
    },
    {
        "case_id": "RSM-DIGEST-MATCH",
        "row": {
            "kind": "REVISION_COMPARE",
            "sample_revision_a": "s1",
            "sample_revision_b": "s1",
            "issued_raw_digest": "deadbeef",
            "recomputed_digest": "deadbeef",
            "criterion_version": "c1",
        },
        "expect": "DIGEST_MATCH",
    },
    {
        "case_id": "RSM-SILENT-MISS",
        "row": {
            "kind": "RETRIEVAL",
            "gold_hit_count": 2,
            "retrieved_hit_count": 0,
        },
        "expect": "RAG_SILENT_MISS",
    },
    {
        "case_id": "RSM-EMPTY-OK",
        "row": {
            "kind": "RETRIEVAL",
            "gold_hit_count": 0,
            "retrieved_hit_count": 0,
            "empty_declared": True,
        },
        "expect": "EMPTY_OK",
    },
    {
        "case_id": "RSM-EMPTY-UNDECLARED",
        "row": {
            "kind": "RETRIEVAL",
            "gold_hit_count": 0,
            "retrieved_hit_count": 0,
        },
        "expect": "EMPTY_UNDECLARED",
    },
]


def main() -> int:
    rows = []
    ok = True
    for fx in FIXTURES:
        got = judge(fx["row"])
        match = got.get("reason_code") == fx["expect"]
        ok = ok and match
        rows.append(
            {
                "case_id": fx["case_id"],
                "expect": fx["expect"],
                "got": got.get("reason_code"),
                "match": match,
            }
        )
    # fixture pack digest: sorted case rows only
    pack = [{"case_id": r["case_id"], "expect": next(f["expect"] for f in FIXTURES if f["case_id"] == r["case_id"]), "row": next(f["row"] for f in FIXTURES if f["case_id"] == r["case_id"])} for r in rows]
    pack_digest = digest_of(pack)
    out = {
        "version": "RAG_SILENT_MISS/v0.1",
        "credit": "布雷登-Brayden",
        "all_match": ok,
        "pack_digest": pack_digest,
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
