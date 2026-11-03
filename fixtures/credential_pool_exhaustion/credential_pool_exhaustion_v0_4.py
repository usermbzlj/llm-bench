#!/usr/bin/env python3
"""CREDENTIAL_POOL_EXHAUSTION v0.4
v0.4 (both shapes credit @礼花, observed fixed-TTL config row @礼花):
  C9 REARM_RESET_HINT  when a re-probe fails AGAIN but this time the 402 carries
     reset_at, the new window must use reset_at, not the default TTL -- otherwise
     the gateway never learns the real recovery time (key_rearm_ignores_reset).
  C10 PROBE_BYPASS  a backoff cap longer than MAX_CAP is only admissible with an
     independent low-priority probe on a fixed interval that does not carry
     business traffic; long cap without it keeps a recovered pool locked
     (RED_LONG_CAP_NO_BYPASS). Short-cap gateways -> NOT_APPLICABLE (reported,
     counted in na_n, never folded into GREEN). C7 also admits cap>MAX_CAP iff a
     bypass probe exists.
  C10C control  the bypass probe itself must not hammer: probes per dead key
     <= span/PROBE_MIN_INTERVAL + 1 (RED_PROBE_HAMMER).
  C8 adds: long exponential cap without bypass -> RED_LONG_CAP_NO_BYPASS;
     observed row with unknown base TTL -> UNKNOWN_BASE (never CONFIG_OK).
v0.3: C6 ANCHOR (shape credit @青藤: re-armed window counted from the ORIGINAL
  expiry instead of the re-probe time -> with sparse traffic every new window is
  already expired, the dead key gets hammered each round while looking "retried");
  C7 RECOVERY_BOUND (backoff must be capped: uncapped exponential backoff keeps a
  recovered key dead far past recovery); C8 CONFIG_DECLARED (config row credit
  @MOSS, provenance=observed: backoff_kind=fixed, base_s=600, cap_s=600,
  rearm_on_fail=true). C5 check moved 140 -> 200 so capped exponential backoff
  (MAX_CAP=120 in fixture time) is admissible, not only fixed TTL.
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
  v0.4: key_rearm_ignores_reset (reset_at dropped on re-arm; only C9 catches it),
        key_longcap_no_bypass (cap 600 > MAX_CAP, no probe; C7+C10 RED),
        key_longcap_bypass (cap 600 + probe every 10; all GREEN),
        key_longcap_bypass_hammer (probe every 1; only C10C catches it)
"""
from __future__ import annotations
import json, sys

DEFAULT_TTL = 60
MAX_CAP = 120          # fixture-time cap policy; real deployments scale it
LONG_CAP = 600         # fixture-time long cap (needs a bypass probe)
PROBE_INTERVAL = 10    # bypass probe interval (fixture time)
PROBE_MIN_INTERVAL = 10
KEYS = ["a1", "a2", "a3"]

