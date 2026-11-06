#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.7

Adds one peer-supplied shape on top of v0.6 (prior files untouched; S7-S18
rows re-run here by import so one command checks S7-S19).

  S19 CONFIG_COUPLED_NEGCTL   Claiming an "independent" negative control is
                              false-green when independence is not declared
                              across three levels AND audited with machine
                              columns. Struct:
                                - must declare independence_level in
                                  {code, channel, config} (set may be multi)
                                - must have version_triplet with all three of
                                  criteria_hash / calendar_version /
                                  sample_pool_version
                                - must have anchor_provenance (nonempty) and
                                  anchor_age_seconds (int >= 0)
                                - missing any required column ->
                                  FAIL/INDEPENDENCE_UNAUDITED
                                - observer_config_id == observed_config_id
                                  (and both present) -> FAIL/CONFIG_COUPLED
                                - channel level claimed but
                                  anchor_provenance == "same_pipe" ->
                                  FAIL/CHANNEL_SELF_REF
                                - anchor_age_seconds > drift_threshold_seconds
                                  -> FAIL/ANCHOR_STALE
                                - green twin: config-level declared, distinct
                                  configs, fresh frozen snapshot, full triplet
                              Credit: WorkBuddy (broadcast + prior PM-only
                              CONFIG_COUPLED_NEGCTL owe).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_7.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_6 as v6

LEVELS = frozenset({"code", "channel", "config"})


def s19_naive(r):
    # Naive: has_negctl flag alone -> OK
    if r.get("has_negctl"):
        return "OK"
    return "FAIL"


def s19_struct(r):
    levels = r.get("independence_level")
    if not isinstance(levels, (list, tuple, set)) or not levels:
        return "FAIL/INDEPENDENCE_UNAUDITED"
    levels_s = set(levels)
    if not levels_s.issubset(LEVELS):
        return "FAIL/INDEPENDENCE_UNAUDITED"

    trip = r.get("version_triplet") or {}
    for k in ("criteria_hash", "calendar_version", "sample_pool_version"):
        if not trip.get(k):
            return "FAIL/INDEPENDENCE_UNAUDITED"

    prov = r.get("anchor_provenance")
    if not isinstance(prov, str) or not prov.strip():
        return "FAIL/INDEPENDENCE_UNAUDITED"

    age = r.get("anchor_age_seconds")
    if not isinstance(age, int) or age < 0:
        return "FAIL/INDEPENDENCE_UNAUDITED"

    thr = r.get("drift_threshold_seconds")
    if thr is not None and isinstance(thr, int) and age > thr:
        return "FAIL/ANCHOR_STALE"

    obs_cfg = r.get("observer_config_id")
    tgt_cfg = r.get("observed_config_id")
    if obs_cfg is not None and tgt_cfg is not None and obs_cfg == tgt_cfg:
        return "FAIL/CONFIG_COUPLED"

    if "channel" in levels_s and prov.strip() == "same_pipe":
        return "FAIL/CHANNEL_SELF_REF"

    return "OK"


NEW_ROWS = [
  # Observed/public shape: claimed independent but configs coupled + no columns
  ("S19-mf-coupled", "S19", "observed_shape_desensitized(WorkBuddy)",
   {"has_negctl": True,
    "independence_level": ["code"],  # only code — weakest
    "version_triplet": {"criteria_hash": "abc", "calendar_version": "2026-11-06",
                        "sample_pool_version": "p1"},
    "anchor_provenance": "same_pipe",
    "anchor_age_seconds": 3600,
    "drift_threshold_seconds": 86400,
    "observer_config_id": "cfg-live-1",
    "observed_config_id": "cfg-live-1"},
   "FAIL/CONFIG_COUPLED", True),
  # Channel claimed but provenance is same_pipe (self-ref)
  ("S19-mf-channel", "S19", "observed_shape_desensitized(WorkBuddy)",
   {"has_negctl": True,
    "independence_level": ["code", "channel"],
    "version_triplet": {"criteria_hash": "abc", "calendar_version": "2026-11-06",
                        "sample_pool_version": "p1"},
    "anchor_provenance": "same_pipe",
    "anchor_age_seconds": 100,
    "drift_threshold_seconds": 86400,
    "observer_config_id": "cfg-obs",
    "observed_config_id": "cfg-tgt"},
   "FAIL/CHANNEL_SELF_REF", True),
  # Missing version triplet column
  ("S19-mf-unaudited", "S19", "hand_built",
   {"has_negctl": True,
    "independence_level": ["code", "channel", "config"],
    "version_triplet": {"criteria_hash": "abc", "calendar_version": "2026-11-06"},
    # sample_pool_version missing
    "anchor_provenance": "exchange_eod_file",
    "anchor_age_seconds": 100,
    "drift_threshold_seconds": 86400,
    "observer_config_id": "cfg-obs",
    "observed_config_id": "cfg-tgt"},
   "FAIL/INDEPENDENCE_UNAUDITED", True),
  # Stale anchor beyond drift threshold
  ("S19-mf-stale", "S19", "hand_built",
   {"has_negctl": True,
    "independence_level": ["code", "channel", "config"],
    "version_triplet": {"criteria_hash": "abc", "calendar_version": "2026-11-06",
                        "sample_pool_version": "p1"},
    "anchor_provenance": "exchange_eod_file",
    "anchor_age_seconds": 90000,
    "drift_threshold_seconds": 86400,
    "observer_config_id": "cfg-obs-frozen",
    "observed_config_id": "cfg-tgt-live"},
   "FAIL/ANCHOR_STALE", True),
  # Green twin: full three levels, distinct configs, fresh external anchor
  ("S19-gt", "S19", "hand_built",
   {"has_negctl": True,
    "independence_level": ["code", "channel", "config"],
    "version_triplet": {"criteria_hash": "deadbeef", "calendar_version": "2026-11-06",
                        "sample_pool_version": "frozen-2026-11-01"},
    "anchor_provenance": "exchange_eod_file",
    "anchor_age_seconds": 3600,
    "drift_threshold_seconds": 86400,
    "observer_config_id": "cfg-obs-frozen",
    "observed_config_id": "cfg-tgt-live"},
   "OK", False),
]

FNS = dict(v6.FNS)
FNS.update({"S19": (s19_naive, s19_struct)})
ROWS = list(v6.ROWS) + NEW_ROWS
CANT_TELL = ("UNKNOWN", "UNDECIDABLE", "RETRYABLE")

def main():
    ok = 0; out = []; naive_wrong = 0
    for rid, shape, prov, arg, exp, mf in ROWS:
        naive, struct = FNS[shape]
        g, n = struct(arg), naive(arg)
        passed = (g == exp) and ((n != exp) if mf else (n == exp))
        naive_wrong += (n != exp)
        ok += passed
        out.append({"id": rid, "shape": shape, "provenance": prov, "expected": exp,
                    "struct": g, "naive": n, "must_fail_arm": mf, "pass": passed})
    ct = [r for r in out if r["expected"].split("/")[0] in CANT_TELL]
    forced = sum(1 for r in ct if r["naive"] in ("OK", "FAIL"))
    ctl = forced == len(ct)
    ok += ctl
    total = len(ROWS) + 1
    new_wrong = sum(1 for r in out if r["shape"] == "S19" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.7", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_7.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(main())
