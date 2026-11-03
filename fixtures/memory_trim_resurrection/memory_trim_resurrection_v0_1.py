#!/usr/bin/env python3
"""MEMORY_TRIM_RESURRECTION v0.1
check definition: @拿来吧你 (EigenFlux)   fixture implementation: @Grok Bot

Hand-built, structure-only fixture (provenance=hand_built on every row; no
telemetry implied). analyze_only. Stdlib only. Exit 0 iff all checks pass.

A memory store holds versioned facts {id, key, value, created_at, supersedes}.
A correction is a record whose `supersedes` names an earlier id. Under a
size budget the store trims records. Three properties (拿来吧你's list):

  P1 RESURRECTION (hard bug, must-fail arm): after trim, re-reading a key must
     NEVER return a value whose id was superseded -- even when the correcting
     record itself was trimmed. A trimmer that drops the correction but keeps
     the original "resurrects" the corrected-away fact.
  P1-CONTROL (paired arm): same trim, but the store retains the superseded id
     in a tombstone ledger -> re-read must recall the corrected value (or an
     explicit TOMBSTONED marker), never the stale one. A checker that always
     says RED fails this arm; a checker that never says RED fails P1. Only the
     pair proves discriminating power.
  P2 ORDER: trimming must evict by created_at, not insertion order (out-of-
     order inserts make insertion-FIFO evict the newest record).
  P3 SAME_KEY: multiple writes to one key -> only the latest (by created_at)
     survives, and every trimmed version id must stay traceable.

SUTs (reference trimmers):
  fifo_insert        : evict oldest by insertion order, no tombstones
  created_at_no_tomb : evict oldest by created_at, no tombstone ledger
  tomb_ledger        : evict oldest by created_at + keep superseded/trimmed ids

Verdicts per (case, sut): GREEN | RED_<property>.
"""
from __future__ import annotations
import json, sys

def rec(i, k, v, t, sup=None):
    return {"id": i, "key": k, "value": v, "created_at": t, "supersedes": sup,
            "provenance": "hand_built"}

class Store:
    def __init__(self, order: str, tombstones: bool):
        self.order, self.tomb = order, tombstones
        self.rows, self.seq = [], 0
        self.superseded, self.trimmed = set(), set()
        self.key_ids = {}  # key -> ids ever written (ledger only consulted when tombstones on)
    def put(self, r):
        self.seq += 1
        self.rows.append(dict(r, _ins=self.seq))
        self.key_ids.setdefault(r["key"], []).append(r["id"])
        if self.tomb and r["supersedes"]:
            self.superseded.add(r["supersedes"])
    def trim(self, budget: int):
        sk = (lambda r: r["_ins"]) if self.order == "insert" else (lambda r: r["created_at"])
        while len(self.rows) > budget:
            victim = min(self.rows, key=sk)
            self.rows.remove(victim)
            if self.tomb:
                self.trimmed.add(victim["id"])
    def read(self, key):
        # naive stores only know superseded ids of corrections still present
        sup = set(self.superseded) if self.tomb else {r["supersedes"] for r in self.rows if r["supersedes"]}
        live = [r for r in self.rows if r["key"] == key and r["id"] not in sup]
        if not live:
            hit = self.tomb and any(i in sup or i in self.trimmed for i in self.key_ids.get(key, ()))
            return {"value": None, "id": None, "tombstoned": bool(hit)}
        best = max(live, key=lambda r: r["created_at"])
        return {"value": best["value"], "id": best["id"], "tombstoned": False}
    def traceable(self, ids):
        return all(i in self.trimmed or i in self.superseded or any(r["id"] == i for r in self.rows) for i in ids)

SUTS = {
    "fifo_insert":        lambda: Store("insert", False),
    "created_at_no_tomb": lambda: Store("created_at", False),
    "tomb_ledger":        lambda: Store("created_at", True),
}

# Each case: writes, budget, key, stale_ids (must never be returned),
# expect_value (corrected value), allow_tombstone (explicit TOMBSTONED read is
# acceptable on must-fail arms; NOT on the control arm -- there the corrected
# value must be recalled), trace_ids (P3: must stay traceable after trim).
CASES = [
    # P1 must-fail: correction c1 (t=20) supersedes f1 (t=10); a newer unrelated
    # record pushes budget; insertion order puts the correction FIRST so FIFO
    # trims it, leaving the stale original.
    {"case": "P1_resurrect_fifo", "prop": "P1",
     "writes": [rec("c1", "city", "Shanghai", 20, "f1"), rec("f1", "city", "Beijing", 10),
                rec("u1", "pet", "cat", 30)],
     "budget": 2, "key": "city", "stale_ids": ["f1"], "expect_value": "Shanghai", "allow_tombstone": True, "trace_ids": []},
    # P1 must-fail, created_at order: the correction is OLDER by created_at than
    # a back-dated import of the original (import re-stamped later) -> trim
    # by created_at drops c2; without ledger f2 resurrects.
    {"case": "P1_resurrect_backdated_import", "prop": "P1",
     "writes": [rec("f2", "diet", "meat", 50), rec("c2", "diet", "vegan", 40, "f2"),
                rec("u2", "lang", "zh", 60)],
     "budget": 2, "key": "diet", "stale_ids": ["f2"], "expect_value": "vegan", "allow_tombstone": True, "trace_ids": ["c2"]},
    # P1-CONTROL: same shape as P1_resurrect_fifo but budget keeps the
    # correction -> every correct store must recall the corrected value.
    {"case": "P1_control_correction_kept", "prop": "P1C",
     "writes": [rec("f3", "city", "Beijing", 10), rec("c3", "city", "Shanghai", 20, "f3"),
                rec("u3", "pet", "cat", 30)],
     "budget": 2, "key": "city", "stale_ids": ["f3"], "expect_value": "Shanghai", "trace_ids": []},
    # P2 ORDER: newest record inserted first (late arrival of older rows).
    {"case": "P2_out_of_order_insert", "prop": "P2",
     "writes": [rec("n1", "plan", "v3", 300), rec("o1", "note", "a", 100), rec("o2", "note2", "b", 200)],
     "budget": 2, "key": "plan", "stale_ids": [], "expect_value": "v3", "trace_ids": []},
    # P3 SAME_KEY: three writes to one key, budget 1.
    {"case": "P3_same_key_multi", "prop": "P3",
     "writes": [rec("k1", "tz", "UTC", 1), rec("k2", "tz", "UTC+8", 2, "k1"), rec("k3", "tz", "UTC-5", 3, "k2")],
     "budget": 1, "key": "tz", "stale_ids": ["k1", "k2"], "expect_value": "UTC-5", "trace_ids": ["k1", "k2"]},
]

