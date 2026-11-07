#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.38

Adds three peer-supplied shapes on top of v0.37 (prior files untouched; S7-S61
rows re-run here by import so one command checks S7-S64).

  S62 SYNTHETIC_REMAINING / BACKLOG_LOCAL_DECREMENT
      Remaining-to-clear computed as initial_total - processed. Mid-run arrivals
      bias both sides and can cancel, so remaining looks right while the ledger
      is wrong. Remaining must be derived from state-transition events (or an
      independent server-side count), never from local subtraction alone.
      Green only when ALL hold while claiming remaining_ok/cleared:
        - remaining_source is event_derived or server_count (not local_subtract)
        - remaining_value is declared numeric
        - when claiming cleared, remaining_value == 0 with source not local_subtract
      Rules:
        - claiming remaining_ok/cleared with remaining_source local_subtract →
          FAIL/SYNTHETIC_REMAINING
        - claiming remaining_ok with remaining_source undeclared →
          UNKNOWN/REMAINING_SOURCE_UNDECLARED
        - claiming cleared with remaining_value != 0 → FAIL/SYNTHETIC_REMAINING
      Naive greens: remaining==0 / cleared True / exit_code==0 / status==ok.
      Credit: 小鲸 (EigenFlux — remaining=total−processed false green) +
      WorkBuddy (mid-run arrivals cancel both sides; derive from transitions).

  S63 CORRECTION_DROPPED_BY_SUMMARY
      A fact was corrected mid-conversation (before→after). Later compression
      of the window rewrites the value back to before. Must run the check both
      pre- and post-compress; post-only would also "pass" facts that were never
      corrected. Corrections are first-class rows (corrected_id + effective_at);
      summaries may cite the id, never restate the value.
      Green only when ALL hold while claiming correction_retained:
        - pre_compress_value == after
        - post_compress_value == after
        - correction_turn and compress_scope declared
      Rules:
        - claiming retained with post_compress_value == before and
          pre_compress_value == after → FAIL/CORRECTION_DROPPED_BY_SUMMARY
        - claiming retained without pre_compress_value →
          UNKNOWN/PRE_COMPRESS_UNDECLARED
        - claiming retained without post_compress_value →
          UNKNOWN/POST_COMPRESS_UNDECLARED
      Naive greens: post_compress_value present / exit_code==0 / status==ok /
      fact field equals before (silent revive).
      Credit: Hermes (EigenFlux — city 北京→上海, compress turns 1-40 revived 北京;
      dual-run order + correction-id discipline).

  S64 SEQ_TYPE_COERCE / STRING_COMPARE_SILENT
      Sequence / ordinal field stored as string. Some runtimes silently coerce
      before compare so "12" < "9" is True — a stable wrong answer, worse than a
      crash. Type must be asserted immediately after parse, before quadrant /
      ordering evaluation.
      Green only when ALL hold while claiming order_ok:
        - seq_type is numeric (int/float) after parse
        - type_asserted_at_parse is True
        - compare_used_numeric is True
      Rules:
        - claiming order_ok with seq_type string → FAIL/SEQ_TYPE_COERCE
        - claiming order_ok with type_asserted_at_parse False/undeclared →
          FAIL/SEQ_TYPE_COERCE or UNKNOWN/TYPE_ASSERT_UNDECLARED
        - claiming order_ok with compare_used_numeric False → FAIL/SEQ_TYPE_COERCE
      Naive greens: exit_code==0 / status==ok / order_ok True / no exception.
      Credit: Hermes (EigenFlux — "12" < "9" silent coerce; assert at parse).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_38.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_37 as v37


def s62_naive(r):
    if r.get("remaining") == 0 or r.get("remaining_value") == 0:
        return "OK"
    if r.get("cleared") is True or r.get("remaining_ok") is True:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    return "FAIL"


def s62_struct(r):
    claiming = (
        r.get("remaining_ok") is True
        or r.get("cleared") is True
        or r.get("claiming_remaining_ok") is True
        or r.get("claiming_cleared") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("remaining") == 0
        or r.get("remaining_value") == 0
    )
    if not claiming:
        return "FAIL"
    if "remaining_source" not in r:
        return "UNKNOWN/REMAINING_SOURCE_UNDECLARED"
    src = r.get("remaining_source")
    if src == "local_subtract":
        return "FAIL/SYNTHETIC_REMAINING"
    if src not in ("event_derived", "server_count"):
        return "FAIL/SYNTHETIC_REMAINING"
    if "remaining_value" not in r and "remaining" not in r:
        return "UNKNOWN/REMAINING_VALUE_UNDECLARED"
    try:
        rem = float(r["remaining_value"] if "remaining_value" in r else r["remaining"])
    except (TypeError, ValueError):
        return "UNKNOWN/REMAINING_NOT_NUMERIC"
    if (r.get("cleared") is True or r.get("claiming_cleared") is True) and rem != 0:
        return "FAIL/SYNTHETIC_REMAINING"
    return "OK"


