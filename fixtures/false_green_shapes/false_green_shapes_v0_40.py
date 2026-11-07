#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.40

Adds three peer-supplied shapes on top of v0.39 (prior files untouched; S7-S67
rows re-run here by import so one command checks S7-S70).

  S68 TRY_BUNDLE_PARTIAL / SIBLING_SKIPPED_AS_PASS
      Two (or more) checks bundled in one try/except. One raises; the sibling
      never executes; the report still marks BOTH as passed. Green only when
      ALL hold while claiming checks_ok / all_passed:
        - each check_id has its own executed=true receipt
        - raised_check_id (if any) is NOT marked passed
        - skipped_after_raise check_ids are NOT marked passed
      Rules:
        - claiming all_passed with any check executed=false →
          FAIL/TRY_BUNDLE_PARTIAL
        - claiming all_passed with raised_check_id in passed_ids →
          FAIL/SIBLING_SKIPPED_AS_PASS
        - claiming without per-check executed map →
          UNKNOWN/CHECK_EXEC_MAP_UNDECLARED
      Naive greens: exit_code==0 / status==ok / all_passed True / n_passed==n_checks.
      Credit: 汐 (EigenFlux — 同 try 两条检查、一条抛另一条没跑却双过).

  S69 VERSION_PROBE_TAGS_ONLY / UPDATE_SIGNAL_UNANCHORED
      Version probe only lists remote tags; never compares against installed
      version. So "has_update=true" is the only thing it can say — consecutive
      identical signals with no installed_version / compared_to should reverse
      to broken. Green only when ALL hold while claiming update_checked:
        - installed_version declared
        - remote_version or remote_tags declared
        - compared_to equals installed_version (anchor)
        - has_update reflects remote != installed
      Rules:
        - claiming update_checked / has_update without installed_version →
          FAIL/VERSION_PROBE_TAGS_ONLY
        - claiming has_update with compared_to missing or != installed →
          FAIL/UPDATE_SIGNAL_UNANCHORED
        - identical signal across rounds with no anchor →
          FAIL/STALE_UPDATE_SIGNAL
        - claiming without remote side → UNKNOWN/REMOTE_VERSION_UNDECLARED
      Naive greens: has_update True / tags_fetched True / exit_code==0 / status==ok.
      Credit: 汐 (EigenFlux — 只拉远端标签、从不比对已装版本).

  S70 DENOMINATOR_UNBOUND / PUSHED_DERIVED_EXPECTED
      expected is derived from pushed (expected := pushed) so ratio==1.0 is
      tautological. Basis must come from an independent expected source, not
      from the value under test. Green only when ALL hold while claiming
      ratio_ok / coverage_ok:
        - expected_basis in {independent, external_lock, pinned_spec}
        - expected_basis is NOT pushed_derived / self_derived
        - distribution_lock present when a ratio is claimed (else STALE)
      Rules:
        - claiming ratio_ok with expected_basis pushed_derived/self_derived →
          FAIL/DENOMINATOR_UNBOUND
        - claiming ratio_ok with expected := pushed flag →
          FAIL/DENOMINATOR_UNBOUND
        - claiming ratio_ok without distribution_lock →
          FAIL/STALE_RATIO_UNLOCKED
        - claiming without expected_basis → UNKNOWN/EXPECTED_BASIS_UNDECLARED
      Naive greens: ratio==1.0 / ratio_ok True / coverage==1.0 / exit_code==0.
      Credit: WorkBuddy (EigenFlux — expected:=pushed 注入臂; basis 不得自证).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_40.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_39 as v39


def s68_naive(r):
    if r.get("all_passed") is True or r.get("checks_ok") is True:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    if r.get("n_passed") is not None and r.get("n_checks") is not None:
        if r.get("n_passed") == r.get("n_checks"):
            return "OK"
    return "FAIL"


