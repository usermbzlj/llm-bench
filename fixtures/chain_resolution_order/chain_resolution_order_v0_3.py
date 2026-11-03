#!/usr/bin/env python3
"""CHAIN_RESOLUTION_ORDER v0.3  (critique credit: Hermes, EigenFlux; X1 cross-file
cycle shape credit: 麦麦和糖糖; impl: Grok Bot; all rows hand_built; analyze_only)

v0.2 stays untouched; its 11 rows are re-judged here by import and their
verdicts must not move. v0.3 adds four things, each with a must-fail arm:

1. masked != NOT_EVALUATED (Hermes). masked means "evaluated, non-decisive".
   A check found only by the diagnostic shadow walk now gets status
   FAIL_MASKED, never NOT_EVALUATED. Invariant I1: every name in masked has
   status FAIL_MASKED; nothing with status NOT_EVALUATED is in masked.
   (v0.2 reported M1 CYCLE=NOT_EVALUATED while masked=[CYCLE] -- the exact
   ambiguity Hermes flagged; v0.3 D3S is the corrected assertion.)

2. Canonical cycle order (Hermes X1). The expected value of a cycle is the
   cycle rotated so its smallest node id is first (directed, no reflection).
   Observed traversal order is input only and never appears in assertions:
   changing the start node / traversal must not move the expected value.
   Cross-file cycle X1 (a@f1 -> c@f2 -> b@f1 -> a): canonical [a,c,b] from
   every start. Naive snapshot (expect = observed order from start a) is
   wrong on 2/3 starts.

3. SELF_CYCLE vs DUP_DEF_CYCLE (Hermes X2). A->A with one definition is
   CYCLE_SELF. If id A is defined in >=2 files, "A->A" is not a self-loop:
   the edge may land on the other file's copy, so the row is
   DUP_DEF_CYCLE (some copy points back into the path) or
   DUP_DEF_UNRESOLVED (no copy points back). Two codes, never merged.
   Naive dict-build (last definition wins) flips with file order.

4. Evidence audit for UNDECIDABLE_LIMIT rows (Hermes): three columns
   walked_max_path_len, visited_prefix_sha256, budget + budget_unit in
   {nodes,edges,ms} + budget_scope in {per_path,shared_pool} + per-column
   run_uid. Priority (first hit wins, note carries the rest):
     COLUMN_SOURCE_MISMATCH  run_uid differs across columns ("given, but not
                             the same run" -- looks complete, most dangerous)
     NOT_EVALUABLE           any column / unit / scope / run_uid missing
     SEMANTIC_MISMATCH       hash domain is not ordered_path+prefix_len
                             (set-hash collides on different walks)
     HASH_MISMATCH           recomputed ordered hash != reported
     EVIDENCED               UNDECIDABLE_LIMIT stands, with evidence
   Hash domain fixed: sha256 of canonical JSON {"path":[...],"prefix_len":n}
   (sort_keys, separators=(",",":"), ensure_ascii=False).
   Cycle provable past budget still -> NOT_EVALUATED + note (unchanged).

stdlib only; exit 0 iff selftest all pass.
"""
from __future__ import annotations
import hashlib, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain_resolution_order_v0_2 as v2  # noqa: E402

# ---------------------------------------------------------------- 1. masked
def judge(row, order=v2.CHECK_ORDER):
    r = v2.judge(row, order=order)
    st = dict(r["check_status"])
    for c in r["masked"]:
        st[c] = "FAIL_MASKED"
    r = dict(r, check_status=st)
    if r["verdict"] == "CONDITIONAL_CYCLE":
        cyc = observed_cycle(row)
        r["cycle_canonical"] = canonical_cycle(cyc)
        if len(cyc) == 1:
            r["verdict"] = "CYCLE_SELF"
    return r

def invariant_masked(r):
    return all(r["check_status"][c] == "FAIL_MASKED" for c in r["masked"]) and \
        not any(s == "NOT_EVALUATED" and c in r["masked"] for c, s in r["check_status"].items())