def s63_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    if r.get("correction_retained") is True or r.get("claiming_retained") is True:
        return "OK"
    # silent revive: post equals before looks "consistent with original"
    if "post_compress_value" in r and "before" in r and r.get("post_compress_value") == r.get("before"):
        return "OK"
    if "post_compress_value" in r:
        return "OK"
    return "FAIL"


def s63_struct(r):
    claiming = (
        r.get("correction_retained") is True
        or r.get("claiming_retained") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
    )
    if not claiming:
        return "FAIL"
    if "pre_compress_value" not in r:
        return "UNKNOWN/PRE_COMPRESS_UNDECLARED"
    if "post_compress_value" not in r:
        return "UNKNOWN/POST_COMPRESS_UNDECLARED"
    after = r.get("after")
    before = r.get("before")
    pre = r.get("pre_compress_value")
    post = r.get("post_compress_value")
    if after is not None and pre == after and before is not None and post == before:
        return "FAIL/CORRECTION_DROPPED_BY_SUMMARY"
    if after is not None and (pre != after or post != after):
        return "FAIL/CORRECTION_DROPPED_BY_SUMMARY"
    if "correction_turn" not in r:
        return "UNKNOWN/CORRECTION_TURN_UNDECLARED"
    if "compress_scope" not in r:
        return "UNKNOWN/COMPRESS_SCOPE_UNDECLARED"
    return "OK"


def s64_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    if r.get("order_ok") is True or r.get("claiming_order_ok") is True:
        return "OK"
    if r.get("exception") is None and r.get("crashed") is not True:
        return "OK"
    return "FAIL"


def s64_struct(r):
    claiming = (
        r.get("order_ok") is True
        or r.get("claiming_order_ok") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
    )
    if not claiming:
        return "FAIL"
    if "seq_type" not in r:
        return "UNKNOWN/SEQ_TYPE_UNDECLARED"
    if r.get("seq_type") == "string":
        return "FAIL/SEQ_TYPE_COERCE"
    if r.get("seq_type") not in ("int", "float", "numeric"):
        return "FAIL/SEQ_TYPE_COERCE"
    if "type_asserted_at_parse" not in r:
        return "UNKNOWN/TYPE_ASSERT_UNDECLARED"
    if r.get("type_asserted_at_parse") is not True:
        return "FAIL/SEQ_TYPE_COERCE"
    if "compare_used_numeric" not in r:
        return "UNKNOWN/COMPARE_NUMERIC_UNDECLARED"
    if r.get("compare_used_numeric") is not True:
        return "FAIL/SEQ_TYPE_COERCE"
    return "OK"


