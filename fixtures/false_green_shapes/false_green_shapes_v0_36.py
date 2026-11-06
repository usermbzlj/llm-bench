#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.36

Adds three peer-supplied shapes on top of v0.35 (prior files untouched; S7-S55
rows re-run here by import so one command checks S7-S58).

  S56 READABLE_NOT_REPLACEABLE / SHARE_DELETE_GATE
      On Windows share modes, GENERIC_READ with share=1 lets another process
      read a file but rename/delete-open still fail (error 32). Claiming a
      file is replaceable from read_ok alone is a silent false green.
      Measured share matrix (peer): share=0 all fail; share=1 read ok /
      write+delete_open+rename fail; share=3 write+read ok / delete+rename
      fail; share=7 all ok. Rename needs object DELETE access AND holder
      FILE_SHARE_DELETE. Non-destructive precheck: try-open DELETE.
      Green only when ALL hold while claiming replaceable:
        - read_ok is True
        - delete_open_ok is True
        - rename_ok is True
        - share_mode includes FILE_SHARE_DELETE (share_mode & 4) OR
          share_allows_delete is True
      Rules:
        - claiming replaceable with read_ok True and rename_ok False →
          FAIL/READABLE_NOT_REPLACEABLE
        - claiming replaceable with delete_open_ok False →
          FAIL/READABLE_NOT_REPLACEABLE
        - claiming replaceable with rename_ok undeclared →
          UNKNOWN/RENAME_OK_UNDECLARED
        - claiming replaceable with delete_open_ok undeclared →
          UNKNOWN/DELETE_OPEN_OK_UNDECLARED
      Naive greens: read_ok True / exit_code==0 / status==ok / ok True.
      Credit: Hermes-AiMaShi (EigenFlux — share 0/1/3/7 matrix, DELETE
      precheck matches rename cell-for-cell).

  S57 INPROC_PROBE_SELF_VALIDATES / CROSS_PROCESS_REQUIRED
      The same unlock/share probe run inside the process that holds the
      handle always returns ok — even under share=0 — because the verifier
      is validating itself. Cross-process initiation is mandatory.
      Green only when ALL hold while claiming unlocked/unlocked_ok:
        - probe_same_process is False
        - probe_ok is True
        - share_mode is declared (int or str)
      Rules:
        - claiming unlocked with probe_same_process True →
          FAIL/INPROC_PROBE_SELF_VALIDATES
        - claiming unlocked with probe_same_process undeclared →
          UNKNOWN/PROBE_SAME_PROCESS_UNDECLARED
        - claiming unlocked with probe_ok undeclared →
          UNKNOWN/PROBE_OK_UNDECLARED
      Naive greens: probe_ok True / exit_code==0 / status==ok / ok True.
      Credit: Hermes-AiMaShi (EigenFlux — in-process probe share=0 still ok).

  S58 MARKER_EXISTS_WITHOUT_CONTENT / MARK_EMPTY
      After hard-killing a writer, marker_exists can be True with size=0.
      Existence alone must not count as write success. Four gates: exists →
      size>0 → parseable → content fingerprint match; size==0 is MARK_EMPTY,
      not success.
      Green only when ALL hold while claiming write_ok:
        - marker_exists is True
        - marker_size is int/float and marker_size > 0
        - content_parseable is True
        - content_fingerprint_match is True
      Rules:
        - claiming write_ok with marker_exists True and marker_size==0 →
          FAIL/MARK_EMPTY
        - claiming write_ok with marker_size<=0 → FAIL/MARK_EMPTY
        - claiming write_ok with content_parseable False →
          FAIL/MARKER_EXISTS_WITHOUT_CONTENT
        - claiming write_ok with content_fingerprint_match False →
          FAIL/MARKER_EXISTS_WITHOUT_CONTENT
        - claiming write_ok with marker_size undeclared →
          UNKNOWN/MARKER_SIZE_UNDECLARED
        - claiming write_ok with content_parseable undeclared →
          UNKNOWN/CONTENT_PARSEABLE_UNDECLARED
        - claiming write_ok with fingerprint undeclared →
          UNKNOWN/FINGERPRINT_MATCH_UNDECLARED
      Naive greens: marker_exists True / exit_code==0 / status==ok / ok True.
      Credit: Hermes-AiMaShi (EigenFlux — hard-kill 3/3 size=0 vs normal
      exit 28 bytes; four-gate landing criterion).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_36.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_35 as v35


def _claiming_ok(r):
    return (
        r.get("exit_code") == 0
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("replaceable") is True
        or r.get("unlocked") is True
        or r.get("write_ok") is True
        or r.get("claiming_replaceable") is True
        or r.get("claiming_unlocked") is True
        or r.get("claiming_write_ok") is True
    )


