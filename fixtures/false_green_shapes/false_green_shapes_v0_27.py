#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.27

Adds one peer-supplied shape on top of v0.26 (prior files untouched; S7-S38
rows re-run here by import so one command checks S7-S39).

  S39 EXEC_DAC_BYPASS_EXIT0 / EXEC_FAIL_126_127_REASON_CODES
      Exit-code-only harnesses green on exit==0 and lump 126/127 as
      "permission fail". Observed root+DAC_OVERRIDE arms return exit 0
      while nobody fails (126 DIR_NOT_SEARCHABLE / exit 2 FILE_NOT_READABLE).
      Naive greens: exit==0 / status==ok / "permission_ok" / missing reason.
      Struct requires (not synthesizable):
        - exit_code (int)
        - reason_code (explicit taxonomy; empty != mapped)
        - euid, cap_eff (list/str; CAP_DAC_OVERRIDE presence matters)
        - dac_bypass_applied (bool; must be declared when exit==0 under root)
        - class in {owner,group,other}; ancestor_no_x_for_euid when dir search
        - out_of_126_127 (bool) when exit not in {0,126,127}
      Rules:
        - exit==0 AND (dac_bypass_applied OR CAP_DAC_OVERRIDE in cap_eff)
          while class in {other,group} or ancestor_no_x_for_euid ->
          FAIL/DAC_BYPASS_EXIT0
        - exit in {126,127} AND reason_code missing/empty ->
          UNKNOWN/REASON_CODE_UNDECLARED
        - exit not in {0,126,127} AND out_of_126_127 undeclared ->
          UNKNOWN/OUT_OF_126_127_UNDECLARED
        - exit==0 AND no dac bypass AND reason_code in
          {EXEC_OK_WITH_OUTPUT, EXEC_OK_NO_OUTPUT} -> OK
        - exit in {126,127} with mapped reason_code -> FAIL/<reason>
          (must-fail arms prove naive can't distinguish codes)
        - claiming EXEC_OK without euid or cap_eff ->
          UNKNOWN/PRIVILEGE_CONTEXT_UNDECLARED
      Credit: OpenClaw 助手 (EigenFlux PM — 9-arm desensitized root/nobody
      matrix: A1..A9; delivered EXEC_FAIL_126_127_REASON_CODES +
      DAC_BYPASS_EXIT0_DIR; requested EXEC_OK_WITH_OUTPUT baseline slot +
      out_of_126_127 for exit=2 shell-cannot-open).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_27.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_26 as v26


OK_REASONS = {"EXEC_OK_WITH_OUTPUT", "EXEC_OK_NO_OUTPUT"}
FAIL_126_127 = {
    "FILE_NOT_EXECUTABLE_FOR_EUID",
    "DIR_NOT_SEARCHABLE_FOR_EUID",
    "TARGET_NOT_FOUND",
    "INTERPRETER_NOT_FOUND",
    "TARGET_NOT_REGULAR",
    "FILE_NOT_READABLE",
}


def _caps(r):
    c = r.get("cap_eff")
    if c is None:
        return []
    if isinstance(c, str):
        return [x.strip() for x in c.replace(",", " ").split() if x.strip()]
    if isinstance(c, (list, tuple, set)):
        return list(c)
    return []


def s39_naive(r):
    if r.get("status") == "ok":
        return "OK"
    if r.get("permission_ok") is True:
        return "OK"
    ec = r.get("exit_code")
    if ec == 0:
        return "OK"
    if ec in (126, 127):
        return "FAIL"  # lumped — no reason_code discrimination
    if r.get("ran") is True:
        return "OK"
    return "FAIL"


def s39_struct(r):
    if "exit_code" not in r:
        return "UNKNOWN/EXIT_UNDECLARED"
    ec = r.get("exit_code")
    reason = r.get("reason_code")
    claiming_ok = (
        r.get("status") == "ok"
        or r.get("permission_ok") is True
        or r.get("ran") is True
        or ec == 0
    )

    if claiming_ok and ("euid" not in r or "cap_eff" not in r):
        return "UNKNOWN/PRIVILEGE_CONTEXT_UNDECLARED"

    caps = _caps(r)
    dac_cap = "CAP_DAC_OVERRIDE" in caps or "dac_override" in {c.lower() for c in caps}
    dac_applied = r.get("dac_bypass_applied") is True or dac_cap
    cls = r.get("class")
    ancestor_nox = r.get("ancestor_no_x_for_euid") is True

    if ec == 0:
        if dac_applied and (cls in ("other", "group") or ancestor_nox or r.get("dac_bypass_applied") is True):
            # root/privileged green that nobody would fail
            return "FAIL/DAC_BYPASS_EXIT0"
        if reason is None or reason == "":
            return "UNKNOWN/REASON_CODE_UNDECLARED"
        if reason in OK_REASONS and not dac_applied:
            return "OK"
        if reason == "EXEC_OK_BUT_DAC_BYPASS" or dac_applied:
            return "FAIL/DAC_BYPASS_EXIT0"
        return "FAIL"

    if ec in (126, 127):
        if reason is None or reason == "":
            return "UNKNOWN/REASON_CODE_UNDECLARED"
        if reason in FAIL_126_127:
            return f"FAIL/{reason}"
        return f"FAIL/{reason}"

    # out of {0,126,127}
    if "out_of_126_127" not in r:
        return "UNKNOWN/OUT_OF_126_127_UNDECLARED"
    if reason is None or reason == "":
        return "UNKNOWN/REASON_CODE_UNDECLARED"
    if reason in FAIL_126_127 or reason == "FILE_NOT_READABLE":
        return f"FAIL/{reason}"
    return f"FAIL/{reason}"


NEW_ROWS = [
  # A3 desensitized: root exit0 DAC bypass on dir700 ancestor other x=0
  ("S39-mf-dac-dir-bypass", "S39", "observed_shape_desensitized(OpenClaw助手)",
   {"arm": "A3_dir_not_search_700", "exit_code": 0,
    "reason_code": "EXEC_OK_BUT_DAC_BYPASS", "euid": 0,
    "cap_eff": ["CAP_DAC_OVERRIDE"], "dac_bypass_applied": True,
    "class": "other", "ancestor_no_x_for_euid": True,
    "status": "ok", "permission_ok": True},
   "FAIL/DAC_BYPASS_EXIT0", True),
  # A2 root: x bit set but no read — DAC bypass exit0
  ("S39-mf-dac-file-noread", "S39", "observed_shape_desensitized(OpenClaw助手)",
   {"arm": "A2_file_x_no_read_111", "exit_code": 0,
    "reason_code": "EXEC_OK_BUT_DAC_BYPASS", "euid": 0,
    "cap_eff": ["CAP_DAC_OVERRIDE"], "dac_bypass_applied": True,
    "class": "other", "status": "ok"},
   "FAIL/DAC_BYPASS_EXIT0", True),
  # naive exit==0 without privilege context
  ("S39-ct-priv-undeclared", "S39", "hand_built",
   {"exit_code": 0, "reason_code": "EXEC_OK_WITH_OUTPUT", "status": "ok"},
   "UNKNOWN/PRIVILEGE_CONTEXT_UNDECLARED", True),
  # 126 without reason_code
  ("S39-ct-reason-undeclared", "S39", "hand_built",
   {"exit_code": 126, "euid": 1000, "cap_eff": [], "status": "fail"},
   "UNKNOWN/REASON_CODE_UNDECLARED", True),
  # A2 nobody exit=2 out of 126/127, undeclared flag
  ("S39-ct-out-of-band", "S39", "observed_shape_desensitized(OpenClaw助手)",
   {"arm": "A2_nobody", "exit_code": 2, "reason_code": "FILE_NOT_READABLE",
    "euid": 65534, "cap_eff": []},
   "UNKNOWN/OUT_OF_126_127_UNDECLARED", True),
  # A1 mapped 126 with reason — must-fail vs naive lumped FAIL
  ("S39-mf-126-mapped", "S39", "observed_shape_desensitized(OpenClaw助手)",
   {"arm": "A1_file_no_x_644", "exit_code": 126,
    "reason_code": "FILE_NOT_EXECUTABLE_FOR_EUID",
    "euid": 1000, "cap_eff": [], "class": "other"},
   "FAIL/FILE_NOT_EXECUTABLE_FOR_EUID", True),
  # A4 127 mapped
  ("S39-mf-127-mapped", "S39", "observed_shape_desensitized(OpenClaw助手)",
   {"arm": "A4_missing_cmd", "exit_code": 127,
    "reason_code": "TARGET_NOT_FOUND",
    "euid": 1000, "cap_eff": []},
   "FAIL/TARGET_NOT_FOUND", True),
  # green twin: true EXEC_OK_WITH_OUTPUT no dac
  ("S39-gt-exec-ok-output", "S39", "observed_shape_desensitized(OpenClaw助手)",
   {"arm": "A9_normal_ok", "exit_code": 0,
    "reason_code": "EXEC_OK_WITH_OUTPUT", "euid": 1000,
    "cap_eff": [], "dac_bypass_applied": False, "class": "owner",
    "status": "ok"},
   "OK", False),
  # must-fail: nobody correctly maps dir search — naive lumps to FAIL
  ("S39-mf-nobody-dir-mapped", "S39", "hand_built",
   {"arm": "A3_nobody", "exit_code": 126,
    "reason_code": "DIR_NOT_SEARCHABLE_FOR_EUID",
    "euid": 65534, "cap_eff": [], "class": "other",
    "ancestor_no_x_for_euid": True, "out_of_126_127": False},
   "FAIL/DIR_NOT_SEARCHABLE_FOR_EUID", True),
  # green twin: empty_x no shebang — exit0 no dac, EXEC_OK_NO_OUTPUT
  ("S39-gt-exec-ok-no-output", "S39", "observed_shape_desensitized(OpenClaw助手)",
   {"arm": "A6_empty_x_no_shebang", "exit_code": 0,
    "reason_code": "EXEC_OK_NO_OUTPUT", "euid": 1000,
    "cap_eff": [], "dac_bypass_applied": False, "class": "owner"},
   "OK", False),
]


FNS = dict(v26.FNS)
FNS.update({"S39": (s39_naive, s39_struct)})
ROWS = list(v26.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] == "S39" and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.27", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_27.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
