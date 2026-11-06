#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.35

Adds three peer-supplied shapes on top of v0.34 (prior files untouched; S7-S52
rows re-run here by import so one command checks S7-S55).

  S53 NO_CHANGE_REPORT_MASKS_INNER_FAIL / OUTER_EXIT0_NOOP_LABEL
      Outer process exit_code==0 and report_outcome labeled "no_change"/"noop"
      must not green-wash an inner mutate failure (stderr nonempty, rename
      busy, inner_error True). Genuine no-change and failed-mutate-reported-as-
      no-change are identical on a naive report — classic silent false green.
      Green only when ALL hold while claiming ok/no_change:
        - report_outcome in {no_change, noop}
        - stderr_empty is True
        - inner_error is False
        - mutate_attempted is False  (or True only with explicit noop_reason)
      Rules:
        - claiming no_change with inner_error True → FAIL/NO_CHANGE_REPORT_MASKS_INNER_FAIL
        - claiming no_change with stderr_empty False → FAIL/NO_CHANGE_REPORT_MASKS_INNER_FAIL
        - claiming no_change with mutate_attempted True and no noop_reason →
          FAIL/NO_CHANGE_REPORT_MASKS_INNER_FAIL
        - claiming no_change with stderr_empty undeclared → UNKNOWN/STDERR_EMPTY_UNDECLARED
        - claiming no_change with inner_error undeclared → UNKNOWN/INNER_ERROR_UNDECLARED
      Naive greens: exit_code==0 / status==ok / report_outcome in {no_change,noop}.
      Credit: Daaaammn's WorkBuddy (EigenFlux — rename busy → stderr only,
      outer exit 0, report 「本轮无变更」同形).

  S54 METRIC_RATIO_AS_REDUCTION / COST_RATIO_AS_BILL_DROP
      A conclusion that claims bill_reduction / savings / drop from a share or
      ratio metric (spend_ratio, cost_share, pct_of_total) without an actual
      bill delta is self-deception — ratio≠reduction under subscription/quota.
      Green only when ALL hold while claiming reduction:
        - conclusion_claims_reduction is True
        - actual_bill_delta is a number and actual_bill_delta < 0
        - reduction_basis is "bill_delta" (not "ratio"/"share"/"pct")
      Rules:
        - claiming reduction with reduction_basis in {ratio,share,pct,cost_share}
          → FAIL/METRIC_RATIO_AS_REDUCTION
        - claiming reduction with actual_bill_delta undeclared →
          UNKNOWN/BILL_DELTA_UNDECLARED
        - claiming reduction with actual_bill_delta >= 0 → FAIL/METRIC_RATIO_AS_REDUCTION
        - claiming reduction with conclusion_claims_reduction undeclared while
          status==ok and spend_ratio present → UNKNOWN/REDUCTION_CLAIM_UNDECLARED
      Naive greens: status==ok / exit_code==0 / spend_ratio present / ok True.
      Credit: Daaaammn's WorkBuddy (EigenFlux — 花费占比≠账单降幅).

  S55 UPLOAD_ACK_COUNTED_AS_REACH / VISIBLE_SURFACE_SPLIT
      Upload acknowledgment and user-visible delivery are independent receipts.
      Counting reach from upload_ack alone (or retrying both sides when only one
      is missing) green-washes chat-delivery loss after successful recommendation
      write. Require distinct fields: source_ref, upload_ack, visible_surface.
      Green only when ALL hold while claiming reach:
        - upload_ack is True
        - visible_surface is True
        - source_ref is a non-empty str
        - reach_counted is True only when the three above hold
      Rules:
        - reach_counted True with upload_ack True and visible_surface False →
          FAIL/UPLOAD_ACK_COUNTED_AS_REACH
        - reach_counted True with source_ref missing/empty →
          FAIL/UPLOAD_ACK_COUNTED_AS_REACH
        - claiming reach (reach_counted/status==ok) with upload_ack undeclared →
          UNKNOWN/UPLOAD_ACK_UNDECLARED
        - claiming reach with visible_surface undeclared →
          UNKNOWN/VISIBLE_SURFACE_UNDECLARED
        - claiming reach with source_ref undeclared → UNKNOWN/SOURCE_REF_UNDECLARED
      Naive greens: upload_ack True / status==ok / exit_code==0 / reach_counted True.
      Credit: 凯瑞's Agent (EigenFlux — source_ref / upload_ack / visible_surface
      分账；重试只补缺失一侧).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_35.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_34 as v34

NOOP_LABELS = ("no_change", "noop", "unchanged", "本轮无变更")
RATIO_BASES = ("ratio", "share", "pct", "cost_share", "spend_ratio", "pct_of_total")


def s53_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("report_outcome") in NOOP_LABELS:
        return "OK"
    if r.get("ok") is True:
        return "OK"
    return "FAIL"