def s68_struct(r):
    claiming = (
        r.get("all_passed") is True
        or r.get("checks_ok") is True
        or r.get("claiming_all_passed") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or (r.get("n_passed") is not None and r.get("n_checks") is not None
            and r.get("n_passed") == r.get("n_checks"))
    )
    if not claiming:
        return "FAIL"
    exec_map = r.get("check_executed")
    if not isinstance(exec_map, dict) or not exec_map:
        return "UNKNOWN/CHECK_EXEC_MAP_UNDECLARED"
    passed_ids = r.get("passed_ids")
    if passed_ids is None:
        passed_ids = [k for k, v in exec_map.items() if v is True]
    if not isinstance(passed_ids, (list, tuple, set)):
        return "UNKNOWN/CHECK_EXEC_MAP_UNDECLARED"
    passed_set = set(passed_ids)
    for cid, executed in exec_map.items():
        if executed is False and cid in passed_set:
            return "FAIL/TRY_BUNDLE_PARTIAL"
        if executed is not True and cid in passed_set:
            return "FAIL/TRY_BUNDLE_PARTIAL"
    raised = r.get("raised_check_id")
    if raised and raised in passed_set:
        return "FAIL/SIBLING_SKIPPED_AS_PASS"
    skipped = r.get("skipped_after_raise") or []
    if isinstance(skipped, (list, tuple, set)):
        for cid in skipped:
            if cid in passed_set:
                return "FAIL/SIBLING_SKIPPED_AS_PASS"
    return "OK"


def s69_naive(r):
    if r.get("has_update") is True or r.get("tags_fetched") is True:
        return "OK"
    if r.get("update_checked") is True or r.get("probe_ok") is True:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    return "FAIL"


def s69_struct(r):
    claiming = (
        r.get("update_checked") is True
        or r.get("has_update") is True
        or r.get("claiming_update_checked") is True
        or r.get("probe_ok") is True
        or r.get("tags_fetched") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
    )
    if not claiming:
        return "FAIL"
    if "installed_version" not in r:
        return "FAIL/VERSION_PROBE_TAGS_ONLY"
    remote = r.get("remote_version")
    if remote is None:
        tags = r.get("remote_tags")
        if isinstance(tags, (list, tuple)) and tags:
            remote = tags[0]
        else:
            return "UNKNOWN/REMOTE_VERSION_UNDECLARED"
    if "compared_to" not in r:
        return "FAIL/UPDATE_SIGNAL_UNANCHORED"
    if r.get("compared_to") != r.get("installed_version"):
        return "FAIL/UPDATE_SIGNAL_UNANCHORED"
    if r.get("identical_signal_rounds", 0) >= 2 and r.get("has_update") is True:
        # consecutive identical "has update" with no actual version delta
        if remote == r.get("installed_version"):
            return "FAIL/STALE_UPDATE_SIGNAL"
    # consistent claim
    want_update = remote != r.get("installed_version")
    if r.get("has_update") is True and not want_update:
        return "FAIL/STALE_UPDATE_SIGNAL"
    if r.get("has_update") is False and want_update:
        return "FAIL/UPDATE_SIGNAL_UNANCHORED"
    return "OK"


def s70_naive(r):
    if r.get("ratio") == 1.0 or r.get("ratio") == 1:
        return "OK"
    if r.get("ratio_ok") is True or r.get("coverage_ok") is True:
        return "OK"
    if r.get("coverage") == 1.0 or r.get("coverage") == 1:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    return "FAIL"


def s70_struct(r):
    claiming = (
        r.get("ratio_ok") is True
        or r.get("coverage_ok") is True
        or r.get("claiming_ratio_ok") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("ratio") in (1, 1.0)
        or r.get("coverage") in (1, 1.0)
    )
    if not claiming:
        return "FAIL"
    if "expected_basis" not in r:
        return "UNKNOWN/EXPECTED_BASIS_UNDECLARED"
    basis = r.get("expected_basis")
    if basis in ("pushed_derived", "self_derived") or r.get("expected_from_pushed") is True:
        return "FAIL/DENOMINATOR_UNBOUND"
    if basis not in ("independent", "external_lock", "pinned_spec"):
        return "FAIL/DENOMINATOR_UNBOUND"
    if r.get("distribution_lock") is not True and r.get("distribution_lock_present") is not True:
        return "FAIL/STALE_RATIO_UNLOCKED"
    return "OK"


