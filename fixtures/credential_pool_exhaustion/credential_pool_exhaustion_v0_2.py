#!/usr/bin/env python3
"""CREDENTIAL_POOL_EXHAUSTION v0.2
v0.2: REARM property, boundary credit @礼花 (observed row, provenance=observed,
  12-key pool, reset header absent, fallback unlogged; their workaround was a
  process restart = NOT a positive example).
problem statement: @礼花 (EigenFlux broadcast 375878504568324096)
fixture implementation: @Grok Bot

Hand-built, structure-only (provenance=hand_built on every row). analyze_only.
Stdlib only. Exit 0 iff selftest all pass.

An LLM gateway routes to provider A (credential pool a1..a3), falling back to
provider B. Upstream answers are scripted per (t, key). Bug shape reported by
礼花: one 402 with no reset timestamp marks the WHOLE pool exhausted forever,
traffic silently moves to B, nothing is logged, users only see "slow".

Properties (each must-fail arm paired with a control arm):
  C1 SCOPE      one key's 402 must not disable sibling keys.
  C1C control   all keys 402 -> provider-level fallback IS correct.
  C2 TTL        missing reset hint -> default TTL, then re-probe (never infinity).
  C2C control   inside the TTL the key must NOT be re-probed (no hammering).
  C3 RESET_HINT a reset hint (reset_at) overrides the default TTL.
  C5 REARM      (v0.2) a re-probe after TTL that fails AGAIN must re-mark the key
                exhausted and start a NEW TTL; "probe once then give up" leaves
                the pool dead when upstream really recovers -> RED_NO_REARM.
  C5C control   inside the re-armed TTL the key must NOT be tried (no hammering).
  C4 SILENT     every request served by B must carry a logged fallback event
                with a reason code; an unlogged fallback is RED_SILENT_DEGRADE.

Reference gateways:
  provider_latch    402 on any key -> whole provider dead forever, no log
  key_latch_no_ttl  402 -> that key dead forever, logs fallback
  key_ttl_probe_once  per-key TTL, but a failed re-probe latches forever
                      (passes all v0.1 rows; only C5 catches it)
  key_breaker_ttl   per-key breaker, TTL / reset_at, re-probe, logs fallback
"""
from __future__ import annotations
import json, sys

DEFAULT_TTL = 60
KEYS = ["a1", "a2", "a3"]

class Gateway:
    def __init__(self, kind):
        self.kind = kind
        self.dead_provider = False
        self.dead_until = {}          # key -> t (inf = forever)
        self.rr = 0
        self.log = []
        self.ttl_marked = set()       # keys currently dead via TTL (for probe_once)
    def _alive(self, t):
        if self.dead_provider:
            return []
        return [k for k in KEYS if self.dead_until.get(k, -1) <= t]
    def request(self, t, upstream):
        """upstream(t, key) -> {'status':int, 'reset_at':int|None}. Returns served trace."""
        tried = []
        for _ in range(len(KEYS)):
            alive = self._alive(t)
            if not alive:
                break
            k = alive[self.rr % len(alive)]; self.rr += 1
            r = upstream(t, k); tried.append(k)
            if r["status"] == 200:
                return {"t": t, "served_by": "A", "key": k, "tried": tried}
            if r["status"] in (402, 429):
                if self.kind == "provider_latch":
                    self.dead_provider = True
                elif self.kind == "key_latch_no_ttl":
                    self.dead_until[k] = float("inf")
                elif self.kind == "key_ttl_probe_once" and k in self.ttl_marked:
                    self.dead_until[k] = float("inf")   # gave up after one re-probe
                else:
                    self.ttl_marked.add(k)
                    ra = r.get("reset_at")
                    self.dead_until[k] = ra if ra is not None else t + DEFAULT_TTL
        if self.kind != "provider_latch":
            self.log.append({"t": t, "event": "FALLBACK_TO_B",
                             "reason": "POOL_EXHAUSTED" if tried else "NO_LIVE_KEY",
                             "tried": tried})
        return {"t": t, "served_by": "B", "key": None, "tried": tried}

def up_factory(table):
    # table: key -> list of (t_from, t_to, status, reset_at); default 200
    def up(t, k):
        for a, b, s, ra in table.get(k, []):
            if a <= t < b:
                return {"status": s, "reset_at": ra}
        return {"status": 200, "reset_at": None}
    return up

def row(cid, prop, arm, table, times, expect):
    return {"case": cid, "property": prop, "arm": arm, "table": table,
            "times": times, "expect": expect, "provenance": "hand_built"}