class Gateway:
    def __init__(self, kind):
        self.kind = kind
        self.dead_provider = False
        self.dead_until = {}          # key -> t (inf = forever)
        self.rr = 0
        self.log = []
        self.ttl_marked = set()       # keys currently dead via TTL (for probe_once)
        self.fails = {}               # key -> consecutive failures (backoff)
        self.cfg = {"key_breaker_ttl": ("fixed", DEFAULT_TTL, DEFAULT_TTL),
                    "key_backoff_capped": ("exponential", DEFAULT_TTL, MAX_CAP),
                    "key_backoff_uncapped": ("exponential", DEFAULT_TTL, None),
                    "key_rearm_stale_anchor": ("fixed", DEFAULT_TTL, DEFAULT_TTL),
                    "key_rearm_ignores_reset": ("fixed", DEFAULT_TTL, DEFAULT_TTL),
                    "key_longcap_no_bypass": ("exponential", DEFAULT_TTL, LONG_CAP),
                    "key_longcap_bypass": ("exponential", DEFAULT_TTL, LONG_CAP),
                    "key_longcap_bypass_hammer": ("exponential", DEFAULT_TTL, LONG_CAP)}.get(kind)
        self.probe_interval = {"key_longcap_bypass": PROBE_INTERVAL,
                               "key_longcap_bypass_hammer": 1}.get(kind)
        self.probes = []              # (t, key, status) -- never business traffic
    def effective_cap(self):
        if self.kind in ("provider_latch", "key_latch_no_ttl", "key_ttl_probe_once"):
            return float("inf")
        kind_, base, cap = self.cfg or ("fixed", DEFAULT_TTL, DEFAULT_TTL)
        return float("inf") if cap is None else cap
    def probe_tick(self, t, upstream):
        """Independent low-priority probe: only dead keys, no business traffic,
        success clears the window, failure leaves the backoff untouched."""
        for k in KEYS:
            du = self.dead_until.get(k, -1)
            if du > t and du != float("inf"):
                r = upstream(t, k); self.probes.append((t, k, r["status"]))
                if r["status"] == 200:
                    self.dead_until[k] = t; self.fails[k] = 0
    def _ttl(self, k):
        kind_, base, cap = self.cfg or ("fixed", DEFAULT_TTL, DEFAULT_TTL)
        if kind_ == "fixed":
            return base
        v = base * 2 ** (self.fails[k] - 1)
        return v if cap is None else min(v, cap)
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
                self.fails[k] = 0
                return {"t": t, "served_by": "A", "key": k, "tried": tried}
            if r["status"] in (402, 429):
                if self.kind == "provider_latch":
                    self.dead_provider = True
                elif self.kind == "key_latch_no_ttl":
                    self.dead_until[k] = float("inf")
                elif self.kind == "key_ttl_probe_once" and k in self.ttl_marked:
                    self.dead_until[k] = float("inf")   # gave up after one re-probe
                else:
                    self.fails[k] = self.fails.get(k, 0) + 1
                    ra = r.get("reset_at")
                    if self.kind == "key_rearm_ignores_reset" and k in self.ttl_marked:
                        ra = None                               # bug: hint ignored on re-arm
                    if ra is not None:
                        self.dead_until[k] = ra
                    elif self.kind == "key_rearm_stale_anchor" and k in self.ttl_marked:
                        self.dead_until[k] = self.dead_until[k] + self._ttl(k)  # anchored at old expiry (bug)
                    else:
                        self.dead_until[k] = t + self._ttl(k)
                    self.ttl_marked.add(k)
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
        [0, 1, 70, 200], {"served_at": {"200": "A"}}),
    # C5C control: same table, probe at t=110 is inside the re-armed TTL -> a1 untouched.
    row("C5C", "REARM", "control",
        {"a1": [(0, 1, 402, None), (70, 100, 402, None)],
         "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 70, 110], {"not_tried_at": {"110": "a1"}}),
    # C6 ANCHOR (v0.3, 青藤): a1 dead for a long time; sparse traffic re-probes at 170 and
    # fails. New window must start at 170 (-> >=230); anchoring at old expiry (60+60=120)
    # makes it already expired, so a1 is hammered again at 200.
    row("C6", "ANCHOR", "must_fail",
        {"a1": [(0, 500, 402, None)], "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 170, 200], {"not_tried_at": {"200": "a1"}}),
    # C7 RECOVERY_BOUND (v0.3): a1 fails at 0,70,200, upstream recovers at 340. Any backoff
    # with cap <= MAX_CAP re-probes by 350; uncapped doubling (window 240 at t=200) does not.
    row("C7", "RECOVERY_BOUND", "must_fail",
        {"a1": [(0, 340, 402, None)], "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 70, 200, 350], {"served_at": {"350": "A"}}),
    # C9 REARM_RESET_HINT (v0.4, 礼花): a1 402 no hint at 0; re-probe at 70 fails again but
    # now carries reset_at=80; upstream recovers at 80. Default TTL would hold a1 until 130.
    row("C9", "REARM_RESET_HINT", "must_fail",
        {"a1": [(0, 1, 402, None), (70, 80, 402, 80)],
         "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 70, 90], {"served_at": {"90": "A"}}),
    # C10 PROBE_BYPASS (v0.4, 礼花): a1 dead until 460; business is sparse. Gateways whose
    # effective cap > MAX_CAP must detect recovery via a bypass probe and serve A at 480.
    row("C10", "PROBE_BYPASS", "must_fail",
        {"a1": [(0, 460, 402, None)], "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 70, 200, 450, 480], {"served_at": {"480": "A"}, "applies_if_cap_gt": MAX_CAP}),
    # C10C control: the bypass probe must not hammer a dead key.
    row("C10C", "PROBE_BYPASS", "control",
        {"a1": [(0, 460, 402, None)], "a2": [(1, INF, 402, None)], "a3": [(1, INF, 402, None)]},
        [0, 1, 70, 200, 450, 480], {"max_probes_per_key_span": [0, 460]}),
    # C4: any B-serve must be logged with a reason.
    row("C4", "SILENT", "must_fail", {k: [(0, INF, 402, None)] for k in KEYS}, [0],
        {"fallback_logged": True}),
]

def run_trace(gw, up, times):
    trace = []
    ticks = list(range(0, max(times) + 1, gw.probe_interval)) if gw.probe_interval else []
    ev = sorted([(t, 0) for t in ticks] + [(t, 1) for t in times])
    for t, is_biz in ev:
        if is_biz:
            trace.append(gw.request(t, up))
        else:
            gw.probe_tick(t, up)
    return trace

def judge(case, gw_kind):
    gw = Gateway(gw_kind); up = up_factory(case["table"])
    e = case["expect"]
    if "applies_if_cap_gt" in e and gw.effective_cap() <= e["applies_if_cap_gt"]:
        return "NOT_APPLICABLE"
    trace = run_trace(gw, up, case["times"])
    if "max_probes_per_key_span" in e:
        a, b = e["max_probes_per_key_span"]
        lim = (b - a) // PROBE_MIN_INTERVAL + 1
        for k in KEYS:
            if sum(1 for (t, kk, _) in gw.probes if kk == k and a <= t < b) > lim:
                return "RED_PROBE_HAMMER"
        return "GREEN"
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
        # v0.4: a bypass probe that saw 200 for k before ts legitimately re-opens k
        if any(kk == k and st == 200 and tp <= int(ts) for (tp, kk, st) in gw.probes):
            continue
        if k in next(x for x in trace if x["t"] == int(ts))["tried"]:
            return "RED_HAMMER_STALE_ANCHOR" if case["property"] == "ANCHOR" else "RED_HAMMER"
    if e.get("fallback_logged") and any(x["t"] not in logged for x in b_serves):
        return "RED_SILENT_DEGRADE"
    return "GREEN"

def _red(case):
    return {"SCOPE": "RED_SCOPE", "TTL": "RED_NO_REPROBE", "RESET_HINT": "RED_RESET_IGNORED",
            "SILENT": "RED_SILENT_DEGRADE", "REARM": "RED_NO_REARM",
            "RECOVERY_BOUND": "RED_RECOVERY_LATE", "REARM_RESET_HINT": "RED_REARM_RESET_IGNORED",
            "PROBE_BYPASS": "RED_LONG_CAP_NO_BYPASS"}[case["property"]]

V04 = ("C9", "C10", "C10C")
_G = lambda: {c["case"]: "GREEN" for c in CASES}
_LATCH_V04 = {"C9": "RED_REARM_RESET_IGNORED", "C10": "RED_LONG_CAP_NO_BYPASS", "C10C": "GREEN"}
_SHORT_V04 = {"C9": "GREEN", "C10": "NOT_APPLICABLE", "C10C": "GREEN"}
EXPECTED = {
    "provider_latch":   {"C1": "RED_SCOPE", "C1C": "GREEN", "C2": "RED_NO_REPROBE", "C2C": "GREEN",
                         "C3": "RED_RESET_IGNORED", "C4": "RED_SILENT_DEGRADE",
                         "C5": "RED_NO_REARM", "C5C": "GREEN", "C6": "GREEN", "C7": "RED_RECOVERY_LATE",
                         **_LATCH_V04},
    "key_latch_no_ttl": {"C1": "GREEN", "C1C": "GREEN", "C2": "RED_NO_REPROBE", "C2C": "GREEN",
                         "C3": "RED_RESET_IGNORED", "C4": "GREEN",
                         "C5": "RED_NO_REARM", "C5C": "GREEN", "C6": "GREEN", "C7": "RED_RECOVERY_LATE",
                         **_LATCH_V04},
    "key_ttl_probe_once": {**_G(), "C5": "RED_NO_REARM", "C7": "RED_RECOVERY_LATE", **_LATCH_V04},
    "key_rearm_stale_anchor": {**_G(), "C6": "RED_HAMMER_STALE_ANCHOR", **_SHORT_V04},
    "key_backoff_uncapped": {**_G(), "C7": "RED_RECOVERY_LATE", "C10": "RED_LONG_CAP_NO_BYPASS"},
    "key_backoff_capped": {**_G(), **_SHORT_V04},
    "key_breaker_ttl":  {**_G(), **_SHORT_V04},
    # v0.4 reference gateways
    "key_rearm_ignores_reset": {**_G(), **_SHORT_V04, "C9": "RED_REARM_RESET_IGNORED"},
    "key_longcap_no_bypass": {**_G(), "C7": "RED_RECOVERY_LATE", "C10": "RED_LONG_CAP_NO_BYPASS"},
    "key_longcap_bypass": _G(),
    "key_longcap_bypass_hammer": {**_G(), "C10C": "RED_PROBE_HAMMER"},
}

def main():
    out, ok, n = {"fixture": "CREDENTIAL_POOL_EXHAUSTION", "version": "0.4", "max_cap_s": MAX_CAP,
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
    d3 = (all(v["verdict"] in ("GREEN", "NOT_APPLICABLE") for v in out["results"]["key_breaker_ttl"].values())
          and sum(v["verdict"] != "GREEN" for v in out["results"]["provider_latch"].values()) >= 4)
    for d in (d1, d2, d3):
        n += 1; ok += bool(d)
    d4 = (out["results"]["key_ttl_probe_once"]["C5"]["verdict"] == "RED_NO_REARM" and
          all(v["verdict"] == "GREEN" for c, v in out["results"]["key_ttl_probe_once"].items()
              if c in ("C1", "C1C", "C2", "C2C", "C3", "C4")))
    n += 1; ok += bool(d4)
    V03 = [c["case"] for c in CASES if c["case"] not in V04]
    d5 = all(out["results"][g][c]["verdict"] != "GREEN" and
             all(out["results"][g][cc]["verdict"] in ("GREEN", "NOT_APPLICABLE") for cc in V03 if cc != c)
             for g, c in (("key_rearm_stale_anchor", "C6"), ("key_backoff_uncapped", "C7")))
    n += 1; ok += bool(d5)
    # D6: each v0.4 bug gateway is caught ONLY by its new row (all v0.3 rows green/NA)
    d6 = (all(out["results"]["key_rearm_ignores_reset"][c]["verdict"] in ("GREEN", "NOT_APPLICABLE")
              for c in V03) and out["results"]["key_rearm_ignores_reset"]["C9"]["verdict"] != "GREEN"
          and all(out["results"]["key_longcap_bypass_hammer"][c]["verdict"] == "GREEN"
                  for c in out["results"]["key_longcap_bypass_hammer"] if c != "C10C"))
    n += 1; ok += bool(d6)
    # D7: NOT_APPLICABLE is reported, never folded into GREEN: na_n > 0 and green_n excludes it
    na_n = sum(v["verdict"] == "NOT_APPLICABLE" for g in out["results"].values() for v in g.values())
    green_n = sum(v["verdict"] == "GREEN" for g in out["results"].values() for v in g.values())
    d7 = na_n == 4 and green_n + na_n + sum(v["verdict"].startswith("RED") for g in out["results"].values()
                                            for v in g.values()) == len(EXPECTED) * len(CASES)
    n += 1; ok += bool(d7)
    out["counts"] = {"green_n": green_n, "not_applicable_n": na_n}
    # C8 CONFIG_DECLARED: declared backoff config rows (no trace); cap must be finite, rearm on fail
    cfg_rows = [
        {"src": "MOSS", "provenance": "observed", "backoff_kind": "fixed", "base_s": 600, "cap_s": 600,
         "rearm_on_fail": True, "expect": "CONFIG_OK"},
        {"src": "hand_built", "provenance": "hand_built", "backoff_kind": "exponential", "base_s": 60,
         "cap_s": None, "rearm_on_fail": True, "expect": "RED_NO_CAP"},
        {"src": "hand_built", "provenance": "hand_built", "backoff_kind": "fixed", "base_s": 60,
         "cap_s": 60, "rearm_on_fail": False, "expect": "RED_NO_REARM"},
        {"src": "hand_built", "provenance": "hand_built", "backoff_kind": "exponential", "base_s": 60,
         "cap_s": 30, "rearm_on_fail": True, "expect": "RED_CAP_BELOW_BASE"},
        # v0.4
        {"src": "礼花", "provenance": "observed", "backoff_kind": "fixed", "base_s": None, "cap_s": None,
         "rearm_on_fail": True, "expect": "UNKNOWN_BASE",
         "note": "fixed TTL, same TTL re-armed on fail, reset_at absent; magnitude not yet disclosed"},
        {"src": "hand_built", "provenance": "hand_built", "backoff_kind": "exponential", "base_s": 60,
         "cap_s": 3600, "rearm_on_fail": True, "bypass_probe_s": None, "expect": "RED_LONG_CAP_NO_BYPASS"},
        {"src": "hand_built", "provenance": "hand_built", "backoff_kind": "exponential", "base_s": 60,
         "cap_s": 3600, "rearm_on_fail": True, "bypass_probe_s": 60, "expect": "CONFIG_OK"},
    ]
    out["C8_config_declared"] = []
    for r in cfg_rows:
        v = ("UNKNOWN_BASE" if r["base_s"] is None
             else "RED_NO_CAP" if r["cap_s"] is None else "RED_NO_REARM" if not r["rearm_on_fail"]
             else "RED_CAP_BELOW_BASE" if r["cap_s"] < r["base_s"]
             # v0.4: cap >= 4x base needs an independent bypass probe (礼花)
             else "RED_LONG_CAP_NO_BYPASS" if (r["backoff_kind"] == "exponential" and
                                              r["cap_s"] >= 4 * r["base_s"] and not r.get("bypass_probe_s"))
             else "CONFIG_OK")
        n += 1; ok += v == r["expect"]
        out["C8_config_declared"].append({**{k: r[k] for k in r if k != "expect"}, "verdict": v, "expected": r["expect"]})
    out["discriminating"] = {"D6_v04_bugs_caught_only_by_new_rows": d6, "D7_not_applicable_reported_not_green": d7, "D5_new_gateways_caught_only_by_new_row": d5,"D4_v01_all_green_but_no_rearm_caught_only_by_C5": d4, "D1_always_red_fails_control": d1, "D2_always_green_misses_must_fail": d2,
                             "D3_fix_all_green_naive_red": d3}
    out["selftest"] = f"{ok}/{n}"
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if ok == n else 1

if __name__ == "__main__":
    sys.exit(main())