def s56_naive(r):
    if r.get("read_ok") is True:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    if r.get("replaceable") is True or r.get("claiming_replaceable") is True:
        return "OK"
    return "FAIL"


def s56_struct(r):
    claiming = (
        r.get("replaceable") is True
        or r.get("claiming_replaceable") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
    )
    if not claiming:
        return "FAIL"
    if "rename_ok" not in r:
        return "UNKNOWN/RENAME_OK_UNDECLARED"
    if "delete_open_ok" not in r:
        return "UNKNOWN/DELETE_OPEN_OK_UNDECLARED"
    rename_ok = r.get("rename_ok") is True
    delete_ok = r.get("delete_open_ok") is True
    read_ok = r.get("read_ok") is True
    share_allows = r.get("share_allows_delete") is True
    share_mode = r.get("share_mode")
    if isinstance(share_mode, int) and (share_mode & 4) == 4:
        share_allows = True
    if read_ok and not rename_ok:
        return "FAIL/READABLE_NOT_REPLACEABLE"
    if not delete_ok:
        return "FAIL/READABLE_NOT_REPLACEABLE"
    if not rename_ok:
        return "FAIL/READABLE_NOT_REPLACEABLE"
    if not share_allows and "share_allows_delete" in r:
        return "FAIL/READABLE_NOT_REPLACEABLE"
    return "OK"


def s57_naive(r):
    if r.get("probe_ok") is True:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    if r.get("unlocked") is True or r.get("claiming_unlocked") is True:
        return "OK"
    return "FAIL"


def s57_struct(r):
    claiming = (
        r.get("unlocked") is True
        or r.get("claiming_unlocked") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("probe_ok") is True
    )
    if not claiming:
        return "FAIL"
    if "probe_same_process" not in r:
        return "UNKNOWN/PROBE_SAME_PROCESS_UNDECLARED"
    if "probe_ok" not in r:
        return "UNKNOWN/PROBE_OK_UNDECLARED"
    if r.get("probe_same_process") is True:
        return "FAIL/INPROC_PROBE_SELF_VALIDATES"
    if r.get("probe_ok") is not True:
        return "FAIL"
    return "OK"


def s58_naive(r):
    if r.get("marker_exists") is True:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    if r.get("write_ok") is True or r.get("claiming_write_ok") is True:
        return "OK"
    return "FAIL"


def s58_struct(r):
    claiming = (
        r.get("write_ok") is True
        or r.get("claiming_write_ok") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("marker_exists") is True
    )
    if not claiming:
        return "FAIL"
    if "marker_size" not in r:
        return "UNKNOWN/MARKER_SIZE_UNDECLARED"
    if "content_parseable" not in r:
        return "UNKNOWN/CONTENT_PARSEABLE_UNDECLARED"
    if "content_fingerprint_match" not in r:
        return "UNKNOWN/FINGERPRINT_MATCH_UNDECLARED"
    try:
        size = float(r["marker_size"])
    except (TypeError, ValueError):
        return "UNKNOWN/MARKER_SIZE_NOT_NUMERIC"
    if size <= 0:
        return "FAIL/MARK_EMPTY"
    if r.get("marker_exists") is not True:
        return "FAIL"
    if r.get("content_parseable") is not True:
        return "FAIL/MARKER_EXISTS_WITHOUT_CONTENT"
    if r.get("content_fingerprint_match") is not True:
        return "FAIL/MARKER_EXISTS_WITHOUT_CONTENT"
    return "OK"


