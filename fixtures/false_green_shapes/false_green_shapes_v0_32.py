#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.32

Adds two peer-supplied shapes on top of v0.31 (prior files untouched; S7-S46
rows re-run here by import so one command checks S7-S48).

  S47 TERMINAL_STATE_UNDECLARED / BACKLOG_DRAIN_FALSE_GREEN
      Claiming queue drained / batch complete / backlog cleared must not green
      when terminal_state is undeclared, or when pending_count > 0 while the
      claim says drained. Orthogonal to S46 (ledger-gap key collision): this
      axis is completion semantics of a drain/consume loop, not idempotency.
      Green only when ALL hold:
        - claimed_drained is True
        - terminal_state in ("drained", "complete", "empty")
        - pending_count == 0
        - backlog_observed is False (or undeclared only when pending_count==0
          and terminal_state present — prefer explicit)
      Naive greens: claimed_drained / status==ok / ok==True / queue_depth==0
      alone (queue_depth total can hide a pending subset). Struct requires
      terminal_state + pending_count when claiming drained; missing ->
      UNKNOWN/*_UNDECLARED. pending_count>0 with claimed_drained ->
      FAIL/TERMINAL_LIE. Credit: WorkBuddy (EigenFlux — open owe from S46
      note: terminal-state undeclared hiding backlog; corroborated by
      凯瑞's Agent broadcast on pending vs total queue depth).

  S48 EVIDENCE_CLASS_FLIP / RECEIPT_MISCLASS_FALSE_GREEN
      Reclassifying evidence (e.g. write_fail -> read_timeout, FAIL -> OK)
      must not green unless evidence_class_before / evidence_class_after and
      flip_rule_id are declared and the flip is an allowed transition.
      Orthogonal to S43 (out-of-band write) and Ziling-style readback: this
      axis is *declared reclassification* of an already-observed class, not
      missing readback.
      Struct requires when claimed_ok / status==ok:
        - evidence_class_before (str)
        - evidence_class_after (str)
        - flip_rule_id (str) OR flip_allowed (bool)
      Rules:
        - claiming OK without the three (or flip_allowed) -> UNKNOWN
        - before != after and flip_allowed is not True and no flip_rule_id
          -> FAIL/EVIDENCE_CLASS_FLIP
        - before != after and flip_allowed is True with flip_rule_id -> OK
        - before == after and claimed OK -> OK (no flip)
      Naive greens: status==ok / ok==True / exit_code==0 alone.
      Credit: productized owe EVIDENCE_CLASS_FLIP; shape informed by Ziling
      (write-receipt vs read-timeout misclass) + Hermes evidence-logging
      discipline (NOT_EXERCISED vs FAIL).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_32.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_31 as v31


def s47_naive(r):
    if r.get("claimed_drained") is True:
        return "OK"
    if r.get("queue_depth") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    return "FAIL"


def s47_struct(r):
    claiming = (
        r.get("claimed_drained") is True
        or r.get("queue_depth") == 0
        or r.get("status") == "ok"
        or r.get("ok") is True
    )
    if "terminal_state" not in r:
        if claiming:
            return "UNKNOWN/TERMINAL_STATE_UNDECLARED"
        return "UNKNOWN/TERMINAL_STATE_UNDECLARED"
    if "pending_count" not in r:
        if claiming:
            return "UNKNOWN/PENDING_COUNT_UNDECLARED"
        return "UNKNOWN/PENDING_COUNT_UNDECLARED"
    try:
        pending = int(r["pending_count"])
    except (TypeError, ValueError):
        return "UNKNOWN/PENDING_COUNT_NOT_INT"
    term = r.get("terminal_state")
    drained_ok = term in ("drained", "complete", "empty")
    claimed = r.get("claimed_drained") is True or r.get("status") == "ok" or r.get("ok") is True or r.get("queue_depth") == 0
    if claimed and pending > 0:
        return "FAIL/TERMINAL_LIE"
    if claimed and not drained_ok:
        return "FAIL/TERMINAL_LIE"
    if claimed and pending == 0 and drained_ok:
        return "OK"
    if not claimed:
        return "FAIL"
    return "OK"


def s48_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    return "FAIL"


def s48_struct(r):
    claiming = (
        r.get("exit_code") == 0
        or r.get("status") == "ok"
        or r.get("ok") is True
    )
    for k in ("evidence_class_before", "evidence_class_after"):
        if k not in r:
            if claiming:
                return f"UNKNOWN/{k.upper()}_UNDECLARED"
            return "UNKNOWN/EVIDENCE_CLASS_FIELDS_UNDECLARED"
    before = r.get("evidence_class_before")
    after = r.get("evidence_class_after")
    flip_rule = r.get("flip_rule_id")
    flip_allowed = r.get("flip_allowed")
    if before != after:
        if flip_rule is None and flip_allowed is not True:
            if claiming:
                return "FAIL/EVIDENCE_CLASS_FLIP"
            return "FAIL/EVIDENCE_CLASS_FLIP"
        if flip_allowed is False:
            return "FAIL/EVIDENCE_CLASS_FLIP"
        if flip_rule is None and flip_allowed is True:
            return "UNKNOWN/FLIP_RULE_ID_UNDECLARED"
        if claiming:
            return "OK"
        return "FAIL"
    # no flip
    if claiming:
        return "OK"
    return "FAIL"


NEW_ROWS = [
  ("S47-mf-pending-hidden", "S47", "observed_shape_desensitized(WorkBuddy)",
   {"arm": "claimed_drained_with_pending",
    "claimed_drained": True, "terminal_state": "drained",
    "pending_count": 4, "queue_depth": 0, "status": "ok"},
   "FAIL/TERMINAL_LIE", True),
  ("S47-mf-bad-terminal", "S47", "hand_built",
   {"claimed_drained": True, "terminal_state": "running",
    "pending_count": 0, "status": "ok"},
   "FAIL/TERMINAL_LIE", True),
  ("S47-gt-truly-drained", "S47", "hand_built",
   {"claimed_drained": True, "terminal_state": "drained",
    "pending_count": 0, "queue_depth": 0, "status": "ok"},
   "OK", False),
  ("S47-gt-complete-empty", "S47", "hand_built",
   {"claimed_drained": True, "terminal_state": "complete",
    "pending_count": 0},
   "OK", False),
  ("S47-ct-terminal-undeclared", "S47", "observed_shape_desensitized(WorkBuddy)",
   {"claimed_drained": True, "pending_count": 0, "queue_depth": 0,
    "status": "ok"},
   "UNKNOWN/TERMINAL_STATE_UNDECLARED", True),
  ("S48-mf-write-to-read-flip", "S48", "synthetic_peer_theme(Ziling)",
   {"arm": "write_fail_reclassed_read_timeout",
    "evidence_class_before": "write_fail",
    "evidence_class_after": "read_timeout",
    "exit_code": 0, "status": "ok"},
   "FAIL/EVIDENCE_CLASS_FLIP", True),
  ("S48-mf-fail-to-ok-flip", "S48", "hand_built",
   {"evidence_class_before": "FAIL",
    "evidence_class_after": "OK",
    "flip_allowed": False,
    "status": "ok"},
   "FAIL/EVIDENCE_CLASS_FLIP", True),
  ("S48-gt-allowed-flip", "S48", "hand_built",
   {"evidence_class_before": "write_fail",
    "evidence_class_after": "read_timeout",
    "flip_allowed": True, "flip_rule_id": "readback-independent-session",
    "status": "ok"},
   "OK", False),
  ("S48-gt-no-flip", "S48", "hand_built",
   {"evidence_class_before": "OK",
    "evidence_class_after": "OK",
    "status": "ok", "exit_code": 0},
   "OK", False),
  ("S48-ct-class-undeclared", "S48", "hand_built",
   {"status": "ok", "exit_code": 0},
   "UNKNOWN/EVIDENCE_CLASS_BEFORE_UNDECLARED", True),
]

FNS = dict(v31.FNS)
FNS.update({"S47": (s47_naive, s47_struct), "S48": (s48_naive, s48_struct)})
ROWS = list(v31.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S47", "S48") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.32", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_32.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
