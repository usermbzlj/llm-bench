#!/usr/bin/env python3
"""ANCHOR_SHARED_FAULT_DOMAIN v0.1

Structure-only fixture. Failure shapes from EigenFlux PMs:

  工具人的小工具 — three anchors (exec_receipt / artifact / reconciliation)
  constructed from one scheduler response → shared fault domain → expect FAIL
  (counting distinct agent labels ≠ independence).

  尹子璐的 Agent — supervisor and supervised share the same fault domain and
  timeout window; both fail but report "supervise pass" → expect FAIL.

Honest path: each independence axis (fault_domain_id, scheduler_response_id,
timeout_window_id, hash_layer_id) is actually distinct across the roles that
claim to corroborate each other; reported verdict may then be PASS.

General fixture; analyze_only. Stdlib only.
Credit: 工具人的小工具 + 尹子璐的 Agent (structure); Grok Bot (implementation).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "tri_anchor_corroboration":
        # Three anchors claiming independent corroboration of one job.
        anchors = receipt.get("anchors") or []
        if not isinstance(anchors, list) or len(anchors) < 3:
            return {"judge": "FAIL", "reason_code": "ANCHORS_INCOMPLETE"}
        roles = {a.get("role") for a in anchors if isinstance(a, dict)}
        needed = {"exec_receipt", "artifact", "reconciliation"}
        if not needed.issubset(roles):
            return {"judge": "FAIL", "reason_code": "ANCHOR_ROLES_MISSING", "detail": {"have": sorted(roles)}}

        by_role = {a["role"]: a for a in anchors if isinstance(a, dict) and a.get("role") in needed}
        sched_ids = {_norm(by_role[r].get("scheduler_response_id")) for r in needed}
        fault_ids = {_norm(by_role[r].get("fault_domain_id")) for r in needed}
        hash_ids = {_norm(by_role[r].get("hash_layer_id")) for r in needed}
        reported = receipt.get("reported_verdict")  # PASS|FAIL|...
        agent_labels = {_norm(by_role[r].get("agent_label")) for r in needed}

        # Missing axis → cannot claim independence
        if None in sched_ids or None in fault_ids:
            return {"judge": "FAIL", "reason_code": "AXIS_UNDECLARED"}

        shared_sched = len(sched_ids) == 1
        shared_fault = len(fault_ids) == 1
        shared_hash = None not in hash_ids and len(hash_ids) == 1
        distinct_agents = None not in agent_labels and len(agent_labels) == len(needed)

        # False-green: agent count looks independent but scheduler/fault collapsed
        if (shared_sched or shared_fault or shared_hash) and reported == "PASS":
            return {
                "judge": "FAIL",
                "reason_code": "SHARED_FAULT_DOMAIN_FALSE_PASS",
                "detail": {
                    "shared_scheduler_response": shared_sched,
                    "shared_fault_domain": shared_fault,
                    "shared_hash_layer": shared_hash,
                    "distinct_agent_labels": distinct_agents,
                    "sched_ids": sorted(x for x in sched_ids if x),
                    "fault_ids": sorted(x for x in fault_ids if x),
                },
            }
        if shared_sched or shared_fault or shared_hash:
            return {
                "judge": "FAIL",
                "reason_code": "SHARED_FAULT_DOMAIN",
                "detail": {
                    "shared_scheduler_response": shared_sched,
                    "shared_fault_domain": shared_fault,
                    "shared_hash_layer": shared_hash,
                },
            }

        # Honest: all three axes distinct
        if len(sched_ids) == 3 and len(fault_ids) == 3 and (None in hash_ids or len(hash_ids) == 3):
            if reported in ("PASS", "FAIL"):
                return {"judge": "PASS", "reason_code": "HONEST_DISTINCT_DOMAINS"}
            return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

        return {"judge": "FAIL", "reason_code": "PARTIAL_COLLAPSE"}

    if kind == "supervisor_same_domain":
        # 尹子璐: supervisor + supervised share fault domain / timeout window.
        sup = receipt.get("supervisor") or {}
        sub = receipt.get("supervised") or {}
        if not isinstance(sup, dict) or not isinstance(sub, dict):
            return {"judge": "FAIL", "reason_code": "ROLES_MISSING"}
        fd_sup = _norm(sup.get("fault_domain_id"))
        fd_sub = _norm(sub.get("fault_domain_id"))
        tw_sup = _norm(sup.get("timeout_window_id"))
        tw_sub = _norm(sub.get("timeout_window_id"))
        sup_outcome = receipt.get("supervisor_outcome")  # pass|fail
        sub_outcome = receipt.get("supervised_outcome")
        reported = receipt.get("reported_supervise_verdict")  # pass|fail

        if fd_sup is None or fd_sub is None or tw_sup is None or tw_sub is None:
            return {"judge": "FAIL", "reason_code": "AXIS_UNDECLARED"}

        same_domain = fd_sup == fd_sub
        same_window = tw_sup == tw_sub
        both_failed = sup_outcome == "fail" and sub_outcome == "fail"

        # False-green: same domain+window, both fail, but report supervise pass
        if same_domain and same_window and both_failed and reported == "pass":
            return {
                "judge": "FAIL",
                "reason_code": "SUPERVISOR_SAME_DOMAIN_FALSE_PASS",
                "detail": {
                    "fault_domain_id": fd_sup,
                    "timeout_window_id": tw_sup,
                },
            }
        if same_domain and same_window:
            return {"judge": "FAIL", "reason_code": "SUPERVISOR_SAME_DOMAIN"}

        # Honest: distinct domain or window; reported consistent with outcomes
        if fd_sup != fd_sub or tw_sup != tw_sub:
            if reported in ("pass", "fail"):
                return {"judge": "PASS", "reason_code": "HONEST_SUPERVISOR_SEPARATION"}
            return {"judge": "FAIL", "reason_code": "REPORTED_VERDICT_MISSING"}

        return {"judge": "FAIL", "reason_code": "UNCLASSIFIED"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND"}


CASES: list[dict[str, Any]] = [
    # --- tri_anchor: shared scheduler response (工具人 primary) ---
    {
        "case_id": "asfd-tri-shared-sched-false-pass",
        "kind": "tri_anchor_corroboration",
        "reported_verdict": "PASS",
        "anchors": [
            {"role": "exec_receipt", "scheduler_response_id": "sched-1", "fault_domain_id": "fd-A", "hash_layer_id": "h1", "agent_label": "a1"},
            {"role": "artifact", "scheduler_response_id": "sched-1", "fault_domain_id": "fd-B", "hash_layer_id": "h2", "agent_label": "a2"},
            {"role": "reconciliation", "scheduler_response_id": "sched-1", "fault_domain_id": "fd-C", "hash_layer_id": "h3", "agent_label": "a3"},
        ],
        "expect_judge": "FAIL",
        "expect_reason": "SHARED_FAULT_DOMAIN_FALSE_PASS",
    },
    {
        "case_id": "asfd-tri-shared-fault-false-pass",
        "kind": "tri_anchor_corroboration",
        "reported_verdict": "PASS",
        "anchors": [
            {"role": "exec_receipt", "scheduler_response_id": "s1", "fault_domain_id": "fd-X", "hash_layer_id": "h1", "agent_label": "a1"},
            {"role": "artifact", "scheduler_response_id": "s2", "fault_domain_id": "fd-X", "hash_layer_id": "h2", "agent_label": "a2"},
            {"role": "reconciliation", "scheduler_response_id": "s3", "fault_domain_id": "fd-X", "hash_layer_id": "h3", "agent_label": "a3"},
        ],
        "expect_judge": "FAIL",
        "expect_reason": "SHARED_FAULT_DOMAIN_FALSE_PASS",
    },
    {
        "case_id": "asfd-tri-shared-hash-false-pass",
        "kind": "tri_anchor_corroboration",
        "reported_verdict": "PASS",
        "anchors": [
            {"role": "exec_receipt", "scheduler_response_id": "s1", "fault_domain_id": "fd-A", "hash_layer_id": "hash-shared", "agent_label": "a1"},
            {"role": "artifact", "scheduler_response_id": "s2", "fault_domain_id": "fd-B", "hash_layer_id": "hash-shared", "agent_label": "a2"},
            {"role": "reconciliation", "scheduler_response_id": "s3", "fault_domain_id": "fd-C", "hash_layer_id": "hash-shared", "agent_label": "a3"},
        ],
        "expect_judge": "FAIL",
        "expect_reason": "SHARED_FAULT_DOMAIN_FALSE_PASS",
    },
    {
        "case_id": "asfd-tri-shared-sched-no-pass-claim",
        "kind": "tri_anchor_corroboration",
        "reported_verdict": "FAIL",
        "anchors": [
            {"role": "exec_receipt", "scheduler_response_id": "sched-9", "fault_domain_id": "fd-A", "hash_layer_id": "h1", "agent_label": "a1"},
            {"role": "artifact", "scheduler_response_id": "sched-9", "fault_domain_id": "fd-B", "hash_layer_id": "h2", "agent_label": "a2"},
            {"role": "reconciliation", "scheduler_response_id": "sched-9", "fault_domain_id": "fd-C", "hash_layer_id": "h3", "agent_label": "a3"},
        ],
        "expect_judge": "FAIL",
        "expect_reason": "SHARED_FAULT_DOMAIN",
    },
    {
        "case_id": "asfd-tri-honest-distinct",
        "kind": "tri_anchor_corroboration",
        "reported_verdict": "PASS",
        "anchors": [
            {"role": "exec_receipt", "scheduler_response_id": "s1", "fault_domain_id": "fd-A", "hash_layer_id": "h1", "agent_label": "a1"},
            {"role": "artifact", "scheduler_response_id": "s2", "fault_domain_id": "fd-B", "hash_layer_id": "h2", "agent_label": "a2"},
            {"role": "reconciliation", "scheduler_response_id": "s3", "fault_domain_id": "fd-C", "hash_layer_id": "h3", "agent_label": "a3"},
        ],
        "expect_judge": "PASS",
        "expect_reason": "HONEST_DISTINCT_DOMAINS",
    },
    {
        "case_id": "asfd-tri-axis-undeclared",
        "kind": "tri_anchor_corroboration",
        "reported_verdict": "PASS",
        "anchors": [
            {"role": "exec_receipt", "scheduler_response_id": "s1", "fault_domain_id": None, "hash_layer_id": "h1", "agent_label": "a1"},
            {"role": "artifact", "scheduler_response_id": "s2", "fault_domain_id": "fd-B", "hash_layer_id": "h2", "agent_label": "a2"},
            {"role": "reconciliation", "scheduler_response_id": "s3", "fault_domain_id": "fd-C", "hash_layer_id": "h3", "agent_label": "a3"},
        ],
        "expect_judge": "FAIL",
        "expect_reason": "AXIS_UNDECLARED",
    },
    {
        "case_id": "asfd-tri-roles-missing",
        "kind": "tri_anchor_corroboration",
        "reported_verdict": "PASS",
        "anchors": [
            {"role": "exec_receipt", "scheduler_response_id": "s1", "fault_domain_id": "fd-A", "hash_layer_id": "h1", "agent_label": "a1"},
            {"role": "artifact", "scheduler_response_id": "s2", "fault_domain_id": "fd-B", "hash_layer_id": "h2", "agent_label": "a2"},
        ],
        "expect_judge": "FAIL",
        "expect_reason": "ANCHORS_INCOMPLETE",
    },
    # --- supervisor same domain (尹子璐) ---
    {
        "case_id": "asfd-sup-same-domain-false-pass",
        "kind": "supervisor_same_domain",
        "supervisor": {"fault_domain_id": "fd-Z", "timeout_window_id": "tw-1"},
        "supervised": {"fault_domain_id": "fd-Z", "timeout_window_id": "tw-1"},
        "supervisor_outcome": "fail",
        "supervised_outcome": "fail",
        "reported_supervise_verdict": "pass",
        "expect_judge": "FAIL",
        "expect_reason": "SUPERVISOR_SAME_DOMAIN_FALSE_PASS",
    },
    {
        "case_id": "asfd-sup-same-domain-detected",
        "kind": "supervisor_same_domain",
        "supervisor": {"fault_domain_id": "fd-Z", "timeout_window_id": "tw-1"},
        "supervised": {"fault_domain_id": "fd-Z", "timeout_window_id": "tw-1"},
        "supervisor_outcome": "fail",
        "supervised_outcome": "fail",
        "reported_supervise_verdict": "fail",
        "expect_judge": "FAIL",
        "expect_reason": "SUPERVISOR_SAME_DOMAIN",
    },
    {
        "case_id": "asfd-sup-honest-separation",
        "kind": "supervisor_same_domain",
        "supervisor": {"fault_domain_id": "fd-sup", "timeout_window_id": "tw-sup"},
        "supervised": {"fault_domain_id": "fd-sub", "timeout_window_id": "tw-sub"},
        "supervisor_outcome": "pass",
        "supervised_outcome": "fail",
        "reported_supervise_verdict": "fail",
        "expect_judge": "PASS",
        "expect_reason": "HONEST_SUPERVISOR_SEPARATION",
    },
]


def main() -> int:
    results = []
    failures = []
    for case in CASES:
        receipt = {k: v for k, v in case.items() if k not in ("case_id", "expect_judge", "expect_reason")}
        out = judge(receipt)
        ok = out.get("judge") == case["expect_judge"] and out.get("reason_code") == case["expect_reason"]
        row = {
            "case_id": case["case_id"],
            "ok": ok,
            "expect_judge": case["expect_judge"],
            "expect_reason": case["expect_reason"],
            "got": out,
        }
        results.append(row)
        if not ok:
            failures.append(row)

    payload = {
        "fixture": "ANCHOR_SHARED_FAULT_DOMAIN",
        "version": "v0.1",
        "policy": "analyze_only REFERENCE_ONLY fictional_desensitized no_secrets",
        "credit": ["工具人的小工具", "尹子璐的 Agent"],
        "n_cases": len(CASES),
        "n_pass": len(CASES) - len(failures),
        "n_fail": len(failures),
        "results": results,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    payload["run_out_sha256"] = digest
    out_path = __file__.replace(".py", "_run_out.json") if False else None
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    print(text)
    print(f"META={'PASS' if not failures else 'FAIL'} cases={len(CASES)} fail={len(failures)}", file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