NEW_ROWS = [
  ("S56-mf-share1-read-only", "S56", "observed_shape_desensitized(Hermes-AiMaShi)",
   {"share_mode": 1, "read_ok": True, "write_ok": False, "delete_open_ok": False,
    "rename_ok": False, "share_allows_delete": False, "replaceable": True,
    "status": "ok", "exit_code": 0},
   "FAIL/READABLE_NOT_REPLACEABLE", True),
  ("S56-mf-share3-no-delete", "S56", "observed_shape_desensitized(Hermes-AiMaShi)",
   {"share_mode": 3, "read_ok": True, "write_ok": True, "delete_open_ok": False,
    "rename_ok": False, "share_allows_delete": False, "claiming_replaceable": True,
    "ok": True},
   "FAIL/READABLE_NOT_REPLACEABLE", True),
  ("S56-mf-read-ok-rename-fail", "S56", "hand_built",
   {"read_ok": True, "delete_open_ok": True, "rename_ok": False,
    "share_allows_delete": True, "status": "ok"},
   "FAIL/READABLE_NOT_REPLACEABLE", True),
  ("S56-ct-rename-undeclared", "S56", "hand_built",
   {"read_ok": True, "delete_open_ok": True, "replaceable": True, "exit_code": 0},
   "UNKNOWN/RENAME_OK_UNDECLARED", True),
  ("S56-ct-delete-undeclared", "S56", "hand_built",
   {"read_ok": True, "rename_ok": True, "claiming_replaceable": True},
   "UNKNOWN/DELETE_OPEN_OK_UNDECLARED", True),
  ("S56-gt-share7-all-ok", "S56", "observed_shape_desensitized(Hermes-AiMaShi)",
   {"share_mode": 7, "read_ok": True, "write_ok": True, "delete_open_ok": True,
    "rename_ok": True, "share_allows_delete": True, "replaceable": True,
    "status": "ok", "exit_code": 0},
   "OK", False),
  ("S57-mf-inproc-share0", "S57", "observed_shape_desensitized(Hermes-AiMaShi)",
   {"probe_same_process": True, "probe_ok": True, "share_mode": 0,
    "unlocked": True, "status": "ok", "exit_code": 0},
   "FAIL/INPROC_PROBE_SELF_VALIDATES", True),
  ("S57-mf-inproc-claiming", "S57", "hand_built",
   {"probe_same_process": True, "probe_ok": True, "claiming_unlocked": True,
    "ok": True},
   "FAIL/INPROC_PROBE_SELF_VALIDATES", True),
  ("S57-ct-same-proc-undeclared", "S57", "hand_built",
   {"probe_ok": True, "unlocked": True, "exit_code": 0},
   "UNKNOWN/PROBE_SAME_PROCESS_UNDECLARED", True),
  ("S57-ct-probe-ok-undeclared", "S57", "hand_built",
   {"probe_same_process": False, "claiming_unlocked": True, "status": "ok"},
   "UNKNOWN/PROBE_OK_UNDECLARED", True),
  ("S57-gt-cross-process", "S57", "hand_built",
   {"probe_same_process": False, "probe_ok": True, "share_mode": 0,
    "unlocked": True, "status": "ok", "exit_code": 0},
   "OK", False),
  ("S58-mf-mark-empty-hardkill", "S58", "observed_shape_desensitized(Hermes-AiMaShi)",
   {"marker_exists": True, "marker_size": 0, "content_parseable": False,
    "content_fingerprint_match": False, "write_ok": True, "status": "ok",
    "exit_code": 0},
   "FAIL/MARK_EMPTY", True),
  ("S58-mf-size-zero-ok-label", "S58", "hand_built",
   {"marker_exists": True, "marker_size": 0.0, "content_parseable": True,
    "content_fingerprint_match": True, "claiming_write_ok": True, "ok": True},
   "FAIL/MARK_EMPTY", True),
  ("S58-mf-exists-not-parseable", "S58", "hand_built",
   {"marker_exists": True, "marker_size": 28, "content_parseable": False,
    "content_fingerprint_match": False, "write_ok": True, "exit_code": 0},
   "FAIL/MARKER_EXISTS_WITHOUT_CONTENT", True),
  ("S58-mf-fingerprint-miss", "S58", "hand_built",
   {"marker_exists": True, "marker_size": 28, "content_parseable": True,
    "content_fingerprint_match": False, "status": "ok"},
   "FAIL/MARKER_EXISTS_WITHOUT_CONTENT", True),
  ("S58-ct-size-undeclared", "S58", "hand_built",
   {"marker_exists": True, "content_parseable": True,
    "content_fingerprint_match": True, "write_ok": True},
   "UNKNOWN/MARKER_SIZE_UNDECLARED", True),
  ("S58-ct-parseable-undeclared", "S58", "hand_built",
   {"marker_exists": True, "marker_size": 28, "content_fingerprint_match": True,
    "claiming_write_ok": True},
   "UNKNOWN/CONTENT_PARSEABLE_UNDECLARED", True),
  ("S58-ct-fp-undeclared", "S58", "hand_built",
   {"marker_exists": True, "marker_size": 28, "content_parseable": True,
    "write_ok": True, "exit_code": 0},
   "UNKNOWN/FINGERPRINT_MATCH_UNDECLARED", True),
  ("S58-gt-four-gates", "S58", "observed_shape_desensitized(Hermes-AiMaShi)",
   {"marker_exists": True, "marker_size": 28, "content_parseable": True,
    "content_fingerprint_match": True, "write_ok": True, "status": "ok",
    "exit_code": 0},
   "OK", False),
]

FNS = dict(v35.FNS)
FNS.update({
    "S56": (s56_naive, s56_struct),
    "S57": (s57_naive, s57_struct),
    "S58": (s58_naive, s58_struct),
})
ROWS = list(v35.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S56", "S57", "S58") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.36", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_36.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
