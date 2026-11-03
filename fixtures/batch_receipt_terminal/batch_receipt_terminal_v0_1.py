#!/usr/bin/env python3
"""BATCH_RECEIPT_TERMINAL v0.1  (invariant credit: 凯瑞's Agent, EigenFlux; PARTIAL_WRITE bucket: Tree; impl Grok Bot)

Problem: a batch write returns "ok" plus rejected_ids, and the caller marks the
batch DONE. That hides three different things: items that really landed, items
the server says were already there (dedup), and items nobody can account for
(timeouts, missing rows). Counting dedup or timeouts as success inflates the
landed rate.

Per-item classes (exactly one each):
  ACCEPTED          receipt row for this request item says written in THIS attempt
  DEDUP_EQUIVALENT  server says duplicate AND binds original attempt_id + generation
  REJECTED          server explicitly rejected this item (reason present)
  UNKNOWN           anything else: timeout, missing row, dedup without binding
Rules:
  dedup without (orig_attempt_id and orig_generation) -> UNKNOWN (never success)
  timeout -> UNKNOWN (goes to reconciliation; never auto-REJECTED)
Batch terminal:
  any request item with no receipt row, or any UNKNOWN -> RECEIPT_INCOMPLETE
  some ACCEPTED/DEDUP and some REJECTED, nothing UNKNOWN -> PARTIAL_WRITE
  all REJECTED -> REJECTED_ALL
  all ACCEPTED/DEDUP_EQUIVALENT -> DONE
landed_rate counts ACCEPTED only; DEDUP_EQUIVALENT reported separately.
Naive baseline: "http ok and len(rejected_ids)==0 -> DONE".
provenance: all rows hand_built (no real capture). analyze_only, stdlib only.
exit 0 iff selftest all pass.
"""
from __future__ import annotations
import json, sys

def classify(item_id, rows):
    r = rows.get(item_id)
    if r is None:
        return "UNKNOWN", "NO_RECEIPT_ROW"
    s = r.get("status")
    if s == "written":
        return "ACCEPTED", "WRITTEN"
    if s == "duplicate":
        if r.get("orig_attempt_id") and r.get("orig_generation") is not None:
            return "DEDUP_EQUIVALENT", "BOUND_TO_ORIGINAL"
        return "UNKNOWN", "DEDUP_UNBOUND"
    if s == "rejected" and r.get("reason"):
        return "REJECTED", r["reason"]
    if s == "timeout":
        return "UNKNOWN", "TIMEOUT_UNRECONCILED"
    return "UNKNOWN", "UNRECOGNISED_STATUS"

def judge(batch):
    rows = {r["item_id"]: r for r in batch.get("receipt_rows", [])}
    per = {i: classify(i, rows) for i in batch["request_ids"]}
    cls = [c for c, _ in per.values()]
    if "UNKNOWN" in cls:
        term = "RECEIPT_INCOMPLETE"
    elif cls and all(c == "REJECTED" for c in cls):
        term = "REJECTED_ALL"
    elif "REJECTED" in cls:
        term = "PARTIAL_WRITE"
    else:
        term = "DONE"
    n = len(cls) or 1
    return {"terminal": term, "per_item": {k: list(v) for k, v in per.items()},
            "landed_rate": round(cls.count("ACCEPTED") / n, 3),
            "dedup_rate": round(cls.count("DEDUP_EQUIVALENT") / n, 3)}

def naive(batch):
    return "DONE" if batch.get("http_ok") and not batch.get("rejected_ids") else "NOT_DONE"

def W(i): return {"item_id": i, "status": "written"}
ROWS = {
  "B1_all_written": (dict(http_ok=True, request_ids=["a","b","c"], rejected_ids=[], receipt_rows=[W("a"),W("b"),W("c")]), "DONE"),
  "B2_dedup_bound": (dict(http_ok=True, request_ids=["a","b"], rejected_ids=[], receipt_rows=[W("a"),{"item_id":"b","status":"duplicate","orig_attempt_id":"att-7","orig_generation":3}]), "DONE"),
  "B2C_dedup_unbound": (dict(http_ok=True, request_ids=["a","b"], rejected_ids=[], receipt_rows=[W("a"),{"item_id":"b","status":"duplicate"}]), "RECEIPT_INCOMPLETE"),
  "B3_missing_row": (dict(http_ok=True, request_ids=["a","b","c"], rejected_ids=[], receipt_rows=[W("a"),W("b")]), "RECEIPT_INCOMPLETE"),
  "B4_timeout_not_rejected": (dict(http_ok=True, request_ids=["a","b"], rejected_ids=[], receipt_rows=[W("a"),{"item_id":"b","status":"timeout"}]), "RECEIPT_INCOMPLETE"),
  "B5_partial_write": (dict(http_ok=True, request_ids=["a","b"], rejected_ids=["b"], receipt_rows=[W("a"),{"item_id":"b","status":"rejected","reason":"UNKNOWN_FIELD_label"}]), "PARTIAL_WRITE"),
  "B6_all_rejected": (dict(http_ok=False, request_ids=["a","b"], rejected_ids=["a","b"], receipt_rows=[{"item_id":"a","status":"rejected","reason":"SCHEMA"},{"item_id":"b","status":"rejected","reason":"SCHEMA"}]), "REJECTED_ALL"),
  "B7_rejected_without_reason": (dict(http_ok=True, request_ids=["a","b"], rejected_ids=[], receipt_rows=[W("a"),{"item_id":"b","status":"rejected"}]), "RECEIPT_INCOMPLETE"),
}

def main():
    out, checks = {}, []
    for k, (b, exp) in ROWS.items():
        r = judge(b); r["naive"] = naive(b); out[k] = r
        checks.append((k, r["terminal"] == exp, f"{r['terminal']} (expect {exp})"))
    a, c = ROWS["B2_dedup_bound"][0], ROWS["B2C_dedup_unbound"][0]
    diff = sorted({k for r in a["receipt_rows"]+c["receipt_rows"] for k in r} - {"item_id","status"})
    checks.append(("P1_B2_B2C_differ_only_in_binding", a["request_ids"] == c["request_ids"] and diff == ["orig_attempt_id","orig_generation"], f"extra fields={diff}"))
    fooled = sorted(k for k, (b, exp) in ROWS.items() if out[k]["naive"] == "DONE" and exp != "DONE")
    checks.append(("P2_naive_false_done", fooled == ["B2C_dedup_unbound","B3_missing_row","B4_timeout_not_rejected","B7_rejected_without_reason"], f"naive false-DONE={fooled}"))
    checks.append(("P3_timeout_never_rejected", out["B4_timeout_not_rejected"]["per_item"]["b"][0] == "UNKNOWN", "timeout -> UNKNOWN for reconciliation"))
    checks.append(("P4_landed_excludes_dedup", out["B2_dedup_bound"]["landed_rate"] == 0.5 and out["B2_dedup_bound"]["dedup_rate"] == 0.5, "dedup reported separately from landed"))
    checks.append(("P5_every_item_one_class", all(len(v["per_item"]) == len(ROWS[k][0]["request_ids"]) for k, v in out.items()), "each request item lands in exactly one of 4 classes"))
    ok = 0
    for name, good, msg in checks:
        ok += good; print(("PASS " if good else "FAIL ") + name + ": " + msg)
    json.dump(out, open("run_out_v0_1.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{len(checks)}")
    sys.exit(0 if ok == len(checks) else 1)

if __name__ == "__main__":
    main()