# ------------------------------------------------------- 2. canonical order
def observed_cycle(row):
    nodes, cur, seen, path = row["nodes"], row["start"], {}, []
    for i in range(row.get("max_steps", 16)):
        if cur in seen:
            return path[seen[cur]:]
        seen[cur] = i; path.append(cur)
        n = nodes.get(cur)
        if n is None or n.get("next") is None:
            return []
        cur = n["next"]
    return []

def canonical_cycle(cyc):
    if not cyc:
        return []
    k = cyc.index(min(cyc))
    return cyc[k:] + cyc[:k]

# ------------------------------------------------- 3. multi-file definitions
def judge_defs(start, defs, max_steps=16):
    """defs: list of {id, file, next, writer?}. Definition layer first."""
    by_id = {}
    for d in defs:
        by_id.setdefault(d["id"], []).append(d)
    cur, path = start, []
    for _ in range(max_steps):
        ds = by_id.get(cur)
        if not ds:
            return {"verdict": "SUCCESSOR_MISSING", "node": cur, "path": path}
        files = sorted({d["file"] for d in ds})
        if len(files) >= 2:
            back = [d for d in ds if d.get("next") is not None and (d["next"] == cur or d["next"] in path)]
            return {"verdict": "DUP_DEF_CYCLE" if back else "DUP_DEF_UNRESOLVED",
                    "node": cur, "files": files, "path": path + [cur]}
        if cur in path:
            cyc = path[path.index(cur):]
            files_on = sorted({by_id[x][0]["file"] for x in cyc})
            return {"verdict": "CYCLE_SELF" if len(cyc) == 1 else "CONDITIONAL_CYCLE",
                    "cycle_canonical": canonical_cycle(cyc), "cycle_files": files_on,
                    "cross_file": len(files_on) > 1}
        path.append(cur)
        nxt = ds[0].get("next")
        if nxt is None:
            return {"verdict": "RESOLVED", "path": path}
        cur = nxt
    return {"verdict": "UNDECIDABLE_LIMIT", "path": path}

def naive_last_wins(start, defs, max_steps=16):
    nodes = {d["id"]: {"writer": "w1", "next": d.get("next")} for d in defs}
    r = v2.judge({"start": start, "writer": "w1", "nodes": nodes, "max_steps": max_steps})
    return "CYCLE_SELF" if r["verdict"] == "CONDITIONAL_CYCLE" and r.get("cycle_start_index") == r["hop"] - 1 else r["verdict"]

# ------------------------------------------------------- 4. evidence audit
UNITS, SCOPES, COLS = {"nodes", "edges", "ms"}, {"per_path", "shared_pool"}, ("walked_max_path_len", "visited_prefix_sha256", "budget")
HASH_DOMAIN = "ordered_path+prefix_len"

