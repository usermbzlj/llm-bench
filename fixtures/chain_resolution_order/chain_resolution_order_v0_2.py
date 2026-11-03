#!/usr/bin/env python3
"""CHAIN_RESOLUTION_ORDER v0.2  (structure credit: Hermes, EigenFlux; rows hand_built)

v0.2 answers Hermes' critique of v0.1: a first-failure verdict makes
"no cycle reported" ambiguous -- it can mean "no cycle" OR "cycle never
evaluated because an earlier check short-circuited". Downstream would read
the second as the first, and no v0.1 selftest could show it.

Changes vs v0.1 (verdict semantics unchanged, so v0.1 rows still agree):
  * every result carries check_status: {check: FAIL|PASS|NOT_EVALUATED}.
    Short-circuit is now visible in data, not only in docs.
  * after the first failure, a diagnostic-only shadow walk (ignores WRITER
    and REWRITE_TARGET, follows `next` when present) records masked
    failures in `masked` (e.g. ["CYCLE"]). The verdict stays the first
    failure; masked never changes the verdict.
  * CYCLE vs LIMIT boundary is fixed by rule, not by discovery order:
      a revisit observed at step s < max_steps          -> CONDITIONAL_CYCLE
      budget exhausted before any revisit is observed   -> UNDECIDABLE_LIMIT
    even when the graph provably cycles past the budget. Limit is a fixture
    fact; we never infer a cycle we did not observe within budget.
analyze_only, stdlib only, exit 0 iff selftest all pass.
"""
from __future__ import annotations
import json, sys

CHECK_ORDER = ["EXISTENCE", "WRITER", "REWRITE_TARGET", "CYCLE"]
CODE = {"EXISTENCE": "SUCCESSOR_MISSING", "WRITER": "WRITER_MISMATCH", "REWRITE_TARGET": "REWRITE_TARGET_MISMATCH"}

def _node_fails(n, writer):
    return {"EXISTENCE": n is None,
            "WRITER": n is not None and n.get("writer") != writer,
            "REWRITE_TARGET": n is not None and n.get("rewrite_target_committed") is False}

def _shadow(row, cur, seen, step, limit):
    """Diagnostic-only continuation: which later checks would fail?"""
    nodes, writer, masked = row["nodes"], row["writer"], set()
    seen = dict(seen)
    while step < limit:
        if cur in seen:
            masked.add("CYCLE"); break
        seen[cur] = step
        n = nodes.get(cur)
        f = _node_fails(n, writer)
        for c in ("WRITER", "REWRITE_TARGET", "EXISTENCE"):
            if f[c]: masked.add(c)
        if n is None or n.get("next") is None: break
        cur, step = n["next"], step + 1
    return masked

def judge(row, order=CHECK_ORDER, shadow=True):
    nodes, cur, writer, limit = row["nodes"], row["start"], row["writer"], row.get("max_steps", 16)
    first_idx = {}
    status = {c: "NOT_EVALUATED" for c in order}
    for step in range(limit):
        if cur in first_idx:
            status["CYCLE"] = "FAIL"
            return {"verdict": "CONDITIONAL_CYCLE", "hop": step, "cycle_start_index": first_idx[cur],
                    "check_order": order, "check_status": status, "masked": []}
        first_idx[cur] = step
        n = nodes.get(cur)
        f = _node_fails(n, writer)
        for c in order:
            if c == "CYCLE": continue
            if f[c]:
                status[c] = "FAIL"
                masked = set()
                if shadow:
                    masked = {x for x in order if x != c and f.get(x)}  # same-hop masked
                    if n is not None and n.get("next") is not None:
                        masked |= _shadow(row, n["next"], first_idx, step + 1, limit)
                    masked.discard(c)
                return {"verdict": CODE[c], "hop": step, "node": cur, "check_order": order,
                        "check_status": status, "masked": sorted(masked, key=order.index)}
            if status[c] != "FAIL": status[c] = "PASS"
        if n.get("next") is None:
            status["CYCLE"] = "PASS"
            return {"verdict": "RESOLVED", "hop": step, "check_order": order, "check_status": status, "masked": []}
        cur = n["next"]
    status["CYCLE"] = "NOT_EVALUATED"
    return {"verdict": "UNDECIDABLE_LIMIT", "hop": limit, "check_order": order, "check_status": status, "masked": []}

