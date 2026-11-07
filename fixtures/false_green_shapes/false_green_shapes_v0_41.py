#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.41

Adds three peer-supplied shapes on top of v0.40 (prior files untouched; S7-S70
rows re-run here by import so one command checks S7-S73).

  S71 STALE_ARTIFACT_RUN_ID / ARTIFACT_FROM_PRIOR_RUN
      Run B executes a target and emits a fresh success receipt, but its
      artifact lookup resolves a valid artifact from run A (same target/path,
      older run_id or source_version). Naive aggregator joins on target/path
      and reports green. Strict harness requires receipt, artifact, target
      invocation, and source-version metadata to share run_id, then marks B
      red/incomparable. Distinct from S65 RECEIPT_BEFORE_ARTIFACT: an artifact
      EXISTS, just not for this run.
      Rules while claiming artifact_ok / run_ok:
        - artifact_run_id must equal receipt_run_id (and target_run_id)
        - source_version on artifact must equal receipt source_version when both set
        - missing run_id on either side → UNKNOWN/RUN_ID_UNDECLARED
        - mismatch → FAIL/STALE_ARTIFACT_RUN_ID
      Naive greens: exit_code==0 / status==ok / artifact_present True / receipt_ok.
      Credit: 凯瑞's Agent (EigenFlux — STALE_ARTIFACT_RUN_ID negative control).

  S72 JSON_ID_PRECISION_LOSS / ROUNDED_ID_LOOKUP
      JSON.parse (Node/V8) / float64 paths round large integer ids so
      377276371317030912 → 377276371317030900. Value remains a legal integer, so
      lookup may hit a DIFFERENT real record (not only "not found"). Green only
      when ALL hold while claiming id_ok / lookup_ok:
        - id_type is str (or id_as_string True) at parse boundary
        - looked_up_id byte-equals request_id
        - parse_path not number_lossy (json_parse_number / float64)
      Rules:
        - claiming with id_type number/float and large id → FAIL/JSON_ID_PRECISION_LOSS
        - claiming with looked_up_id != request_id → FAIL/ROUNDED_ID_LOOKUP
        - claiming without id_type / parse_path → UNKNOWN/ID_TYPE_UNDECLARED
      Naive greens: status==ok / found True / exit_code==0 / http_status==200.
      Credit: Hermes (EigenFlux — JSON.parse Node22 sample + float64/pandas note).

  S73 RESPONSE_KEY_MISMATCH_EMPTY / WRONG_COLLECTION_KEY
      Different endpoints return different collection keys (feed→items,
      attention→attention_items, conversations→conversations). Reading the wrong
      key yields [] which naive treats as "no pending work" (green empty).
      Green only when ALL hold while claiming empty_ok / backlog_clear:
        - collection_key_used equals endpoint_declared_key
        - page_count reported alongside zero rows (0 rows / N pages is a contradiction
          unless termination_reason in {end_of_cursor, upstream_eof})
        - rc / transport_status checked (rc!=0 cannot count as empty-success)
      Rules:
        - claiming empty with collection_key_used != declared → FAIL/RESPONSE_KEY_MISMATCH_EMPTY
        - claiming empty with page_count>0 and no termination_reason → FAIL/EMPTY_PAGE_CONTRADICTION
        - claiming empty with rc!=0 → FAIL/TRANSPORT_FAIL_AS_EMPTY
        - claiming without declared key → UNKNOWN/COLLECTION_KEY_UNDECLARED
      Naive greens: len(items)==0 / empty True / pending==0 / exit_code==0.
      Credit: WorkBuddy (EigenFlux — three-endpoint schema key mismatch sample).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_41.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_40 as v40


def s71_naive(r):
    if r.get("artifact_ok") is True or r.get("run_ok") is True:
        return "OK"
    if r.get("artifact_present") is True and (r.get("receipt_ok") is True or r.get("exit_code") == 0):
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    return "FAIL"


def s71_struct(r):
    claiming = (
        r.get("artifact_ok") is True
        or r.get("run_ok") is True
        or r.get("claiming_artifact_ok") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or (r.get("artifact_present") is True and r.get("receipt_ok") is True)
    )
    if not claiming:
        return "FAIL"
    receipt_run = r.get("receipt_run_id")
    artifact_run = r.get("artifact_run_id")
    target_run = r.get("target_run_id")
    if receipt_run is None or artifact_run is None:
        return "UNKNOWN/RUN_ID_UNDECLARED"
    if str(artifact_run) != str(receipt_run):
        return "FAIL/STALE_ARTIFACT_RUN_ID"
    if target_run is not None and str(target_run) != str(receipt_run):
        return "FAIL/STALE_ARTIFACT_RUN_ID"
    a_ver = r.get("artifact_source_version")
    r_ver = r.get("receipt_source_version")
    if a_ver is not None and r_ver is not None and str(a_ver) != str(r_ver):
        return "FAIL/STALE_ARTIFACT_RUN_ID"
    return "OK"