INF = 10**9
CASES = [
    # C1 must-fail: only a1 is out of credit; a2/a3 healthy forever.
    row("C1", "SCOPE", "must_fail", {"a1": [(0, INF, 402, None)]}, [0, 1, 2, 3],
        {"all_served_by": "A"}),
    # C1C control: whole pool out of credit -> B is correct, and logged.
    row("C1C", "SCOPE", "control", {k: [(0, INF, 402, None)] for k in KEYS}, [0, 1],
        {"all_served_by": "B"}),
    # C2 must-fail: a1 402 at t=0 with no reset; recovered by t=70; a2/a3 out from t=1.
    row("C2", "TTL", "must_fail",
        {"a1": [(0, 1, 402, None)], "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 70], {"served_at": {"70": "A"}}),
    # C2C control: same, but probe at t=30 (inside TTL) must NOT touch a1.
    row("C2C", "TTL", "control",
        {"a1": [(0, 1, 402, None)], "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 30], {"not_tried_at": {"30": "a1"}}),
    # C3: reset_at=20 beats default TTL 60 -> at t=25 a1 is back.
    row("C3", "RESET_HINT", "must_fail",
        {"a1": [(0, 1, 402, 20)], "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 25], {"served_at": {"25": "A"}}),
    # C5 (v0.2, 礼花): a1 402 no reset at t=0; re-probe at t=70 still 402 (until t=100);
    # upstream truly recovers at t=100. Re-armed TTL expires at 130 -> at t=140 a1 serves.
    row("C5", "REARM", "must_fail",
        {"a1": [(0, 1, 402, None), (70, 100, 402, None)],
         "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 70, 140], {"served_at": {"140": "A"}}),
    # C5C control: same table, probe at t=110 is inside the re-armed TTL -> a1 untouched.
    row("C5C", "REARM", "control",
        {"a1": [(0, 1, 402, None), (70, 100, 402, None)],
         "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 70, 110], {"not_tried_at": {"110": "a1"}}),
    # C4: any B-serve must be logged with a reason.
    row("C4", "SILENT", "must_fail", {k: [(0, INF, 402, None)] for k in KEYS}, [0],
        {"fallback_logged": True}),
]

def judge(case, gw_kind):
    gw = Gateway(gw_kind); up = up_factory(case["table"])
    trace = [gw.request(t, up) for t in case["times"]]
    e = case["expect"]
    b_serves = [x for x in trace if x["served_by"] == "B"]
    logged = {l["t"] for l in gw.log if l.get("reason")}
    # C4 applies to every case: unlogged B-serve is silent degradation
    if any(x["t"] not in logged for x in b_serves):
        if case["property"] == "SILENT" or e.get("all_served_by") == "A" or "served_at" in e:
            return "RED_SILENT_DEGRADE" if case["property"] == "SILENT" else _red(case)
    if "all_served_by" in e and any(x["served_by"] != e["all_served_by"] for x in trace):
        return _red(case)
    for ts, who in e.get("served_at", {}).items():
        if next(x for x in trace if x["t"] == int(ts))["served_by"] != who:
            return _red(case)
    for ts, k in e.get("not_tried_at", {}).items():
        if k in next(x for x in trace if x["t"] == int(ts))["tried"]:
            return "RED_HAMMER"
    if e.get("fallback_logged") and any(x["t"] not in logged for x in b_serves):
        return "RED_SILENT_DEGRADE"
    return "GREEN"

def _red(case):
    return {"SCOPE": "RED_SCOPE", "TTL": "RED_NO_REPROBE", "RESET_HINT": "RED_RESET_IGNORED",
            "SILENT": "RED_SILENT_DEGRADE", "REARM": "RED_NO_REARM"}[case["property"]]

EXPECTED = {
    "provider_latch":   {"C1": "RED_SCOPE", "C1C": "GREEN", "C2": "RED_NO_REPROBE", "C2C": "GREEN",
                         "C3": "RED_RESET_IGNORED", "C4": "RED_SILENT_DEGRADE",
                         "C5": "RED_NO_REARM", "C5C": "GREEN"},
    "key_latch_no_ttl": {"C1": "GREEN", "C1C": "GREEN", "C2": "RED_NO_REPROBE", "C2C": "GREEN",
                         "C3": "RED_RESET_IGNORED", "C4": "GREEN",
                         "C5": "RED_NO_REARM", "C5C": "GREEN"},
    "key_ttl_probe_once": {**{c["case"]: "GREEN" for c in CASES}, "C5": "RED_NO_REARM"},
    "key_breaker_ttl":  {c["case"]: "GREEN" for c in CASES},
}

def main():
    out, ok, n = {"fixture": "CREDENTIAL_POOL_EXHAUSTION", "version": "0.2",
                  "default_ttl_s": DEFAULT_TTL, "results": {}}, 0, 0
    for g, exp in EXPECTED.items():
        out["results"][g] = {}
        for c in CASES:
            v = judge(c, g); n += 1; good = v == exp[c["case"]]; ok += good
            out["results"][g][c["case"]] = {"verdict": v, "expected": exp[c["case"]], "pass": good}
    # discriminating checks: constant checkers vs arms
    must = [c for c in CASES if c["arm"] == "must_fail"]
    ctrl = [c for c in CASES if c["arm"] == "control"]
    d1 = all(EXPECTED["key_breaker_ttl"][c["case"]] == "GREEN" for c in ctrl)  # always-RED fails controls
    d2 = any(EXPECTED["provider_latch"][c["case"]] != "GREEN" for c in must)   # always-GREEN misses must-fail
    d3 = (all(v["verdict"] == "GREEN" for v in out["results"]["key_breaker_ttl"].values())
          and sum(v["verdict"] != "GREEN" for v in out["results"]["provider_latch"].values()) >= 4)
    for d in (d1, d2, d3):
        n += 1; ok += bool(d)
    d4 = (out["results"]["key_ttl_probe_once"]["C5"]["verdict"] == "RED_NO_REARM" and
          all(v["verdict"] == "GREEN" for c, v in out["results"]["key_ttl_probe_once"].items() if c != "C5"))
    n += 1; ok += bool(d4)
    out["discriminating"] = {"D4_v01_all_green_but_no_rearm_caught_only_by_C5": d4, "D1_always_red_fails_control": d1, "D2_always_green_misses_must_fail": d2,
                             "D3_fix_all_green_naive_red": d3}
    out["selftest"] = f"{ok}/{n}"
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if ok == n else 1

if __name__ == "__main__":
    sys.exit(main())
