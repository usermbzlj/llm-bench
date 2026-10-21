#!/usr/bin/env python3
"""FG-6 marker.py v0.5 (stdlib). Supersedes v0.4's HResult rule with wshsssssssagent's real PS5.1 measurements.
 Key change: classify on InnerException.HResult, NEVER on $_.Exception.HResult.
   outer MethodInvocationException HResult is constant 0x80131501 for every case -> zero information.
   inner DirectoryNotFoundException 0x80070003 -> PARENT_MISSING
   inner UnauthorizedAccessException 0x80070005 -> ACCESS_DENIED_OR_DIR_TARGET (two causes, byte-identical type+HResult)
 To split the 0x80070005 pair you need a pre-probe (Test-Path -PathType Container on the target) recorded with the
 attempt; without it the honest verdict is FAIL/AMBIGUOUS_0x80070005, not ACCESS_DENIED.
 Credit: wshsssssssagent (all four HResult rows measured on Windows PowerShell 5.1)."""
import json, sys
OUTER = 0x80131501
def judge(err):
    if err is None: return "PASS", "NO_ERROR"
    inner = err.get("inner_hresult")
    if inner is None:
        if err.get("outer_hresult") == OUTER: return "UNDECIDABLE", "OUTER_ONLY_0x80131501"
        return "UNDECIDABLE", "HRESULT_MISSING"
    if inner == 0x80070003: return "FAIL", "PARENT_MISSING"
    if inner == 0x80070005:
        probe = err.get("target_is_dir")  # pre-probe result recorded with the attempt
        if probe is True: return "FAIL", "TARGET_IS_DIRECTORY"
        if probe is False: return "FAIL", "ACCESS_DENIED"
        return "FAIL", "AMBIGUOUS_0x80070005"
    return "FAIL", "IO_OTHER_0x%08X" % inner
def v04_judge(err):  # what most PS code does: read $_.Exception.HResult
    hr = err.get("outer_hresult") if err else None
    return {0x80070003: "PARENT_MISSING", 0x80070005: "ACCESS_DENIED"}.get(hr, "IO_OTHER") if err else "NO_ERROR"
O = OUTER
ROWS = [  # (id, err, expect)
 ("A_cjk_parent_exists", None, ("PASS", "NO_ERROR")),
 ("B_cjk_parent_missing", {"outer_hresult": O, "inner_type": "DirectoryNotFoundException", "inner_hresult": 0x80070003}, ("FAIL", "PARENT_MISSING")),
 ("C_ascii_parent_missing", {"outer_hresult": O, "inner_type": "DirectoryNotFoundException", "inner_hresult": 0x80070003}, ("FAIL", "PARENT_MISSING")),
 ("D_system32_access_denied_probed", {"outer_hresult": O, "inner_type": "UnauthorizedAccessException", "inner_hresult": 0x80070005, "target_is_dir": False}, ("FAIL", "ACCESS_DENIED")),
 ("E_dir_as_file_probed", {"outer_hresult": O, "inner_type": "UnauthorizedAccessException", "inner_hresult": 0x80070005, "target_is_dir": True}, ("FAIL", "TARGET_IS_DIRECTORY")),
 ("F_0x80070005_no_probe", {"outer_hresult": O, "inner_type": "UnauthorizedAccessException", "inner_hresult": 0x80070005}, ("FAIL", "AMBIGUOUS_0x80070005")),
 ("G_outer_only_captured", {"outer_hresult": O}, ("UNDECIDABLE", "OUTER_ONLY_0x80131501")),
]
if __name__ == "__main__":
    ok = True
    for rid, err, want in ROWS:
        got = judge(err); ok &= got == want
        print(json.dumps({"id": rid, "verdict": got[0], "reason": got[1], "pass": got == want}))
    pr = judge(ROWS[1][1]) == judge(ROWS[2][1]); ok &= pr; print(json.dumps({"gate": "charset_pair_B_eq_C", "pass": pr}))
    # counterexample: outer-HResult judge collapses B/C/D/E into one bucket -> 0 of 4 errors distinguished
    outer = {v04_judge(e) for _, e, _ in ROWS[1:6]}
    c = outer == {"IO_OTHER"}; ok &= c
    print(json.dumps({"counterexample": "outer_hresult_judge_sees_one_bucket", "buckets": sorted(outer), "pass": c}))
    # D and E are indistinguishable without the probe: same type, same inner HResult
    strip = lambda e: {k: v for k, v in e.items() if k != "target_is_dir"}
    s = strip(ROWS[3][1]) == strip(ROWS[4][1]); ok &= s
    print(json.dumps({"gate": "D_E_byte_identical_without_probe", "pass": s}))
    print("ALL_PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
