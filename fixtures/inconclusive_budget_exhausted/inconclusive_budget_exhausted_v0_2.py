#!/usr/bin/env python3
"""INCONCLUSIVE_BUDGET_EXHAUSTED v0.2 -- timeout LAYER must be proven, not claimed.

v0.1 (unchanged) covers budget-exhaust vs permanent. v0.2 adds the escalation
convention agreed with MOSS (EigenFlux, 2026-11-03):

  * Only CONNECT-layer exhaustion, repeated (>=2 consecutive) AND confirmed by an
    independent probe that also fails, may escalate to SERVICE_DOWN_CURRENT.
  * TLS / headers / body layer exhaustion never escalates -> INCONCLUSIVE.
  * The layer must be PROVEN by the error text, not by the operator's label.

Key observation (first observed row, credit MOSS): Go's
  "Client.Timeout exceeded while awaiting headers"
is emitted whenever the client deadline fires before response headers arrive.
That span covers dial + TLS handshake + request write + server think time, so the
line does NOT pin the TLS layer. Claimed layer=tls from that line -> LAYER_UNPROVEN
(verdict still INCONCLUSIVE, which is what MOSS's row correctly reported).
Layer-pinning texts used here (Go net/http):
  connect : "dial tcp ...: i/o timeout" / "connect: connection refused"
  tls     : "net/http: TLS handshake timeout"
  body    : "Client.Timeout or context cancellation while reading body"
  pre_headers (ambiguous): "Client.Timeout exceeded while awaiting headers"

analyze_only. Stdlib only. observed row = contributor-supplied, desensitized.
"""
from __future__ import annotations

import json
import re
import sys

PATTERNS = [
    ("connect", re.compile(r"dial tcp .*(i/o timeout|connection refused)")),
    ("tls", re.compile(r"TLS handshake timeout")),
    ("body", re.compile(r"while reading body")),
    ("pre_headers", re.compile(r"Client\.Timeout exceeded while awaiting headers")),
]


def proven_layer(stderr_first_line):
    if not stderr_first_line:
        return None
    for layer, pat in PATTERNS:
        if pat.search(stderr_first_line):
            return layer
    return None


def judge(r):
    """Return (verdict, layer_code)."""
    if r.get("budget_left", 0) > 0:
        return "RETRYING", "BUDGET_OPEN"
    layer = proven_layer(r.get("stderr_first_line"))
    claimed = r.get("claimed_layer")
    if layer is None:
        layer_code = "LAYER_UNPROVEN_NO_TEXT"
    elif layer == "pre_headers":
        layer_code = "LAYER_UNPROVEN_PRE_HEADERS" if claimed not in (None, "pre_headers") else "LAYER_PRE_HEADERS"
    elif claimed not in (None, layer):
        layer_code = "LAYER_LABEL_MISMATCH"
    else:
        layer_code = "LAYER_PROVEN_" + layer.upper()

    if layer != "connect":
        return "INCONCLUSIVE_BUDGET_EXHAUSTED", layer_code
    if r.get("consecutive_exhausted", 0) < 2:
        return "INCONCLUSIVE_BUDGET_EXHAUSTED", "CONNECT_SINGLE"
    probe = r.get("independent_probe")  # None | "failed" | "ok"
    if probe is None:
        return "INCONCLUSIVE_BUDGET_EXHAUSTED", "PROBE_MISSING"
    if probe == "ok":
        return "INCONCLUSIVE_BUDGET_EXHAUSTED", "LOCAL_PATH_SUSPECT"
    return "SERVICE_DOWN_CURRENT", layer_code


def naive(r):
    """Trust the label: connect|tls exhausted twice -> DOWN, else INCONCLUSIVE."""
    if r.get("budget_left", 0) > 0:
        return "RETRYING"
    if r.get("claimed_layer") in ("connect", "tls") and r.get("consecutive_exhausted", 0) >= 2:
        return "SERVICE_DOWN_CURRENT"
    return "INCONCLUSIVE_BUDGET_EXHAUSTED"


ROWS = [
    dict(id="L1", provenance="observed_desensitized", credit="MOSS",
         claimed_layer="tls", stderr_first_line="Client.Timeout exceeded while awaiting headers",
         budget_left=0, consecutive_exhausted=2, independent_probe=None,
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_UNPROVEN_PRE_HEADERS")),
    dict(id="L2", provenance="hand_built", claimed_layer="connect",
         stderr_first_line="dial tcp 203.0.113.7:443: i/o timeout",
         budget_left=0, consecutive_exhausted=3, independent_probe="failed",
         expect=("SERVICE_DOWN_CURRENT", "LAYER_PROVEN_CONNECT")),
    dict(id="L3", provenance="hand_built", claimed_layer="connect",
         stderr_first_line="dial tcp 203.0.113.7:443: i/o timeout",
         budget_left=0, consecutive_exhausted=3, independent_probe=None,
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "PROBE_MISSING")),
    dict(id="L4", provenance="hand_built", claimed_layer="connect",
         stderr_first_line="dial tcp 203.0.113.7:443: connect: connection refused",
         budget_left=0, consecutive_exhausted=3, independent_probe="ok",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LOCAL_PATH_SUSPECT")),
    dict(id="L5", provenance="hand_built", claimed_layer="tls",
         stderr_first_line="net/http: TLS handshake timeout",
         budget_left=0, consecutive_exhausted=4, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_PROVEN_TLS")),
    dict(id="L6", provenance="hand_built", claimed_layer="connect",
         stderr_first_line="Client.Timeout exceeded while awaiting headers",
         budget_left=0, consecutive_exhausted=3, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_UNPROVEN_PRE_HEADERS")),
    dict(id="L7", provenance="hand_built", claimed_layer="connect", stderr_first_line=None,
         budget_left=0, consecutive_exhausted=3, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_UNPROVEN_NO_TEXT")),
    dict(id="L8", provenance="hand_built", claimed_layer="tls",
         stderr_first_line="dial tcp 203.0.113.7:443: i/o timeout",
         budget_left=0, consecutive_exhausted=1, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "CONNECT_SINGLE")),
    dict(id="L9", provenance="hand_built", claimed_layer="body",
         stderr_first_line="context deadline exceeded (Client.Timeout or context cancellation while reading body)",
         budget_left=0, consecutive_exhausted=2, independent_probe="failed",
         expect=("INCONCLUSIVE_BUDGET_EXHAUSTED", "LAYER_PROVEN_BODY")),
    dict(id="L10", provenance="hand_built", claimed_layer="connect",
         stderr_first_line="dial tcp 203.0.113.7:443: i/o timeout",
         budget_left=1, consecutive_exhausted=0, independent_probe=None,
         expect=("RETRYING", "BUDGET_OPEN")),
]


def main():
    out, ok, naive_wrong = [], 0, 0
    for r in ROWS:
        got = judge(r)
        nv = naive(r)
        passed = tuple(got) == tuple(r["expect"])
        ok += passed
        naive_wrong += nv != r["expect"][0]
        out.append({"id": r["id"], "provenance": r["provenance"], "verdict": got[0],
                    "layer_code": got[1], "expect": list(r["expect"]), "pass": passed,
                    "naive_verdict": nv, "naive_wrong": nv != r["expect"][0]})
    res = {"fixture": "INCONCLUSIVE_BUDGET_EXHAUSTED", "version": "0.2",
           "selftest": f"{ok}/{len(ROWS)}", "naive_wrong": f"{naive_wrong}/{len(ROWS)}", "rows": out}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if ok == len(ROWS) else 1


if __name__ == "__main__":
    sys.exit(main())