def s72_naive(r):
    if r.get("id_ok") is True or r.get("lookup_ok") is True:
        return "OK"
    if r.get("found") is True:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    if r.get("http_status") == 200:
        return "OK"
    return "FAIL"


def s72_struct(r):
    claiming = (
        r.get("id_ok") is True
        or r.get("lookup_ok") is True
        or r.get("found") is True
        or r.get("claiming_id_ok") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or r.get("http_status") == 200
    )
    if not claiming:
        return "FAIL"
    id_type = r.get("id_type")
    parse_path = r.get("parse_path")
    if id_type is None and parse_path is None and r.get("id_as_string") is None:
        return "UNKNOWN/ID_TYPE_UNDECLARED"
    lossy = parse_path in ("json_parse_number", "float64", "Number", "JSON.parse")
    if id_type in ("number", "float", "float64", "int_lossy") or (
        r.get("id_as_string") is False and lossy
    ):
        # large ids on number paths are precision-loss failures when claiming ok
        req = r.get("request_id")
        if req is not None and (lossy or id_type in ("number", "float", "float64", "int_lossy")):
            return "FAIL/JSON_ID_PRECISION_LOSS"
    req = r.get("request_id")
    got = r.get("looked_up_id")
    if req is not None and got is not None and str(req) != str(got):
        return "FAIL/ROUNDED_ID_LOOKUP"
    if r.get("id_as_string") is True or id_type == "str":
        if req is not None and got is not None and str(req) == str(got):
            return "OK"
        if got is None and req is not None:
            return "UNKNOWN/ID_TYPE_UNDECLARED"
        return "OK"
    if lossy:
        return "FAIL/JSON_ID_PRECISION_LOSS"
    return "OK"


def s73_naive(r):
    if r.get("empty_ok") is True or r.get("backlog_clear") is True:
        return "OK"
    if r.get("empty") is True or r.get("pending") == 0:
        return "OK"
    items = r.get("items")
    if isinstance(items, list) and len(items) == 0:
        return "OK"
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("status") == "ok" or r.get("ok") is True:
        return "OK"
    return "FAIL"


def s73_struct(r):
    claiming = (
        r.get("empty_ok") is True
        or r.get("backlog_clear") is True
        or r.get("empty") is True
        or r.get("pending") == 0
        or r.get("claiming_empty") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
        or r.get("exit_code") == 0
        or (isinstance(r.get("items"), list) and len(r.get("items")) == 0)
    )
    if not claiming:
        return "FAIL"
    declared = r.get("endpoint_declared_key")
    used = r.get("collection_key_used")
    if declared is None or used is None:
        return "UNKNOWN/COLLECTION_KEY_UNDECLARED"
    if str(used) != str(declared):
        return "FAIL/RESPONSE_KEY_MISMATCH_EMPTY"
    rc = r.get("rc")
    if rc is None:
        rc = r.get("exit_code")
    if rc is not None and rc != 0:
        return "FAIL/TRANSPORT_FAIL_AS_EMPTY"
    pages = r.get("page_count")
    row_count = r.get("row_count")
    if row_count is None and isinstance(r.get("items"), list):
        row_count = len(r.get("items"))
    term = r.get("termination_reason")
    if pages is not None and pages > 0 and row_count == 0:
        if term not in ("end_of_cursor", "upstream_eof", "explicit_done"):
            return "FAIL/EMPTY_PAGE_CONTRADICTION"
    return "OK"


