#!/usr/bin/env python3
"""READ_JUDGE_SAME_PARTY v0.1

Structure-only fixture. Detects ledgers that report "all N rounds read OK"
when content digests are bit-identical across N rounds, yet the read-count
cell is unobservable because the reader and the judge are the same party.

Four machine-checkable rules (from Jerry isomorphic case, EigenFlux):
  1. Same-party (read_actor_id == judge_actor_id) + claimed_all_read +
     no independent read_probe → MUST NOT be PASS; mark UNOBSERVED or FAIL.
  2. Claiming "independent verification" while same-party is
     SAME_PARTY_FALSE_INDEPENDENT.
  3. Digest stable across N rounds + independent probe with read_count < N
     → CLAIMED_READ_INFLATED (must FAIL).
  4. Honest UNOBSERVED when same-party and no probe → PASS; independent
     probe with read_count == N → PASS.

Structure source: Jerry (EigenFlux) — four mandatory rule-source digests
identical across 21 rounds, yet "how many were actually read" unanswerable
because read and judge share one actor. General fixture; no personal
attribution in rows. analyze_only. Stdlib only.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "stable_digest_scan":
        rounds = receipt.get("rounds")
        digests = receipt.get("content_digests")
        read_actor = receipt.get("read_actor_id")
        judge_actor = receipt.get("judge_actor_id")
        claimed_all_read = receipt.get("claimed_all_read")
        claimed_independent = receipt.get("claimed_independent")
        observed_verdict = receipt.get("observed_verdict")  # PASS|FAIL|UNOBSERVED
        read_probe = receipt.get("read_probe")  # optional dict

        if not isinstance(rounds, int) or rounds < 1:
            return {"judge": "FAIL", "reason_code": "ROUNDS_INVALID"}
        if not isinstance(digests, list) or len(digests) != rounds:
            return {"judge": "FAIL", "reason_code": "DIGESTS_LEN_MISMATCH"}
        if not digests or any(not isinstance(d, str) or not d for d in digests):
            return {"judge": "FAIL", "reason_code": "DIGESTS_EMPTY"}

        uniq = set(digests)
        stable = len(uniq) == 1
        same_party = (
            isinstance(read_actor, str)
            and isinstance(judge_actor, str)
            and read_actor != ""
            and read_actor == judge_actor
        )

        if not stable:
            # Not this fixture's planted shape
            if observed_verdict == "PASS" and claimed_all_read is True:
                return {
                    "judge": "FAIL",
                    "reason_code": "UNSTABLE_CLAIMED_ALL_READ",
                    "detail": {"cardinality": len(uniq)},
                }
            return {"judge": "PASS", "reason_code": "UNSTABLE_OK"}

        # Stable digests — core shape
        probe_ok = isinstance(read_probe, dict) and read_probe.get("actor_id")
        probe_independent = (
            probe_ok
            and isinstance(read_probe.get("actor_id"), str)
            and read_probe["actor_id"] != ""
            and read_probe["actor_id"] != read_actor
        )

        if same_party and claimed_independent is True:
            return {
                "judge": "FAIL",
                "reason_code": "SAME_PARTY_FALSE_INDEPENDENT",
                "detail": {"read_actor_id": read_actor},
            }

        if same_party and not probe_independent:
            # Honest path: declare UNOBSERVED
            if observed_verdict == "UNOBSERVED" and claimed_all_read is not True:
                return {"judge": "PASS", "reason_code": "HONEST_UNOBSERVED"}
            # Dishonest: claimed all-read / PASS without independent probe
            if claimed_all_read is True or observed_verdict == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "READ_COUNT_UNOBSERVABLE",
                    "detail": {
                        "rounds": rounds,
                        "digest": digests[0],
                        "observed": observed_verdict,
                    },
                }
            return {
                "judge": "FAIL",
                "reason_code": "SAME_PARTY_UNEXPECTED",
                "detail": {"observed": observed_verdict},
            }

        if probe_independent:
            rc = read_probe.get("read_count")
            if not isinstance(rc, int):
                return {"judge": "FAIL", "reason_code": "PROBE_COUNT_MISSING"}
            if rc < rounds and (claimed_all_read is True or observed_verdict == "PASS"):
                return {
                    "judge": "FAIL",
                    "reason_code": "CLAIMED_READ_INFLATED",
                    "detail": {"read_count": rc, "rounds": rounds},
                }
            if rc < rounds and observed_verdict == "FAIL":
                return {"judge": "PASS", "reason_code": "INFLATION_CAUGHT"}
            if rc == rounds and observed_verdict == "PASS":
                return {"judge": "PASS", "reason_code": "INDEPENDENT_PROBE_OK"}
            if rc > rounds:
                return {
                    "judge": "FAIL",
                    "reason_code": "PROBE_COUNT_OVER",
                    "detail": {"read_count": rc, "rounds": rounds},
                }
            return {
                "judge": "FAIL",
                "reason_code": "PROBE_UNEXPECTED",
                "detail": {"read_count": rc, "observed": observed_verdict},
            }

        return {"judge": "FAIL", "reason_code": "STABLE_UNCLASSIFIED"}

    if kind == "flip_test":
        before = receipt.get("before_verdict")
        after = receipt.get("after_verdict")
        injected = receipt.get("injected")
        if before is None or after is None:
            return {"judge": "FAIL", "reason_code": "FLIP_PAIR_MISSING"}
        if injected != "independent_read_probe":
            return {"judge": "FAIL", "reason_code": "INJECT_WRONG"}
        if before == after:
            return {"judge": "FAIL", "reason_code": "FLIP_NOT_WIRED"}
        if before == "PASS" and after in ("FAIL", "UNOBSERVED"):
            return {"judge": "PASS", "reason_code": "FLIP_OK"}
        return {
            "judge": "FAIL",
            "reason_code": "FLIP_UNEXPECTED",
            "detail": {"before": before, "after": after},
        }

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


_DIGEST = "sha256:rulepack-v3-deadbeef"

FIXTURES = [
    {
        "case_id": "SAME-PARTY-FALSE-PASS",
        "receipt": {
            "kind": "stable_digest_scan",
            "rounds": 21,
            "content_digests": [_DIGEST] * 21,
            "read_actor_id": "agent-A",
            "judge_actor_id": "agent-A",
            "claimed_all_read": True,
            "claimed_independent": False,
            "observed_verdict": "PASS",
            "note": "同方读写判定仍报全读通过",
        },
        "expect": "READ_COUNT_UNOBSERVABLE",
    },
    {
        "case_id": "SAME-PARTY-FALSE-INDEPENDENT",
        "receipt": {
            "kind": "stable_digest_scan",
            "rounds": 21,
            "content_digests": [_DIGEST] * 21,
            "read_actor_id": "agent-A",
            "judge_actor_id": "agent-A",
            "claimed_all_read": True,
            "claimed_independent": True,
            "observed_verdict": "PASS",
        },
        "expect": "SAME_PARTY_FALSE_INDEPENDENT",
    },
    {
        "case_id": "HONEST-UNOBSERVED",
        "receipt": {
            "kind": "stable_digest_scan",
            "rounds": 21,
            "content_digests": [_DIGEST] * 21,
            "read_actor_id": "agent-A",
            "judge_actor_id": "agent-A",
            "claimed_all_read": False,
            "claimed_independent": False,
            "observed_verdict": "UNOBSERVED",
        },
        "expect": "HONEST_UNOBSERVED",
    },
    {
        "case_id": "CLAIMED-READ-INFLATED",
        "receipt": {
            "kind": "stable_digest_scan",
            "rounds": 21,
            "content_digests": [_DIGEST] * 21,
            "read_actor_id": "agent-A",
            "judge_actor_id": "agent-B",
            "claimed_all_read": True,
            "claimed_independent": True,
            "observed_verdict": "PASS",
            "read_probe": {"actor_id": "probe-X", "read_count": 7},
        },
        "expect": "CLAIMED_READ_INFLATED",
    },
    {
        "case_id": "INFLATION-CAUGHT",
        "receipt": {
            "kind": "stable_digest_scan",
            "rounds": 21,
            "content_digests": [_DIGEST] * 21,
            "read_actor_id": "agent-A",
            "judge_actor_id": "agent-B",
            "claimed_all_read": False,
            "claimed_independent": True,
            "observed_verdict": "FAIL",
            "read_probe": {"actor_id": "probe-X", "read_count": 7},
        },
        "expect": "INFLATION_CAUGHT",
    },
    {
        "case_id": "INDEPENDENT-PROBE-OK",
        "receipt": {
            "kind": "stable_digest_scan",
            "rounds": 21,
            "content_digests": [_DIGEST] * 21,
            "read_actor_id": "agent-A",
            "judge_actor_id": "agent-B",
            "claimed_all_read": True,
            "claimed_independent": True,
            "observed_verdict": "PASS",
            "read_probe": {"actor_id": "probe-X", "read_count": 21},
        },
        "expect": "INDEPENDENT_PROBE_OK",
    },
    {
        "case_id": "FLIP-OK",
        "receipt": {
            "kind": "flip_test",
            "injected": "independent_read_probe",
            "before_verdict": "PASS",
            "after_verdict": "UNOBSERVED",
        },
        "expect": "FLIP_OK",
    },
    {
        "case_id": "FLIP-NOT-WIRED",
        "receipt": {
            "kind": "flip_test",
            "injected": "independent_read_probe",
            "before_verdict": "PASS",
            "after_verdict": "PASS",
        },
        "expect": "FLIP_NOT_WIRED",
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
        "version": "READ_JUDGE_SAME_PARTY/v0.1",
        "all_match": ok,
        "n": len(rows),
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
