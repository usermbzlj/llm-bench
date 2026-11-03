#!/usr/bin/env python3
"""CHAIN_RESOLUTION_ORDER v0.1  (structure credit: Hermes, EigenFlux; rows hand_built)

Problem: a successor/rewrite chain can fail several ways AT THE SAME HOP.
If two implementations check failures in different orders, the same row
lands in two different buckets and a cross-implementation diff never closes.
Rule (total order, emitted as a field so a 2nd implementation copies it):
  1 EXISTENCE       successor id not present        -> SUCCESSOR_MISSING
  2 WRITER          node writer != expected writer  -> WRITER_MISMATCH
  3 REWRITE_TARGET  rewrite target not committed    -> REWRITE_TARGET_MISMATCH
  4 CYCLE           id repeats (first-occurrence index, NOT set size)
                                                    -> CONDITIONAL_CYCLE
  step budget exhausted with no repeat              -> UNDECIDABLE_LIMIT
  terminal node reached cleanly                     -> RESOLVED
CONDITIONAL_CYCLE and UNDECIDABLE_LIMIT are separate on purpose: a cycle is
a data fact; a limit hit is a fixture/budget fact. Merging them hides which.
Compare implementations by check_order FIRST, then by verdict.
analyze_only, stdlib only, exit 0 iff selftest all pass.
"""
from __future__ import annotations
import json, sys

CHECK_ORDER = ["EXISTENCE", "WRITER", "REWRITE_TARGET", "CYCLE"]

def judge(row, order=CHECK_ORDER, cycle_by_index=True):
    nodes, cur, writer, limit = row["nodes"], row["start"], row["writer"], row.get("max_steps", 16)
    first_idx, path = {}, []
    for step in range(limit):
        if cycle_by_index and cur in first_idx and "CYCLE" in order:
            return {"verdict": "CONDITIONAL_CYCLE", "hop": step, "cycle_start_index": first_idx[cur], "check_order": order}
        first_idx.setdefault(cur, step); path.append(cur)
        n = nodes.get(cur)
        fails = {
            "EXISTENCE": n is None,
            "WRITER": n is not None and n.get("writer") != writer,
            "REWRITE_TARGET": n is not None and n.get("rewrite_target_committed") is False,
        }
        for c in order:
            if fails.get(c):
                code = {"EXISTENCE": "SUCCESSOR_MISSING", "WRITER": "WRITER_MISMATCH", "REWRITE_TARGET": "REWRITE_TARGET_MISMATCH"}[c]
                return {"verdict": code, "hop": step, "node": cur, "check_order": order}
        if n.get("next") is None:
            return {"verdict": "RESOLVED", "hop": step, "path": path, "check_order": order}
        cur = n["next"]
    return {"verdict": "UNDECIDABLE_LIMIT", "hop": limit, "check_order": order}

W = "w1"
ROWS = {
 "G1_clean": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": W, "next": None}}}, "RESOLVED"),
 "R1_missing": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "zz"}}}, "SUCCESSOR_MISSING"),
 "R2_writer": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": "w2", "next": None}}}, "WRITER_MISMATCH"),
 "R3_rewrite": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": W, "rewrite_target_committed": False, "next": None}}}, "REWRITE_TARGET_MISMATCH"),
 # same hop fails WRITER and REWRITE_TARGET -> order decides: WRITER wins
 "T1_writer_and_rewrite": ({"start": "a", "writer": W, "nodes": {"a": {"writer": "w2", "rewrite_target_committed": False, "next": None}}}, "WRITER_MISMATCH"),
 "C1_cycle": ({"start": "a", "writer": W, "nodes": {"a": {"writer": W, "next": "b"}, "b": {"writer": W, "next": "c"}, "c": {"writer": W, "next": "b"}}}, "CONDITIONAL_CYCLE"),
 "L1_limit": ({"start": "n0", "writer": W, "max_steps": 5, "nodes": {f"n{i}": {"writer": W, "next": f"n{i+1}"} for i in range(10)}}, "UNDECIDABLE_LIMIT"),
}

def main():
    out, ok = {}, 0
    checks = []
    for k, (row, exp) in ROWS.items():
        r = judge(row); out[k] = r
        checks.append((k, r["verdict"] == exp, f"{r['verdict']} (expect {exp})"))
    r = out["C1_cycle"]
    checks.append(("C1_cycle_start_index", r.get("cycle_start_index") == 1, f"cycle_start_index={r.get('cycle_start_index')} (expect 1, node b)"))
    # D1 discriminating: swapped order (REWRITE before WRITER) must flip T1
    sw = judge(ROWS["T1_writer_and_rewrite"][0], order=["EXISTENCE", "REWRITE_TARGET", "WRITER", "CYCLE"])["verdict"]
    checks.append(("D1_order_swap_flips_T1", sw == "REWRITE_TARGET_MISMATCH", f"swapped-order verdict={sw}"))
    # D2 discriminating: no index-based cycle check -> cycle hides as limit
    nb = judge(ROWS["C1_cycle"][0], cycle_by_index=False)["verdict"]
    checks.append(("D2_no_index_cycle_mislabels_as_limit", nb == "UNDECIDABLE_LIMIT", f"no-index verdict={nb}"))
    for name, good, msg in checks:
        ok += good; print(("PASS " if good else "FAIL ") + name + ": " + msg)
    json.dump({"check_order": CHECK_ORDER, "rows": out}, open("run_out_v0_1.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{len(checks)}")
    sys.exit(0 if ok == len(checks) else 1)

if __name__ == "__main__":
    main()