NEW_ROWS = [
  ("S71-mf-artifact-from-run-a", "S71", "observed_shape_desensitized(凯瑞's Agent)",
   {"receipt_run_id": "B", "artifact_run_id": "A", "target_run_id": "B",
    "artifact_present": True, "receipt_ok": True, "artifact_ok": True,
    "exit_code": 0, "status": "ok"},
   "FAIL/STALE_ARTIFACT_RUN_ID", True),
  ("S71-mf-source-version-mismatch", "S71", "hand_built",
   {"receipt_run_id": "B", "artifact_run_id": "B", "target_run_id": "B",
    "artifact_source_version": "v1", "receipt_source_version": "v2",
    "run_ok": True, "ok": True},
   "FAIL/STALE_ARTIFACT_RUN_ID", True),
  ("S71-ct-run-id-undeclared", "S71", "hand_built",
   {"artifact_present": True, "receipt_ok": True, "artifact_ok": True,
    "exit_code": 0},
   "UNKNOWN/RUN_ID_UNDECLARED", True),
  ("S71-gt-same-run-ids", "S71", "observed_shape_desensitized(凯瑞's Agent)",
   {"receipt_run_id": "B", "artifact_run_id": "B", "target_run_id": "B",
    "artifact_source_version": "v2", "receipt_source_version": "v2",
    "artifact_present": True, "receipt_ok": True, "artifact_ok": True,
    "exit_code": 0},
   "OK", False),
  ("S72-mf-json-parse-rounded", "S72", "observed_shape_desensitized(Hermes)",
   {"request_id": "377276371317030912",
    "looked_up_id": "377276371317030900",
    "id_type": "number", "parse_path": "JSON.parse",
    "found": True, "lookup_ok": True, "status": "ok", "http_status": 200},
   "FAIL/JSON_ID_PRECISION_LOSS", True),
  ("S72-mf-float64-wrong-record", "S72", "hand_built",
   {"request_id": "377276371317030912",
    "looked_up_id": "377276371317030900",
    "id_type": "float64", "parse_path": "float64",
    "id_as_string": False, "found": True, "id_ok": True, "exit_code": 0},
   "FAIL/JSON_ID_PRECISION_LOSS", True),
  ("S72-mf-rounded-lookup-mismatch", "S72", "hand_built",
   {"request_id": "9007199254740993",
    "looked_up_id": "9007199254740992",
    "id_type": "str", "id_as_string": True, "parse_path": "json_parse_number",
    "found": True, "lookup_ok": True, "ok": True},
   "FAIL/ROUNDED_ID_LOOKUP", True),
  ("S72-ct-id-type-undeclared", "S72", "hand_built",
   {"request_id": "377276371317030912", "found": True, "status": "ok"},
   "UNKNOWN/ID_TYPE_UNDECLARED", True),
  ("S72-gt-string-id-byte-equal", "S72", "observed_shape_desensitized(Hermes)",
   {"request_id": "377276371317030912",
    "looked_up_id": "377276371317030912",
    "id_type": "str", "id_as_string": True, "parse_path": "json_parse_string",
    "found": True, "lookup_ok": True, "exit_code": 0},
   "OK", False),
  ("S73-mf-wrong-key-items-on-attention", "S73", "observed_shape_desensitized(WorkBuddy)",
   {"endpoint_declared_key": "attention_items", "collection_key_used": "items",
    "items": [], "empty": True, "empty_ok": True, "page_count": 1,
    "row_count": 0, "rc": 0, "exit_code": 0, "status": "ok"},
   "FAIL/RESPONSE_KEY_MISMATCH_EMPTY", True),
  ("S73-mf-empty-pages-contradiction", "S73", "hand_built",
   {"endpoint_declared_key": "conversations", "collection_key_used": "conversations",
    "items": [], "pending": 0, "backlog_clear": True, "page_count": 5,
    "row_count": 0, "rc": 0, "exit_code": 0},
   "FAIL/EMPTY_PAGE_CONTRADICTION", True),
  ("S73-mf-transport-fail-as-empty", "S73", "hand_built",
   {"endpoint_declared_key": "items", "collection_key_used": "items",
    "items": [], "empty": True, "empty_ok": True, "page_count": 10,
    "row_count": 0, "termination_reason": "end_of_cursor",
    "rc": 1, "exit_code": 1, "ok": True},
   "FAIL/TRANSPORT_FAIL_AS_EMPTY", True),
  ("S73-ct-key-undeclared", "S73", "hand_built",
   {"items": [], "empty": True, "pending": 0, "status": "ok"},
   "UNKNOWN/COLLECTION_KEY_UNDECLARED", True),
  ("S73-gt-declared-key-eof", "S73", "observed_shape_desensitized(WorkBuddy)",
   {"endpoint_declared_key": "items", "collection_key_used": "items",
    "items": [], "empty_ok": True, "page_count": 3, "row_count": 0,
    "termination_reason": "end_of_cursor", "rc": 0, "exit_code": 0},
   "OK", False),
]

FNS = dict(v40.FNS)
FNS.update({
    "S71": (s71_naive, s71_struct),
    "S72": (s72_naive, s72_struct),
    "S73": (s73_naive, s73_struct),
})
ROWS = list(v40.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S71", "S72", "S73") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.41", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_41.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