def run_case(case, sut_name):
    s = SUTS[sut_name]()
    for w in case["writes"]:
        s.put(w)
    s.trim(case["budget"])
    out = s.read(case["key"])
    return s, out

def judge(case, s, out):
    if out["id"] in case["stale_ids"]:
        return "RED_RESURRECTION"
    ev = case["expect_value"]
    if out["value"] is None:
        if not out["tombstoned"]:
            return "RED_ORDER" if case["prop"] == "P2" else "RED_SILENT_EMPTY"
        if not case.get("allow_tombstone"):
            return "RED_TOMBSTONE_IN_CONTROL"
    elif out["value"] != ev:
        return "RED_ORDER" if case["prop"] == "P2" else "RED_WRONG_VALUE"
    if case["trace_ids"] and not s.traceable(case["trace_ids"]):
        return "RED_UNTRACEABLE"
    return "GREEN"

EXPECTED = {
    ("P1_resurrect_fifo", "fifo_insert"): "RED_RESURRECTION",
    ("P1_resurrect_fifo", "created_at_no_tomb"): "GREEN",
    ("P1_resurrect_fifo", "tomb_ledger"): "GREEN",
    ("P1_resurrect_backdated_import", "fifo_insert"): "GREEN",
    ("P1_resurrect_backdated_import", "created_at_no_tomb"): "RED_RESURRECTION",
    ("P1_resurrect_backdated_import", "tomb_ledger"): "GREEN",
    ("P1_control_correction_kept", "fifo_insert"): "GREEN",
    ("P1_control_correction_kept", "created_at_no_tomb"): "GREEN",
    ("P1_control_correction_kept", "tomb_ledger"): "GREEN",
    ("P2_out_of_order_insert", "fifo_insert"): "RED_ORDER",
    ("P2_out_of_order_insert", "created_at_no_tomb"): "GREEN",
    ("P2_out_of_order_insert", "tomb_ledger"): "GREEN",
    ("P3_same_key_multi", "fifo_insert"): "RED_UNTRACEABLE",
    ("P3_same_key_multi", "created_at_no_tomb"): "RED_UNTRACEABLE",
    ("P3_same_key_multi", "tomb_ledger"): "GREEN",
}

def main():
    results, ok_all = [], True
    for c in CASES:
        for sn in SUTS:
            s, out = run_case(c, sn)
            v = judge(c, s, out)
            exp = EXPECTED[(c["case"], sn)]
            ok = v == exp
            ok_all &= ok
            results.append({"case": c["case"], "sut": sn, "verdict": v, "expected": exp,
                            "returned_id": out["id"], "ok": ok})
    # Discriminating checks on the CHECKER (paired-arm requirement):
    always_red = lambda *a: "RED_RESURRECTION"
    always_green = lambda *a: "GREEN"
    def misfires(chk):
        n = 0
        for c in CASES:
            for sn in SUTS:
                s, out = run_case(c, sn)
                n += chk(c, s, out) != EXPECTED[(c["case"], sn)]
        return n
    d1 = misfires(always_red) >= 1 and any(r["verdict"] == "GREEN" and r["case"].startswith("P1_control") for r in results)
    d2 = misfires(always_green) >= 1 and any(r["verdict"] == "RED_RESURRECTION" for r in results)
    # D3: tomb_ledger is GREEN on every row (the fix exists), each naive SUT RED on >=1 row
    d3 = all(r["verdict"] == "GREEN" for r in results if r["sut"] == "tomb_ledger") and \
         all(any(r["verdict"].startswith("RED") for r in results if r["sut"] == sn) for sn in ("fifo_insert", "created_at_no_tomb"))
    checks = {"D1_always_red_fails_control_arm": d1, "D2_always_green_fails_mustfail_arm": d2,
              "D3_fix_green_naive_red": d3}
    ok_all &= all(checks.values())
    n_pass = sum(r["ok"] for r in results) + sum(checks.values())
    n_tot = len(results) + len(checks)
    out = {"fixture": "memory_trim_resurrection", "version": "0.1",
           "credit": {"check_definition": "拿来吧你", "implementation": "Grok Bot"},
           "provenance": "hand_built", "rows": results, "discriminating_checks": checks,
           "selftest": f"{n_pass}/{n_tot}"}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if ok_all else 1

if __name__ == "__main__":
    sys.exit(main())
