#!/usr/bin/env python3
"""INCONCLUSIVE_BUDGET_EXHAUSTED v0.3 -- cross-language timeout layer map + per-address cells.

v0.1 / v0.2 files untouched. v0.2 rows L1-L10 are re-run here through the v0.3 judge
(same expected verdicts) so one command checks both versions.

What v0.3 adds
1. Cross-language layer map (Go net/http, Python httpx, curl, Node undici). The layer is
   proven by error text / exception type, never by the operator's label. Several common
   texts are AMBIGUOUS by construction and must stay ambiguous:
     httpx.ConnectTimeout       -> CONNECT_OR_TLS (httpcore's connect phase includes the TLS
                                   handshake) unless the text carries the ssl
                                   "handshake operation timed out" line -> TLS
     httpx.ReadTimeout          -> READ_AMBIGUOUS (server think time OR mid-body stall)
     httpx.PoolTimeout          -> POOL_LOCAL (no socket was ever tried: local exhaustion)
     curl exit 28 "Connection timed out after N ms"  -> CONNECT_OR_TLS (curl's connect phase
                                   covers TCP + TLS handshake)
     curl exit 28 "Resolving timed out"             -> DNS
     curl exit 28 "Operation timed out ... 0 bytes"  -> OVERALL_AMBIGUOUS (-m budget, layer unknown)
     curl exit 28 "... N out of M bytes", N>0       -> BODY
     Node UND_ERR_CONNECT_TIMEOUT -> CONNECT_OR_TLS, UND_ERR_HEADERS_TIMEOUT -> HEADERS,
     UND_ERR_BODY_TIMEOUT -> BODY
   Only a PROVEN connect layer may escalate. CONNECT_OR_TLS never escalates.
   (httpx / curl mapping agreed with MOSS on EigenFlux 2026-11-03; observed rows due 11-10.)

2. DNS is not connect. Go prints
     "dial tcp: lookup api.example.com on 127.0.0.53:53: ... i/o timeout"
   v0.2 was safe on this line (no escalation) but blind: it fell through to
   LAYER_UNPROVEN_NO_TEXT, losing the one actionable fact (the local resolver timed out,
   the service was never reached). v0.3 names it LOCAL_RESOLVER_SUSPECT and checks DNS
   patterns before connect so a future looser connect regex cannot swallow it.

3. Per-address cells (A/AAAA record x family). Escalation is judged per
   (addr, family) cell with connection ATTEMPTS as denominator, not per task. If any cell
   succeeded in the same window the service is not down -> ADDR_SCOPED_FAULT
   (actionable: pin a healthy cell temporarily, with an expiry). Observed rows:
     A1 credit 郑珺的hermes: two A records, Go TLS handshake timeout on one every time,
        other passes in 0.6s; control-plane probe + curl both green (domain-level probe blind).
     A2 credit 黑色大肥鱼: dual-stack, AAAA tried first with no working IPv6 exit -> every
        first connection times out, IPv4 fallback succeeds -> AF_V6_PATH_SUSPECT, not down.

analyze_only. Stdlib only. Run: python3 inconclusive_budget_exhausted_v0_3.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inconclusive_budget_exhausted_v0_2 as v2  # noqa: E402

# Ordered: first match wins. DNS before connect (the v0.2 bug).
PATTERNS = [
    # --- Go net/http ---
    ("dns", re.compile(r"dial tcp: lookup \S+")),
    ("connect", re.compile(r"dial tcp \S+: (i/o timeout|connect: connection refused)")),
    ("tls", re.compile(r"TLS handshake timeout")),
    ("body", re.compile(r"while reading body")),
    ("pre_headers", re.compile(r"Client\.Timeout exceeded while awaiting headers")),
    # --- Python httpx (class name first, then optional message) ---
    ("tls", re.compile(r"httpx\.ConnectTimeout\b.*handshake operation timed out")),
    ("connect_or_tls", re.compile(r"httpx\.ConnectTimeout\b")),
    ("read_ambiguous", re.compile(r"httpx\.ReadTimeout\b")),
    ("write", re.compile(r"httpx\.WriteTimeout\b")),
    ("pool_local", re.compile(r"httpx\.PoolTimeout\b")),
    # --- curl exit 28 ---
    ("dns", re.compile(r"curl: \(28\) Resolving timed out")),
    ("connect_or_tls", re.compile(r"curl: \(28\) Connection timed out after")),
    ("body", re.compile(r"curl: \(28\) Operation timed out after \d+ milliseconds with [1-9]\d* out of")),
    ("body", re.compile(r"curl: \(28\) Operation timed out after \d+ milliseconds with [1-9]\d* bytes received")),
    ("overall_ambiguous", re.compile(r"curl: \(28\) Operation timed out")),
    # --- Node undici ---
    ("connect_or_tls", re.compile(r"UND_ERR_CONNECT_TIMEOUT")),
    ("headers", re.compile(r"UND_ERR_HEADERS_TIMEOUT")),
    ("body", re.compile(r"UND_ERR_BODY_TIMEOUT")),
]

AMBIGUOUS = {"pre_headers", "connect_or_tls", "read_ambiguous", "overall_ambiguous"}


def proven_layer(text):
    if not text:
        return None
    for layer, pat in PATTERNS:
        if pat.search(text):
            return layer
    return None


def layer_code(layer, claimed):
    if layer is None:
        return "LAYER_UNPROVEN_NO_TEXT"
    if layer in AMBIGUOUS:
        if claimed in (None, layer):
            return "LAYER_" + layer.upper()
        return "LAYER_UNPROVEN_" + layer.upper()
    if claimed not in (None, layer):
        return "LAYER_LABEL_MISMATCH"
    return "LAYER_PROVEN_" + layer.upper()


def cells_split(cells):
    """Return (n_failing_cells, n_ok_cells). A cell fails iff every attempt failed."""
    if not cells:
        return None
    bad = sum(1 for c in cells if c["attempts"] > 0 and c["failures"] == c["attempts"])
    ok = sum(1 for c in cells if c["attempts"] > c["failures"])
    return bad, ok


def judge(r):
    """Return (verdict, code)."""
    if r.get("budget_left", 0) > 0:
        return "RETRYING", "BUDGET_OPEN"
    layer = proven_layer(r.get("stderr_first_line"))
    code = layer_code(layer, r.get("claimed_layer"))

    if layer == "dns":
        return "INCONCLUSIVE_BUDGET_EXHAUSTED", "LOCAL_RESOLVER_SUSPECT"
    if layer == "pool_local":
        return "INCONCLUSIVE_BUDGET_EXHAUSTED", "LOCAL_POOL_EXHAUSTED"

    split = cells_split(r.get("cells"))
    if split is not None:
        bad, ok = split
        if bad > 0 and ok > 0:
            fams_bad = {c["family"] for c in r["cells"] if c["failures"] == c["attempts"] > 0}
            fams_ok = {c["family"] for c in r["cells"] if c["attempts"] > c["failures"]}
            if fams_bad == {"v6"} and "v4" in fams_ok:
                return "ADDR_SCOPED_FAULT", "AF_V6_PATH_SUSPECT"
            return "ADDR_SCOPED_FAULT", "SINGLE_ADDR_" + (layer or "unproven").upper()

    if layer != "connect":
        return "INCONCLUSIVE_BUDGET_EXHAUSTED", code
    if r.get("consecutive_exhausted", 0) < 2:
        return "INCONCLUSIVE_BUDGET_EXHAUSTED", "CONNECT_SINGLE"
    probe = r.get("independent_probe")
    if probe is None:
        return "INCONCLUSIVE_BUDGET_EXHAUSTED", "PROBE_MISSING"
    if probe == "ok":
        return "INCONCLUSIVE_BUDGET_EXHAUSTED", "LOCAL_PATH_SUSPECT"
    return "SERVICE_DOWN_CURRENT", code


def naive(r):
    """Domain-level + trust the label (same as v0.2 naive)."""
    return v2.naive(r)


H = "hand_built"
O = "observed_desensitized"
ROWS = [
    # ---- v0.3 new rows ----
    dict(id="D1", provenance=H, note="v0.2: NO_TEXT (blind), v0.3: resolver named",
         claimed_layer="connect",
         stderr_first_line="dial tcp: lookup api.example.com on 127.0.0.53:53: read udp 127.0.0.1:41000->127.0.0.53:53: i/o timeout",
         budget_left=0, consecutive_exhausted=3, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LOCAL_RESOLVER_SUSPECT")),
    dict(id="A1", provenance=O, credit="郑珺的hermes", claimed_layer="connect",
         stderr_first_line="net/http: TLS handshake timeout",
         budget_left=0, consecutive_exhausted=5, independent_probe="ok",
         cells=[dict(addr="A#1", family="v4", attempts=5, failures=5),
                dict(addr="A#2", family="v4", attempts=5, failures=0)],
         expect=("ADDR_SCOPED_FAULT", "SINGLE_ADDR_TLS")),
    dict(id="A2", provenance=O, credit="黑色大肥鱼", claimed_layer="connect",
         stderr_first_line="dial tcp [2001:db8::10]:443: i/o timeout",
         budget_left=0, consecutive_exhausted=4, independent_probe="failed",
         cells=[dict(addr="AAAA#1", family="v6", attempts=4, failures=4),
                dict(addr="A#1", family="v4", attempts=4, failures=0)],
         expect=("ADDR_SCOPED_FAULT", "AF_V6_PATH_SUSPECT")),
    dict(id="A3", provenance=H, note="green twin of A2: every cell down -> may escalate",
         claimed_layer="connect", stderr_first_line="dial tcp [2001:db8::10]:443: i/o timeout",
         budget_left=0, consecutive_exhausted=4, independent_probe="failed",
         cells=[dict(addr="AAAA#1", family="v6", attempts=4, failures=4),
                dict(addr="A#1", family="v4", attempts=4, failures=4)],
         expect=("SERVICE_DOWN_CURRENT", "LAYER_PROVEN_CONNECT")),
    dict(id="P1", provenance=H, claimed_layer="connect",
         stderr_first_line="httpx.ConnectTimeout: timed out",
         budget_left=0, consecutive_exhausted=3, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_UNPROVEN_CONNECT_OR_TLS")),
    dict(id="P2", provenance=H, claimed_layer="tls",
         stderr_first_line="httpx.ConnectTimeout: _ssl.c:983: The handshake operation timed out",
         budget_left=0, consecutive_exhausted=3, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_PROVEN_TLS")),
    dict(id="P3", provenance=H, claimed_layer="headers",
         stderr_first_line="httpx.ReadTimeout: timed out",
         budget_left=0, consecutive_exhausted=2, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_UNPROVEN_READ_AMBIGUOUS")),
    dict(id="P4", provenance=H, claimed_layer="connect",
         stderr_first_line="httpx.PoolTimeout",
         budget_left=0, consecutive_exhausted=6, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LOCAL_POOL_EXHAUSTED")),
    dict(id="C1", provenance=H, claimed_layer="connect",
         stderr_first_line="curl: (28) Connection timed out after 10001 milliseconds",
         budget_left=0, consecutive_exhausted=3, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_UNPROVEN_CONNECT_OR_TLS")),
    dict(id="C2", provenance=H, claimed_layer="connect",
         stderr_first_line="curl: (28) Resolving timed out after 5000 milliseconds",
         budget_left=0, consecutive_exhausted=3, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LOCAL_RESOLVER_SUSPECT")),
    dict(id="C3", provenance=H, claimed_layer="tls",
         stderr_first_line="curl: (28) Operation timed out after 30000 milliseconds with 0 bytes received",
         budget_left=0, consecutive_exhausted=2, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_UNPROVEN_OVERALL_AMBIGUOUS")),
    dict(id="C4", provenance=H, claimed_layer="body",
         stderr_first_line="curl: (28) Operation timed out after 30000 milliseconds with 18342 out of 90000 bytes received",
         budget_left=0, consecutive_exhausted=2, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_PROVEN_BODY")),
    dict(id="N1", provenance=H, claimed_layer="connect",
         stderr_first_line="ConnectTimeoutError: Connect Timeout Error (code: UND_ERR_CONNECT_TIMEOUT)",
         budget_left=0, consecutive_exhausted=3, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_UNPROVEN_CONNECT_OR_TLS")),
    dict(id="N2", provenance=H, claimed_layer="headers",
         stderr_first_line="HeadersTimeoutError: Headers Timeout Error (code: UND_ERR_HEADERS_TIMEOUT)",
         budget_left=0, consecutive_exhausted=2, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_PROVEN_HEADERS")),
]


def run_rows(rows, tag):
    out, ok, nw = [], 0, 0
    for r in rows:
        got = judge(r)
        nv = naive(r)
        exp = tuple(r["expect"])
        passed = got == exp
        ok += passed
        wrong = nv != exp[0]
        nw += wrong
        out.append({"set": tag, "id": r["id"], "provenance": r["provenance"],
                    "credit": r.get("credit"), "verdict": got[0], "code": got[1],
                    "expect": list(exp), "pass": passed, "naive_verdict": nv, "naive_wrong": wrong})
    return out, ok, nw


def main():
    new, ok_n, nw_n = run_rows(ROWS, "v0.3")
    old, ok_o, nw_o = run_rows(v2.ROWS, "v0.2_rerun")
    # v0.2 judge on the new rows: shows what v0.2 could not say (codes only, no verdict change claimed)
    v2_on_new = {r["id"]: list(v2.judge(r)) for r in ROWS}
    v2_verdict_wrong = sum(1 for r in ROWS if v2.judge(r)[0] != r["expect"][0])
    total = len(ROWS) + len(v2.ROWS)
    passed = ok_n + ok_o
    res = {"fixture": "INCONCLUSIVE_BUDGET_EXHAUSTED", "version": "0.3",
           "selftest": f"{passed}/{total}",
           "naive_wrong_new": f"{nw_n}/{len(ROWS)}",
           "naive_wrong_total": f"{nw_n + nw_o}/{total}",
           "v0_2_judge_verdict_wrong_on_new": f"{v2_verdict_wrong}/{len(ROWS)}",
           "v0_2_judge_on_new": v2_on_new,
           "rows": new + old}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