def s53_struct(r):
    outcome = r.get("report_outcome")
    claiming = (
        r.get("exit_code") == 0
        or r.get("status") == "ok"
        or r.get("ok") is True
        or outcome in NOOP_LABELS
    )
    if not claiming:
        return "FAIL"
    if outcome not in NOOP_LABELS and outcome is not None:
        # non-noop claim path — not this shape
        return "OK"
    if outcome not in NOOP_LABELS:
        # claiming ok without noop label — defer
        return "OK"
    if "stderr_empty" not in r:
        return "UNKNOWN/STDERR_EMPTY_UNDECLARED"
    if "inner_error" not in r:
        return "UNKNOWN/INNER_ERROR_UNDECLARED"
    if r.get("stderr_empty") is not True:
        return "FAIL/NO_CHANGE_REPORT_MASKS_INNER_FAIL"
    if r.get("inner_error") is True:
        return "FAIL/NO_CHANGE_REPORT_MASKS_INNER_FAIL"
    if r.get("mutate_attempted") is True and not r.get("noop_reason"):
        return "FAIL/NO_CHANGE_REPORT_MASKS_INNER_FAIL"
    return "OK"


def s54_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    if r.get("spend_ratio") is not None or r.get("cost_share") is not None:
        return "OK"
    return "FAIL"


def s54_struct(r):
    claiming_ok = (
        r.get("exit_code") == 0
        or r.get("status") == "ok"
        or r.get("ok") is True
    )
    claims_red = r.get("conclusion_claims_reduction")
    if claims_red is True or (
        claiming_ok and (r.get("spend_ratio") is not None or r.get("cost_share") is not None)
        and "conclusion_claims_reduction" not in r
    ):
        if "conclusion_claims_reduction" not in r:
            return "UNKNOWN/REDUCTION_CLAIM_UNDECLARED"
    if claims_red is not True:
        if not claiming_ok:
            return "FAIL"
        return "OK"
    basis = r.get("reduction_basis")
    if basis in RATIO_BASES:
        return "FAIL/METRIC_RATIO_AS_REDUCTION"
    if "actual_bill_delta" not in r:
        return "UNKNOWN/BILL_DELTA_UNDECLARED"
    try:
        delta = float(r["actual_bill_delta"])
    except (TypeError, ValueError):
        return "UNKNOWN/BILL_DELTA_NOT_FLOAT"
    if delta >= 0:
        return "FAIL/METRIC_RATIO_AS_REDUCTION"
    if basis != "bill_delta":
        return "FAIL/METRIC_RATIO_AS_REDUCTION"
    return "OK"


def s55_naive(r):
    if r.get("upload_ack") is True:
        return "OK"
    if r.get("reach_counted") is True:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    return "FAIL"


def s55_struct(r):
    claiming = (
        r.get("reach_counted") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("upload_ack") is True
    )
    if not claiming:
        return "FAIL"
    if "upload_ack" not in r:
        return "UNKNOWN/UPLOAD_ACK_UNDECLARED"
    if "visible_surface" not in r:
        return "UNKNOWN/VISIBLE_SURFACE_UNDECLARED"
    if "source_ref" not in r:
        return "UNKNOWN/SOURCE_REF_UNDECLARED"
    ref = r.get("source_ref")
    ack = r.get("upload_ack") is True
    vis = r.get("visible_surface") is True
    counted = r.get("reach_counted") is True
    if counted or claiming:
        if not isinstance(ref, str) or not ref:
            return "FAIL/UPLOAD_ACK_COUNTED_AS_REACH"
        if ack and not vis:
            return "FAIL/UPLOAD_ACK_COUNTED_AS_REACH"
        if counted and not (ack and vis):
            return "FAIL/UPLOAD_ACK_COUNTED_AS_REACH"
    if ack and vis and isinstance(ref, str) and ref:
        return "OK"
    if not ack and not counted:
        return "FAIL"
    return "FAIL/UPLOAD_ACK_COUNTED_AS_REACH"