def ordered_hash(path, prefix_len):
    blob = json.dumps({"path": list(path), "prefix_len": prefix_len}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

def set_hash(path):
    return hashlib.sha256(json.dumps(sorted(set(path)), separators=(",", ":")).encode()).hexdigest()

def audit(ev):
    missing = [c for c in COLS if ev.get(c) is None]
    if ev.get("budget_unit") not in UNITS: missing.append("budget_unit")
    if ev.get("budget_scope") not in SCOPES: missing.append("budget_scope")
    uids = ev.get("run_uid") or {}
    present = {c: uids.get(c) for c in COLS if ev.get(c) is not None}
    if any(v is None for v in present.values()): missing.append("run_uid")
    distinct = {v for v in present.values() if v is not None}
    note = f"missing={missing}" if missing else ""
    if len(distinct) > 1:
        return {"evidence": "COLUMN_SOURCE_MISMATCH", "note": note or "all columns present"}
    if missing:
        return {"evidence": "NOT_EVALUABLE", "note": note}
    if ev.get("hash_domain") != HASH_DOMAIN:
        return {"evidence": "SEMANTIC_MISMATCH", "note": f"hash_domain={ev.get('hash_domain')}"}
    if ev.get("path") is not None and ordered_hash(ev["path"], ev["walked_max_path_len"]) != ev["visited_prefix_sha256"]:
        return {"evidence": "HASH_MISMATCH", "note": "recomputed ordered hash differs"}
    return {"evidence": "EVIDENCED", "note": ""}

def naive_audit(ev):  # "all three columns present -> fine"
    return "EVIDENCED" if all(ev.get(c) is not None for c in COLS) else "NOT_EVALUABLE"

# ------------------------------------------------------------------- rows
W = "w1"
X1_DEFS = [{"id": "a", "file": "f1", "next": "c"}, {"id": "c", "file": "f2", "next": "b"}, {"id": "b", "file": "f1", "next": "a"}]
X2_ROWS = {
    "X2a_self_single_file": ("A", [{"id": "A", "file": "f1", "next": "A"}], "CYCLE_SELF"),
    "X2b_dup_def_cycle": ("A", [{"id": "A", "file": "f1", "next": "A"}, {"id": "A", "file": "f2", "next": "A"}], "DUP_DEF_CYCLE"),
    "X2c_dup_def_back_edge_one_copy": ("A", [{"id": "A", "file": "f1", "next": "A"}, {"id": "A", "file": "f2", "next": None}], "DUP_DEF_CYCLE"),
    "X2c_rev_file_order": ("A", [{"id": "A", "file": "f2", "next": None}, {"id": "A", "file": "f1", "next": "A"}], "DUP_DEF_CYCLE"),
    "X2d_dup_def_no_back_edge": ("A", [{"id": "A", "file": "f1", "next": "B"}, {"id": "A", "file": "f2", "next": None}, {"id": "B", "file": "f1", "next": None}], "DUP_DEF_UNRESOLVED"),
}
P_ACB, P_ABC = ["a", "c", "b"], ["a", "b", "c"]
def ev(**kw):
    base = {"walked_max_path_len": 3, "visited_prefix_sha256": ordered_hash(P_ABC, 3), "budget": 3,
            "budget_unit": "nodes", "budget_scope": "per_path", "hash_domain": HASH_DOMAIN, "path": P_ABC,
            "run_uid": {c: "r1" for c in COLS}}
    base.update(kw); return base
EV_ROWS = {
    "E1_green_evidenced": (ev(), "EVIDENCED"),
    "E2_missing_hash": (ev(visited_prefix_sha256=None), "NOT_EVALUABLE"),
    "E3_missing_unit": (ev(budget_unit=None), "NOT_EVALUABLE"),
    "E4_bad_scope": (ev(budget_scope="global"), "NOT_EVALUABLE"),
    "E5_cross_run": (ev(run_uid={"walked_max_path_len": "r1", "visited_prefix_sha256": "r2", "budget": "r1"}), "COLUMN_SOURCE_MISMATCH"),
    "E6_cross_run_and_missing_unit": (ev(budget_unit=None, run_uid={"walked_max_path_len": "r1", "visited_prefix_sha256": "r2", "budget": "r1"}), "COLUMN_SOURCE_MISMATCH"),
    "E7_set_hash_domain": (ev(hash_domain="visited_set", visited_prefix_sha256=set_hash(P_ABC)), "SEMANTIC_MISMATCH"),
    "E8_hash_of_other_walk": (ev(visited_prefix_sha256=ordered_hash(P_ACB, 3)), "HASH_MISMATCH"),
    "E9_run_uid_absent": (ev(run_uid=None), "NOT_EVALUABLE"),
}

def main():
    checks, out = [], {"v0_2_rows": {}, "X1": {}, "X2": {}, "evidence": {}}
    # v0.2 rows: verdict unchanged (CYCLE_SELF refinement only when cycle length 1; none in v0.2)
    for k, (row, exp) in v2.ROWS.items():
        r = judge(row); out["v0_2_rows"][k] = r
        checks.append((f"V2_{k}", r["verdict"] == exp, f"{r['verdict']} (v0.2 expect {exp})"))
        checks.append((f"I1_{k}", invariant_masked(r), f"masked={r['masked']} status={r['check_status']}"))
    m1 = out["v0_2_rows"]["M1_writer_masks_cycle"]
    checks.append(("D3S_v03_M1_cycle_FAIL_MASKED", m1["check_status"]["CYCLE"] == "FAIL_MASKED", f"CYCLE={m1['check_status']['CYCLE']}"))
    v2m1 = v2.judge(v2.ROWS["M1_writer_masks_cycle"][0])
    checks.append(("D3S_must_fail_v02_violates_I1", not invariant_masked(v2m1), "v0.2 M1: masked=[CYCLE] while CYCLE=NOT_EVALUATED"))
    b2 = out["v0_2_rows"]["B2_cycle_past_budget"]
    checks.append(("D5_limit_cycle_still_NOT_EVALUATED", b2["check_status"]["CYCLE"] == "NOT_EVALUATED", "B2 unchanged"))
    # X1: canonical order independent of start
    naive_wrong = 0; snap = None
    for s in ("a", "c", "b"):
        r = judge_defs(s, X1_DEFS); out["X1"][s] = r
        nodes = {d["id"]: {"writer": W, "next": d["next"]} for d in X1_DEFS}
        obs = observed_cycle({"start": s, "nodes": nodes})
        if snap is None: snap = obs
        naive_wrong += obs != snap
        checks.append((f"X1_start_{s}_canonical", r.get("cycle_canonical") == ["a", "c", "b"] and r.get("cross_file") is True,
                       f"canonical={r.get('cycle_canonical')} files={r.get('cycle_files')} observed={obs}"))
    checks.append(("X1_must_fail_naive_snapshot", naive_wrong == 2, f"observed-order snapshot wrong on {naive_wrong}/3 starts"))
    rev = judge_defs("a", [{"id": "a", "file": "f1", "next": "b"}, {"id": "b", "file": "f1", "next": "c"}, {"id": "c", "file": "f2", "next": "a"}])
    checks.append(("X1R_reversed_direction_distinct", rev["cycle_canonical"] == ["a", "b", "c"], f"direction kept: {rev['cycle_canonical']} != [a,c,b]"))
    # X2: self vs dup-def
    nv = {}
    for k, (s, defs, exp) in X2_ROWS.items():
        r = judge_defs(s, defs); out["X2"][k] = r; nv[k] = naive_last_wins(s, defs)
        checks.append((k, r["verdict"] == exp, f"{r['verdict']} (expect {exp}); naive last-wins={nv[k]}"))
    checks.append(("X2_must_fail_naive_flips_with_file_order", nv["X2c_dup_def_back_edge_one_copy"] != nv["X2c_rev_file_order"],
                   f"naive {nv['X2c_dup_def_back_edge_one_copy']} vs {nv['X2c_rev_file_order']}; v0.3 both DUP_DEF_CYCLE"))
    sc = judge({"start": "A", "writer": W, "nodes": {"A": {"writer": W, "next": "A"}}})
    checks.append(("X2a_single_node_dict_path_CYCLE_SELF", sc["verdict"] == "CYCLE_SELF" and sc["cycle_canonical"] == ["A"], sc["verdict"]))
    # Evidence audit
    nw = 0
    for k, (e, exp) in EV_ROWS.items():
        r = audit(e); out["evidence"][k] = r
        nw += naive_audit(e) != exp
        checks.append((k, r["evidence"] == exp, f"{r['evidence']} (expect {exp}) {r['note']}"))
    checks.append(("E6_note_carries_missing", "budget_unit" in out["evidence"]["E6_cross_run_and_missing_unit"]["note"], out["evidence"]["E6_cross_run_and_missing_unit"]["note"]))
    checks.append(("E7_set_hash_collides", set_hash(P_ABC) == set_hash(P_ACB) and ordered_hash(P_ABC, 3) != ordered_hash(P_ACB, 3), "set-hash equal on two walks, ordered differs"))
    checks.append(("E_must_fail_naive_audit", nw == 7, f"naive 'three columns present' wrong {nw}/{len(EV_ROWS)}"))
    ok = 0
    for name, good, msg in checks:
        ok += good; print(("PASS " if good else "FAIL ") + name + ": " + msg)
    here = os.path.dirname(os.path.abspath(__file__))
    json.dump(out, open(os.path.join(here, "run_out_v0_3.json"), "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{len(checks)}")
    sys.exit(0 if ok == len(checks) else 1)

if __name__ == "__main__":
    main()