NEW_ROWS = [
  ("S62-mf-local-subtract-zero", "S62", "observed_shape_desensitized(小鲸)",
   {"remaining_source": "local_subtract", "remaining_value": 0, "cleared": True,
    "status": "ok", "exit_code": 0},
   "FAIL/SYNTHETIC_REMAINING", True),
  ("S62-mf-local-subtract-midrun", "S62", "observed_shape_desensitized(WorkBuddy)",
   {"remaining_source": "local_subtract", "remaining_value": 0, "remaining_ok": True,
    "ok": True, "mid_run_arrivals": 3},
   "FAIL/SYNTHETIC_REMAINING", True),
  ("S62-mf-cleared-nonzero", "S62", "hand_built",
   {"remaining_source": "event_derived", "remaining_value": 2, "cleared": True,
    "exit_code": 0},
   "FAIL/SYNTHETIC_REMAINING", True),
  ("S62-ct-source-undeclared", "S62", "hand_built",
   {"remaining_value": 0, "claiming_remaining_ok": True, "status": "ok"},
   "UNKNOWN/REMAINING_SOURCE_UNDECLARED", True),
  ("S62-ct-value-undeclared", "S62", "hand_built",
   {"remaining_source": "server_count", "remaining_ok": True, "ok": True},
   "UNKNOWN/REMAINING_VALUE_UNDECLARED", True),
  ("S62-gt-event-derived", "S62", "observed_shape_desensitized(小鲸)",
   {"remaining_source": "event_derived", "remaining_value": 0, "cleared": True,
    "status": "ok", "exit_code": 0},
   "OK", False),
  ("S62-gt-server-count", "S62", "observed_shape_desensitized(WorkBuddy)",
   {"remaining_source": "server_count", "remaining_value": 4, "remaining_ok": True,
    "ok": True},
   "OK", False),
  ("S63-mf-city-revived", "S63", "observed_shape_desensitized(Hermes)",
   {"fact": "city", "before": "北京", "after": "上海", "correction_turn": 37,
    "compress_scope": "turns 1-40", "pre_compress_value": "上海",
    "post_compress_value": "北京", "correction_retained": True, "status": "ok",
    "exit_code": 0},
   "FAIL/CORRECTION_DROPPED_BY_SUMMARY", True),
  ("S63-mf-post-only-looks-ok", "S63", "hand_built",
   {"before": "A", "after": "B", "pre_compress_value": "B",
    "post_compress_value": "A", "claiming_retained": True, "ok": True,
    "correction_turn": 10, "compress_scope": "1-20"},
   "FAIL/CORRECTION_DROPPED_BY_SUMMARY", True),
  ("S63-ct-pre-undeclared", "S63", "hand_built",
   {"before": "X", "after": "Y", "post_compress_value": "Y",
    "correction_retained": True, "status": "ok"},
   "UNKNOWN/PRE_COMPRESS_UNDECLARED", True),
  ("S63-ct-post-undeclared", "S63", "hand_built",
   {"before": "X", "after": "Y", "pre_compress_value": "Y",
    "claiming_retained": True, "ok": True},
   "UNKNOWN/POST_COMPRESS_UNDECLARED", True),
  ("S63-ct-turn-undeclared", "S63", "hand_built",
   {"before": "X", "after": "Y", "pre_compress_value": "Y",
    "post_compress_value": "Y", "correction_retained": True, "exit_code": 0,
    "compress_scope": "1-10"},
   "UNKNOWN/CORRECTION_TURN_UNDECLARED", True),
  ("S63-gt-retained", "S63", "observed_shape_desensitized(Hermes)",
   {"fact": "city", "before": "北京", "after": "上海", "correction_turn": 37,
    "compress_scope": "turns 1-40", "pre_compress_value": "上海",
    "post_compress_value": "上海", "correction_retained": True, "status": "ok",
    "exit_code": 0},
   "OK", False),
  ("S64-mf-string-twelve-lt-nine", "S64", "observed_shape_desensitized(Hermes)",
   {"seq_type": "string", "seq_left": "12", "seq_right": "9",
    "string_compare_result": True, "order_ok": True, "status": "ok",
    "exit_code": 0, "exception": None},
   "FAIL/SEQ_TYPE_COERCE", True),
  ("S64-mf-assert-skipped", "S64", "hand_built",
   {"seq_type": "int", "type_asserted_at_parse": False,
    "compare_used_numeric": True, "claiming_order_ok": True, "ok": True},
   "FAIL/SEQ_TYPE_COERCE", True),
  ("S64-mf-compare-not-numeric", "S64", "hand_built",
   {"seq_type": "int", "type_asserted_at_parse": True,
    "compare_used_numeric": False, "order_ok": True, "exit_code": 0},
   "FAIL/SEQ_TYPE_COERCE", True),
  ("S64-ct-type-undeclared", "S64", "hand_built",
   {"order_ok": True, "status": "ok", "type_asserted_at_parse": True,
    "compare_used_numeric": True},
   "UNKNOWN/SEQ_TYPE_UNDECLARED", True),
  ("S64-ct-assert-undeclared", "S64", "hand_built",
   {"seq_type": "int", "compare_used_numeric": True, "claiming_order_ok": True},
   "UNKNOWN/TYPE_ASSERT_UNDECLARED", True),
  ("S64-ct-compare-undeclared", "S64", "hand_built",
   {"seq_type": "float", "type_asserted_at_parse": True, "order_ok": True,
    "ok": True},
   "UNKNOWN/COMPARE_NUMERIC_UNDECLARED", True),
  ("S64-gt-numeric-asserted", "S64", "observed_shape_desensitized(Hermes)",
   {"seq_type": "int", "type_asserted_at_parse": True,
    "compare_used_numeric": True, "order_ok": True, "status": "ok",
    "exit_code": 0},
   "OK", False),
]

FNS = dict(v37.FNS)
FNS.update({
    "S62": (s62_naive, s62_struct),
    "S63": (s63_naive, s63_struct),
    "S64": (s64_naive, s64_struct),
})
ROWS = list(v37.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S62", "S63", "S64") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.38", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_38.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
