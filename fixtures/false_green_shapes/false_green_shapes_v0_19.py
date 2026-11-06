#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.19

Adds one peer-supplied shape on top of v0.18 (prior files untouched; S7-S30
rows re-run here by import so one command checks S7-S31).

  S31 STDERR_PROMOTED_EXIT0  exit_code==0 must not green-wash a non-empty
                              error-class stderr channel. Naive treats
                              exit_code==0 as OK even when stderr carries
                              error/warning text (or when shell_ok_flag=true
                              while last_exit_code!=0 — PowerShell $? vs
                              $LASTEXITCODE fork under NativeCommandError).
                              Struct:
                                - stderr_captured undeclared ->
                                  UNKNOWN/STDERR_CHANNEL_UNDECLARED
                                - exit_code==0 + stderr_nonempty + not
                                  stderr_classified_benign ->
                                  FAIL/STDERR_PROMOTED_EXIT0
                                - shell_ok_flag=true + last_exit_code!=0 ->
                                  FAIL/SHELL_FLAG_MASKED_EXIT
                                - honest green: exit 0 + (stderr empty OR
                                  classified benign) + flags consistent
                              Credit: Jasper (STDERR_PROMOTED_EXIT0 owe /
                              LOCKED schema direction); Jaemin (PowerShell
                              $? vs $LASTEXITCODE divergence under
                              NativeCommandError — judgment expression must
                              be a desensitized row field).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_19.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_18 as v18


def s31_naive(r):
    # Naive: exit_code alone (or shell_ok_flag if present)
    if "shell_ok_flag" in r and r.get("shell_ok_flag") is not None:
        return "OK" if r.get("shell_ok_flag") else "FAIL"
    code = r.get("exit_code")
    if code is None:
        return "FAIL"
    try:
        return "OK" if int(code) == 0 else "FAIL"
    except (TypeError, ValueError):
        return "FAIL"


def s31_struct(r):
    # Channel must be declared before exit-0 can green
    if "stderr_captured" not in r and "stderr_nonempty" not in r:
        return "UNKNOWN/STDERR_CHANNEL_UNDECLARED"

    # Shell-flag vs last_exit_code fork (PowerShell $? vs $LASTEXITCODE)
    if "shell_ok_flag" in r and "last_exit_code" in r:
        try:
            lec = int(r.get("last_exit_code"))
        except (TypeError, ValueError):
            return "UNKNOWN/LAST_EXIT_UNREADABLE"
        if r.get("shell_ok_flag") is True and lec != 0:
            return "FAIL/SHELL_FLAG_MASKED_EXIT"
        if r.get("shell_ok_flag") is False and lec == 0:
            # NativeCommandError style: $? false while recorded exit 0 —
            # do not trust either alone; require stderr classification
            if r.get("stderr_nonempty") and not r.get("stderr_classified_benign"):
                return "FAIL/STDERR_PROMOTED_EXIT0"
            if r.get("stderr_captured") is False:
                return "UNKNOWN/STDERR_CHANNEL_UNDECLARED"

    code = r.get("exit_code")
    try:
        code_i = int(code) if code is not None else None
    except (TypeError, ValueError):
        return "FAIL"

    stderr_nonempty = bool(r.get("stderr_nonempty"))
    benign = bool(r.get("stderr_classified_benign"))
    captured = r.get("stderr_captured")

    if captured is False and code_i == 0:
        # Exit 0 but stderr never captured — can't prove clean
        return "UNKNOWN/STDERR_CHANNEL_UNDECLARED"

    if code_i == 0 and stderr_nonempty and not benign:
        return "FAIL/STDERR_PROMOTED_EXIT0"

    if code_i == 0 and (not stderr_nonempty or benign):
        return "OK"

    if code_i is not None and code_i != 0:
        # Non-zero is not this shape's false-green; leave as FAIL for naive twin
        return "FAIL"

    return "UNKNOWN/STDERR_CHANNEL_UNDECLARED"


NEW_ROWS = [
  # Observed-shape: exit 0 + error-class stderr => false green under naive
  ("S31-mf-stderr-exit0", "S31", "observed_shape_desensitized(Jasper)",
   {"exit_code": 0, "stderr_captured": True, "stderr_nonempty": True,
    "stderr_classified_benign": False, "stderr_class": "error"},
   "FAIL/STDERR_PROMOTED_EXIT0", True),
  # PowerShell fork: $? true while $LASTEXITCODE nonzero (masked exit)
  ("S31-mf-shell-flag-mask", "S31", "observed_shape_desensitized(Jaemin)",
   {"exit_code": 0, "shell_ok_flag": True, "last_exit_code": 1,
    "stderr_captured": True, "stderr_nonempty": True,
    "stderr_classified_benign": False},
   "FAIL/SHELL_FLAG_MASKED_EXIT", True),
  # $? false + exit recorded 0 + dirty stderr
  ("S31-mf-native-cmd-err", "S31", "hand_built",
   {"exit_code": 0, "shell_ok_flag": False, "last_exit_code": 0,
    "stderr_captured": True, "stderr_nonempty": True,
    "stderr_classified_benign": False},
   "FAIL/STDERR_PROMOTED_EXIT0", True),
  # Undeclared stderr channel
  ("S31-ct-undeclared", "S31", "hand_built",
   {"exit_code": 0},
   "UNKNOWN/STDERR_CHANNEL_UNDECLARED", True),
  # Captured=false on exit 0
  ("S31-ct-uncaptured", "S31", "hand_built",
   {"exit_code": 0, "stderr_captured": False, "stderr_nonempty": False},
   "UNKNOWN/STDERR_CHANNEL_UNDECLARED", True),
  # Green: clean exit 0, stderr empty
  ("S31-gt-clean-exit0", "S31", "hand_built",
   {"exit_code": 0, "stderr_captured": True, "stderr_nonempty": False,
    "shell_ok_flag": True, "last_exit_code": 0},
   "OK", False),
  # Green: exit 0 + stderr present but classified benign (progress tip)
  ("S31-gt-benign-stderr", "S31", "hand_built",
   {"exit_code": 0, "stderr_captured": True, "stderr_nonempty": True,
    "stderr_classified_benign": True, "stderr_class": "progress",
    "shell_ok_flag": True, "last_exit_code": 0},
   "OK", False),
]

FNS = dict(v18.FNS)
FNS.update({"S31": (s31_naive, s31_struct)})
ROWS = list(v18.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S31" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.19", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_19.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL", r["id"], "struct", r["struct"], "naive", r["naive"], "exp", r["expected"])
    if not ctl:
        print("FAIL forced-verdict-control", forced, "of", len(ct))
    sys.exit(0 if ok == total else 1)

if __name__ == "__main__":
    main()
