#!/usr/bin/env python3
"""LOCATION_SPLIT v0.1

Failure shape: discovery/local/api disagree on *where* the live object is.
Naive checks any one plane green (api alive OR local logged-in OR port
listening) -> OK. Struct requires the three planes to name the same
location token; otherwise FAIL/LOCATION_SPLIT.

Observed desensitized rows credit: 52Hz
  L1 chrome-profile: api=未登录(-101); local=已登录;
     discovery=started with a different user-data-dir
  L2 local port: api=process alive + port listening; local=cannot deliver
     (hitting old port); discovery=port only changes after restart

analyze_only. Stdlib only. Run: python3 location_split_v0_1.py
"""
from __future__ import annotations
import json, sys

def naive(r):
    api = r.get("api") or {}
    local = r.get("local") or {}
    if api.get("ok") or local.get("ok") or api.get("listening") or local.get("logged_in"):
        return "OK"
    if r.get("rc", 1) == 0:
        return "OK"
    return "FAIL"

def struct(r):
    api = r.get("api") or {}
    local = r.get("local") or {}
    disc = r.get("discovery") or {}
    # Prefer explicit location tokens
    tokens = []
    for plane, blob in (("api", api), ("local", local), ("discovery", disc)):
        loc = blob.get("location")
        if loc is None or loc == "":
            # Missing location while plane claims success -> split risk
            if blob.get("ok") or blob.get("listening") or blob.get("logged_in"):
                return "FAIL/LOCATION_SPLIT"
            continue
        tokens.append((plane, str(loc)))
    if len(tokens) < 2:
        return "UNDECIDABLE/LOCATION_UNDER_SPECIFIED"
    locs = {t[1] for t in tokens}
    if len(locs) > 1:
        return "FAIL/LOCATION_SPLIT"
    # Same location but contradictory status (logged in vs auth fail)
    if local.get("logged_in") and api.get("auth_code") in (-101, 401, "UNAUTH"):
        return "FAIL/LOCATION_SPLIT"
    if api.get("listening") and local.get("deliverable") is False:
        return "FAIL/LOCATION_SPLIT"
    return "OK"

ROWS = [
  ("L1-mf", "observed_shape_desensitized",
   {"object": "chrome-profile",
    "api": {"ok": False, "auth_code": -101, "location": "user-data-dir-A", "logged_in": False},
    "local": {"ok": True, "logged_in": True, "location": "user-data-dir-A"},
    "discovery": {"location": "user-data-dir-B", "ok": True}},
   "FAIL/LOCATION_SPLIT", True),
  ("L2-mf", "observed_shape_desensitized",
   {"object": "local-port",
    "api": {"ok": True, "listening": True, "location": "127.0.0.1:18080"},
    "local": {"ok": False, "deliverable": False, "location": "127.0.0.1:18080"},
    "discovery": {"location": "127.0.0.1:18081", "ok": True, "note": "port changes only after restart"}},
   "FAIL/LOCATION_SPLIT", True),
  ("L1-gt", "hand_built",
   {"object": "chrome-profile",
    "api": {"ok": True, "auth_code": 0, "location": "user-data-dir-A", "logged_in": True},
    "local": {"ok": True, "logged_in": True, "location": "user-data-dir-A"},
    "discovery": {"location": "user-data-dir-A", "ok": True}},
   "OK", False),
  ("L-un", "hand_built",
   {"object": "unknown",
    "api": {"ok": False},
    "local": {"ok": False},
    "discovery": {}},
   "UNDECIDABLE/LOCATION_UNDER_SPECIFIED", True),
]

def main():
    ok = 0; out = []; naive_wrong = 0
    for rid, prov, arg, exp, mf in ROWS:
        g, n = struct(arg), naive(arg)
        passed = (g == exp) and ((n != exp) if mf else (n == exp))
        naive_wrong += (n != exp)
        ok += passed
        out.append({"id": rid, "provenance": prov, "expected": exp, "struct": g,
                    "naive": n, "must_fail_arm": mf, "pass": passed})
    ct = [r for r in out if r["expected"].startswith("UNDECIDABLE")]
    forced = sum(1 for r in ct if r["naive"] in ("OK", "FAIL"))
    ctl = forced == len(ct)
    ok += ctl
    total = len(ROWS) + 1
    res = {"fixture": "LOCATION_SPLIT", "version": "0.1", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_1.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)}; forced {forced}/{len(ct)}")
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
