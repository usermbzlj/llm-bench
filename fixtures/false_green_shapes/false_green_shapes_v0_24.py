#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.24

Adds one peer-supplied shape on top of v0.23 (prior files untouched; S7-S35
rows re-run here by import so one command checks S7-S36).

  S36 UPLOAD_OK_DISPLAY_INCOMPLETE  Batch/notification counters that treat
                              backend upload / storage success as "displayed"
                              must not green-wash when the final user-facing
                              message is truncated or missing the source link.
                              Naive treats
                              (upload_ok OR storage_ok OR status==completed OR
                               counted_as_displayed) as OK.
                              Struct:
                                - upload_ok undeclared ->
                                  UNKNOWN/UPLOAD_UNDECLARED
                                - claiming displayed without
                                  display_body_complete ->
                                  UNKNOWN/DISPLAY_BODY_UNDECLARED
                                - claiming displayed without
                                  source_link_present ->
                                  UNKNOWN/SOURCE_LINK_UNDECLARED
                                - upload_ok/storage_ok/completed True AND
                                  (display_body_complete False OR
                                   source_link_present False) ->
                                  FAIL/UPLOAD_OK_DISPLAY_INCOMPLETE
                                - counted_as_displayed True while incomplete
                                  -> FAIL/UPLOAD_OK_DISPLAY_INCOMPLETE
                                - upload_ok AND body complete AND source link
                                  -> OK
                              Credit: 凯瑞's Agent (EigenFlux broadcast —
                              后台写入 / 消息生成 / 用户可见是三层；
                              「上传成功但最终消息被截断」负样本；
                              正文+来源链接都在最终输出才计「已展示」).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_24.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_23 as v23


def s36_naive(r):
    if r.get("counted_as_displayed") is True:
        return "OK"
    if r.get("status") == "completed":
        return "OK"
    if r.get("upload_ok") is True:
        return "OK"
    if r.get("storage_ok") is True:
        return "OK"
    if r.get("message_generated") is True:
        return "OK"
    return "FAIL"


def _claims_displayed(r):
    return (
        r.get("counted_as_displayed") is True
        or r.get("status") == "completed"
        or r.get("claim_displayed") is True
    )


def s36_struct(r):
    if "upload_ok" not in r and "storage_ok" not in r and r.get("status") is None:
        return "UNKNOWN/UPLOAD_UNDECLARED"

    uploadish = (
        r.get("upload_ok") is True
        or r.get("storage_ok") is True
        or r.get("status") == "completed"
    )

    claiming = _claims_displayed(r) or uploadish

    if claiming:
        if "display_body_complete" not in r:
            return "UNKNOWN/DISPLAY_BODY_UNDECLARED"
        if "source_link_present" not in r:
            return "UNKNOWN/SOURCE_LINK_UNDECLARED"

    body_ok = r.get("display_body_complete") is True
    link_ok = r.get("source_link_present") is True

    if uploadish or r.get("counted_as_displayed") is True:
        if not body_ok or not link_ok:
            return "FAIL/UPLOAD_OK_DISPLAY_INCOMPLETE"

    if body_ok and link_ok and (uploadish or r.get("message_generated") is True):
        return "OK"

    if not uploadish and not body_ok:
        return "FAIL"

    return "FAIL/UPLOAD_OK_DISPLAY_INCOMPLETE"


NEW_ROWS = [
  # Observed neg sample: upload ok, final message truncated (no complete body)
  ("S36-mf-upload-truncated", "S36", "observed_shape_desensitized(Kyrie)",
   {"upload_ok": True, "storage_ok": True, "message_generated": True,
    "status": "completed", "counted_as_displayed": True,
    "display_body_complete": False, "source_link_present": True,
    "truncation_detected": True},
   "FAIL/UPLOAD_OK_DISPLAY_INCOMPLETE", True),
  # Upload ok but source link missing from final output
  ("S36-mf-missing-source", "S36", "hand_built",
   {"upload_ok": True, "counted_as_displayed": True,
    "display_body_complete": True, "source_link_present": False},
   "FAIL/UPLOAD_OK_DISPLAY_INCOMPLETE", True),
  # Storage ok alone, body incomplete
  ("S36-mf-storage-only", "S36", "hand_built",
   {"storage_ok": True, "status": "completed",
    "display_body_complete": False, "source_link_present": False},
   "FAIL/UPLOAD_OK_DISPLAY_INCOMPLETE", True),
  # Claiming displayed without body field
  ("S36-ct-body-undeclared", "S36", "hand_built",
   {"upload_ok": True, "counted_as_displayed": True,
    "source_link_present": True},
   "UNKNOWN/DISPLAY_BODY_UNDECLARED", True),
  # Claiming displayed without source_link field
  ("S36-ct-link-undeclared", "S36", "hand_built",
   {"upload_ok": True, "claim_displayed": True,
    "display_body_complete": True},
   "UNKNOWN/SOURCE_LINK_UNDECLARED", True),
  # No upload/storage/status at all
  ("S36-ct-upload-undeclared", "S36", "hand_built",
   {"message_generated": True, "display_body_complete": True,
    "source_link_present": True},
   "UNKNOWN/UPLOAD_UNDECLARED", True),
  # Green: upload + complete body + source link
  ("S36-gt-full-display", "S36", "hand_built",
   {"upload_ok": True, "message_generated": True, "status": "completed",
    "counted_as_displayed": True, "display_body_complete": True,
    "source_link_present": True},
   "OK", False),
]


FNS = dict(v23.FNS)
FNS.update({"S36": (s36_naive, s36_struct)})
ROWS = list(v23.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S36" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.24", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_24.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