W = "w1"
ROWS = {
 # v0.1 rows (verdicts must not move)
 "G1_clean": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": W, "next": None}}}, "RESOLVED"),
 "R1_missing": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "zz"}}}, "SUCCESSOR_MISSING"),
 "R2_writer": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": "w2", "next": None}}}, "WRITER_MISMATCH"),
 "R3_rewrite": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": W, "rewrite_target_committed": False, "next": None}}}, "REWRITE_TARGET_MISMATCH"),
 "T1_writer_and_rewrite": ({"start": "a", "writer": W, "nodes": {"a": {"writer": "w2", "rewrite_target_committed": False, "next": None}}}, "WRITER_MISMATCH"),
 "C1_cycle": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": W, "next": "c"}, "c": {"writer": W, "next": "b"}}}, "CONDITIONAL_CYCLE"),
 "L1_limit": ({"start": "n0", "writer": W, "max_steps": 5, "nodes": {f"n{i}": {"writer": W, "next": f"n{i+1}"} for i in range(10)}}, "UNDECIDABLE_LIMIT"),
 # v0.2 rows (Hermes): miss two levels, the earlier one masks the later cycle
 "M1_writer_masks_cycle": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": "w2", "next": "c"}, "c": {"writer": W, "next": "b"}}}, "WRITER_MISMATCH"),
 "M1C_writer_no_cycle": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": "w2", "next": "c"}, "c": {"writer": W, "next": None}}}, "WRITER_MISMATCH"),
 # boundary: repeat observed on the last in-budget step vs one step past budget
 "B1_cycle_at_last_step": ({"start": "a", "writer": W, "max_steps": 3, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": W, "next": "a"}}}, "CONDITIONAL_CYCLE"),
 "B2_cycle_past_budget": ({"start": "a", "writer": W, "max_steps": 2, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": W, "next": "a"}}}, "UNDECIDABLE_LIMIT"),
}

def main():
    out, checks = {}, []
    for k, (row, exp) in ROWS.items():
        r = judge(row); out[k] = r
        checks.append((k, r["verdict"] == exp, f"{r['verdict']} (expect {exp})"))
    checks.append(("C1_cycle_start_index", out["C1_cycle"].get("cycle_start_index") == 1, f"cycle_start_index={out['C1_cycle'].get('cycle_start_index')}"))
    sw = judge(ROWS["T1_writer_and_rewrite"][0], order=["EXISTENCE", "REWRITE_TARGET", "WRITER", "CYCLE"])["verdict"]
    checks.append(("D1_order_swap_flips_T1", sw == "REWRITE_TARGET_MISMATCH", f"swapped-order verdict={sw}"))
    # D3: M1 vs M1C have identical verdicts; only masked/check_status separate them
    m1, m1c = out["M1_writer_masks_cycle"], out["M1C_writer_no_cycle"]
    checks.append(("D3_M1_masked_has_CYCLE", m1["masked"] == ["CYCLE"], f"masked={m1['masked']}"))
    checks.append(("D3C_M1C_masked_empty", m1c["masked"] == [], f"masked={m1c['masked']}"))
    checks.append(("D3S_cycle_not_evaluated_in_M1", m1["check_status"]["CYCLE"] == "NOT_EVALUATED", f"CYCLE={m1['check_status']['CYCLE']}"))
    # D4: v0.1-style output (verdict only) cannot tell M1 from M1C -> the false 'no cycle' read
    checks.append(("D4_verdict_only_collapses_M1_M1C", m1["verdict"] == m1c["verdict"], "verdict-only diff = 0 rows -> masking invisible without check_status"))
    # D5: limit row never claims CYCLE PASS
    checks.append(("D5_limit_cycle_not_evaluated", out["B2_cycle_past_budget"]["check_status"]["CYCLE"] == "NOT_EVALUATED", "B2 CYCLE=NOT_EVALUATED"))
    # D6: T1 same-hop mask recorded
    checks.append(("D6_T1_masks_REWRITE", out["T1_writer_and_rewrite"]["masked"] == ["REWRITE_TARGET"], f"masked={out['T1_writer_and_rewrite']['masked']}"))
    ok = 0
    for name, good, msg in checks:
        ok += good; print(("PASS " if good else "FAIL ") + name + ": " + msg)
    json.dump({"check_order": CHECK_ORDER, "rows": out}, open("run_out_v0_2.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{len(checks)}")
    sys.exit(0 if ok == len(checks) else 1)

if __name__ == "__main__":
    main()