NEW_ROWS = [
  ("S68-mf-sibling-not-executed-marked-pass", "S68", "observed_shape_desensitized(汐)",
   {"check_executed": {"disk": True, "schema": False},
    "passed_ids": ["disk", "schema"], "raised_check_id": "disk",
    "skipped_after_raise": ["schema"], "all_passed": True, "n_passed": 2,
    "n_checks": 2, "exit_code": 0, "status": "ok"},
   "FAIL/TRY_BUNDLE_PARTIAL", True),
  ("S68-mf-raised-still-passed", "S68", "hand_built",
   {"check_executed": {"a": True, "b": True},
    "passed_ids": ["a", "b"], "raised_check_id": "a",
    "claiming_all_passed": True, "ok": True},
   "FAIL/SIBLING_SKIPPED_AS_PASS", True),
  ("S68-ct-exec-map-undeclared", "S68", "hand_built",
   {"all_passed": True, "n_passed": 2, "n_checks": 2, "exit_code": 0},
   "UNKNOWN/CHECK_EXEC_MAP_UNDECLARED", True),
  ("S68-gt-each-executed", "S68", "observed_shape_desensitized(汐)",
   {"check_executed": {"disk": True, "schema": True},
    "passed_ids": ["disk", "schema"], "all_passed": True,
    "n_passed": 2, "n_checks": 2, "exit_code": 0},
   "OK", False),
  ("S69-mf-tags-only-no-installed", "S69", "observed_shape_desensitized(汐)",
   {"remote_tags": ["v1.2.3", "v1.2.2"], "has_update": True,
    "tags_fetched": True, "update_checked": True, "exit_code": 0, "status": "ok"},
   "FAIL/VERSION_PROBE_TAGS_ONLY", True),
  ("S69-mf-unanchored-compared-to", "S69", "hand_built",
   {"installed_version": "1.0.0", "remote_version": "1.1.0",
    "compared_to": "0.9.0", "has_update": True, "probe_ok": True, "ok": True},
   "FAIL/UPDATE_SIGNAL_UNANCHORED", True),
  ("S69-mf-stale-identical-rounds", "S69", "hand_built",
   {"installed_version": "1.0.0", "remote_version": "1.0.0",
    "compared_to": "1.0.0", "has_update": True, "identical_signal_rounds": 3,
    "update_checked": True, "exit_code": 0},
   "FAIL/STALE_UPDATE_SIGNAL", True),
  ("S69-ct-remote-undeclared", "S69", "hand_built",
   {"installed_version": "1.0.0", "compared_to": "1.0.0",
    "update_checked": True, "status": "ok"},
   "UNKNOWN/REMOTE_VERSION_UNDECLARED", True),
  ("S69-gt-anchored-compare", "S69", "observed_shape_desensitized(汐)",
   {"installed_version": "1.0.0", "remote_version": "1.1.0",
    "compared_to": "1.0.0", "has_update": True, "update_checked": True,
    "exit_code": 0},
   "OK", False),
  ("S70-mf-expected-from-pushed", "S70", "observed_shape_desensitized(WorkBuddy)",
   {"expected_basis": "pushed_derived", "expected_from_pushed": True,
    "ratio": 1.0, "ratio_ok": True, "distribution_lock": True,
    "exit_code": 0, "status": "ok"},
   "FAIL/DENOMINATOR_UNBOUND", True),
  ("S70-mf-self-derived", "S70", "hand_built",
   {"expected_basis": "self_derived", "coverage": 1.0, "coverage_ok": True,
    "distribution_lock_present": True, "ok": True},
   "FAIL/DENOMINATOR_UNBOUND", True),
  ("S70-mf-stale-no-lock", "S70", "hand_built",
   {"expected_basis": "independent", "ratio": 1.0, "ratio_ok": True,
    "distribution_lock": False, "exit_code": 0},
   "FAIL/STALE_RATIO_UNLOCKED", True),
  ("S70-ct-basis-undeclared", "S70", "hand_built",
   {"ratio": 1.0, "ratio_ok": True, "distribution_lock": True, "status": "ok"},
   "UNKNOWN/EXPECTED_BASIS_UNDECLARED", True),
  ("S70-gt-independent-locked", "S70", "observed_shape_desensitized(WorkBuddy)",
   {"expected_basis": "independent", "ratio": 1.0, "ratio_ok": True,
    "distribution_lock": True, "exit_code": 0, "status": "ok"},
   "OK", False),
]

FNS = dict(v39.FNS)
FNS.update({
    "S68": (s68_naive, s68_struct),
    "S69": (s69_naive, s69_struct),
    "S70": (s70_naive, s70_struct),
})
ROWS = list(v39.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S68", "S69", "S70") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.40", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_40.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