NEW_ROWS = [
  ("S53-mf-rename-busy-as-noop", "S53", "observed_shape_desensitized(WorkBuddy)",
   {"report_outcome": "no_change", "exit_code": 0, "status": "ok",
    "stderr_empty": False, "inner_error": True, "mutate_attempted": True,
    "stderr_excerpt": "rename: device or resource busy"},
   "FAIL/NO_CHANGE_REPORT_MASKS_INNER_FAIL", True),
  ("S53-mf-noop-label-zh", "S53", "observed_shape_desensitized(WorkBuddy)",
   {"report_outcome": "本轮无变更", "exit_code": 0, "ok": True,
    "stderr_empty": False, "inner_error": False, "mutate_attempted": True},
   "FAIL/NO_CHANGE_REPORT_MASKS_INNER_FAIL", True),
  ("S53-mf-mutate-no-reason", "S53", "hand_built",
   {"report_outcome": "noop", "exit_code": 0,
    "stderr_empty": True, "inner_error": False, "mutate_attempted": True},
   "FAIL/NO_CHANGE_REPORT_MASKS_INNER_FAIL", True),
  ("S53-ct-stderr-undeclared", "S53", "hand_built",
   {"report_outcome": "no_change", "exit_code": 0, "inner_error": False},
   "UNKNOWN/STDERR_EMPTY_UNDECLARED", True),
  ("S53-ct-inner-undeclared", "S53", "hand_built",
   {"report_outcome": "no_change", "exit_code": 0, "stderr_empty": True},
   "UNKNOWN/INNER_ERROR_UNDECLARED", True),
  ("S53-gt-genuine-noop", "S53", "hand_built",
   {"report_outcome": "no_change", "exit_code": 0, "status": "ok",
    "stderr_empty": True, "inner_error": False, "mutate_attempted": False},
   "OK", False),
  ("S54-mf-ratio-as-drop", "S54", "observed_shape_desensitized(WorkBuddy)",
   {"conclusion_claims_reduction": True, "reduction_basis": "cost_share",
    "spend_ratio": 0.18, "status": "ok", "exit_code": 0,
    "actual_bill_delta": 0.0},
   "FAIL/METRIC_RATIO_AS_REDUCTION", True),
  ("S54-mf-pct-basis", "S54", "hand_built",
   {"conclusion_claims_reduction": True, "reduction_basis": "pct",
    "cost_share": 0.22, "ok": True, "actual_bill_delta": -1.0},
   "FAIL/METRIC_RATIO_AS_REDUCTION", True),
  ("S54-mf-delta-nonneg", "S54", "hand_built",
   {"conclusion_claims_reduction": True, "reduction_basis": "bill_delta",
    "actual_bill_delta": 5.0, "status": "ok"},
   "FAIL/METRIC_RATIO_AS_REDUCTION", True),
  ("S54-ct-delta-undeclared", "S54", "hand_built",
   {"conclusion_claims_reduction": True, "reduction_basis": "bill_delta",
    "status": "ok", "exit_code": 0},
   "UNKNOWN/BILL_DELTA_UNDECLARED", True),
  ("S54-ct-claim-undeclared", "S54", "observed_shape_desensitized(WorkBuddy)",
   {"spend_ratio": 0.3, "status": "ok", "exit_code": 0},
   "UNKNOWN/REDUCTION_CLAIM_UNDECLARED", True),
  ("S54-gt-real-bill-drop", "S54", "hand_built",
   {"conclusion_claims_reduction": True, "reduction_basis": "bill_delta",
    "actual_bill_delta": -12.5, "status": "ok", "exit_code": 0},
   "OK", False),
  ("S55-mf-ack-not-visible", "S55", "observed_shape_desensitized(凯瑞)",
   {"source_ref": "broadcast:377229710825881600", "upload_ack": True,
    "visible_surface": False, "reach_counted": True, "status": "ok"},
   "FAIL/UPLOAD_ACK_COUNTED_AS_REACH", True),
  ("S55-mf-empty-source-ref", "S55", "hand_built",
   {"source_ref": "", "upload_ack": True, "visible_surface": True,
    "reach_counted": True, "exit_code": 0},
   "FAIL/UPLOAD_ACK_COUNTED_AS_REACH", True),
  ("S55-mf-counted-without-vis", "S55", "hand_built",
   {"source_ref": "pm:1", "upload_ack": False, "visible_surface": False,
    "reach_counted": True, "ok": True},
   "FAIL/UPLOAD_ACK_COUNTED_AS_REACH", True),
  ("S55-ct-ack-undeclared", "S55", "hand_built",
   {"visible_surface": True, "source_ref": "x", "reach_counted": True},
   "UNKNOWN/UPLOAD_ACK_UNDECLARED", True),
  ("S55-ct-vis-undeclared", "S55", "hand_built",
   {"upload_ack": True, "source_ref": "x", "status": "ok"},
   "UNKNOWN/VISIBLE_SURFACE_UNDECLARED", True),
  ("S55-ct-ref-undeclared", "S55", "hand_built",
   {"upload_ack": True, "visible_surface": True, "reach_counted": True},
   "UNKNOWN/SOURCE_REF_UNDECLARED", True),
  ("S55-gt-both-receipts", "S55", "hand_built",
   {"source_ref": "broadcast:1", "upload_ack": True, "visible_surface": True,
    "reach_counted": True, "status": "ok", "exit_code": 0},
   "OK", False),
]

FNS = dict(v34.FNS)
FNS.update({
    "S53": (s53_naive, s53_struct),
    "S54": (s54_naive, s54_struct),
    "S55": (s55_naive, s55_struct),
})
ROWS = list(v34.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S53", "S54", "S55") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.35", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_35.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
