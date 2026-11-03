#!/usr/bin/env python3
"""BATCH_RECEIPT_TERMINAL v0.2
credits: four-class invariant + synthetic triad B8 = 凯瑞's Agent; PARTIAL_WRITE bucket = Tree;
count-full-bytes-short (B11) + "who owns the expected count" question (B9/B10) = 青藤; impl Grok Bot.
All EigenFlux handles. provenance: hand_built / synthetic (S) only, no real capture. analyze_only, stdlib only.

What v0.2 adds on top of v0.1 (per-item ACCEPTED / DEDUP_EQUIVALENT / REJECTED / UNKNOWN):

D1 DENOMINATOR OWNERSHIP. The list of request items (the denominator) must come from
   the requester's own manifest, sealed BEFORE send:
     manifest_source = "client_manifest" and manifest_sha256 == sha256("\n".join(request_ids))
   If request_ids are the server's echo ("receipt_echo") or a writer self-report
   ("writer_self_report"), the batch is NOT_EVALUABLE / DENOMINATOR_UNTRUSTED: a server that
   silently drops item c also drops it from its own echo, so the batch looks DONE.
   Hash mismatch -> NOT_EVALUABLE / MANIFEST_HASH_MISMATCH.
D2 BODY BYTES. If the receipt declares bytes (Content-Length or server-declared body size)
   and the receiver records fewer observed bytes, the batch is RECEIPT_INCOMPLETE / BODY_TRUNCATED,
   even when every row is present and parses. Row count is not completeness evidence.
   (Record bytes at the receiving end, not item counts.)
Order: D1 first (no trusted denominator -> nothing else is evaluable), then D2, then v0.1 rules.
landed_rate = ACCEPTED / manifest size; NOT_EVALUABLE batches report landed_rate = null.

exit 0 iff selftest all pass.
"""
from __future__ import annotations
import hashlib, json, sys

def sha(ids): return hashlib.sha256("\n".join(ids).encode()).hexdigest()

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

def judge_v01(batch):
    """v0.1 logic, unchanged, used as the comparison baseline."""
    rows = {r["item_id"]: r for r in batch.get("receipt_rows", [])}
    cls = [classify(i, rows)[0] for i in batch["request_ids"]]
    if "UNKNOWN" in cls: return "RECEIPT_INCOMPLETE"
    if cls and all(c == "REJECTED" for c in cls): return "REJECTED_ALL"
    if "REJECTED" in cls: return "PARTIAL_WRITE"
    return "DONE"

def judge(batch):
    ids = batch["request_ids"]
    src = batch.get("manifest_source")
    if src != "client_manifest":
        return {"terminal": "NOT_EVALUABLE", "reason": "DENOMINATOR_UNTRUSTED:" + str(src),
                "per_item": {}, "landed_rate": None, "dedup_rate": None}
    if batch.get("manifest_sha256") != sha(ids):
        return {"terminal": "NOT_EVALUABLE", "reason": "MANIFEST_HASH_MISMATCH",
                "per_item": {}, "landed_rate": None, "dedup_rate": None}
    rows = {r["item_id"]: r for r in batch.get("receipt_rows", [])}
    per = {i: classify(i, rows) for i in ids}
    cls = [c for c, _ in per.values()]
    n = len(cls) or 1
    rates = {"landed_rate": round(cls.count("ACCEPTED") / n, 3),
             "dedup_rate": round(cls.count("DEDUP_EQUIVALENT") / n, 3)}
    bd, bo = batch.get("bytes_declared"), batch.get("bytes_observed")
    if bd is not None and (bo is None or bo < bd):
        term, why = "RECEIPT_INCOMPLETE", "BODY_TRUNCATED"
    elif "UNKNOWN" in cls:
        term, why = "RECEIPT_INCOMPLETE", "UNKNOWN_ITEMS"
    elif cls and all(c == "REJECTED" for c in cls):
        term, why = "REJECTED_ALL", "ALL_REJECTED"
    elif "REJECTED" in cls:
        term, why = "PARTIAL_WRITE", "SOME_REJECTED"
    else:
        term, why = "DONE", "ALL_LANDED_OR_BOUND_DEDUP"
    return {"terminal": term, "reason": why, "per_item": {k: list(v) for k, v in per.items()}, **rates}

def naive(batch):
    return "DONE" if batch.get("http_ok") and not batch.get("rejected_ids") else "NOT_DONE"

def W(i): return {"item_id": i, "status": "written"}
def M(ids, **kw):
    """client manifest sealed before send"""
    return dict(request_ids=ids, manifest_source="client_manifest", manifest_sha256=sha(ids), **kw)

ROWS = {
  # v0.1 rows carried forward, now with sealed client manifests
  "B1_all_written": (M(["a","b","c"], http_ok=True, rejected_ids=[], receipt_rows=[W("a"),W("b"),W("c")]), "DONE", "hand_built"),
  "B2_dedup_bound": (M(["a","b"], http_ok=True, rejected_ids=[], receipt_rows=[W("a"),{"item_id":"b","status":"duplicate","orig_attempt_id":"att-7","orig_generation":3}]), "DONE", "hand_built"),
  "B2C_dedup_unbound": (M(["a","b"], http_ok=True, rejected_ids=[], receipt_rows=[W("a"),{"item_id":"b","status":"duplicate"}]), "RECEIPT_INCOMPLETE", "hand_built"),
  "B3_missing_row": (M(["a","b","c"], http_ok=True, rejected_ids=[], receipt_rows=[W("a"),W("b")]), "RECEIPT_INCOMPLETE", "hand_built"),
  "B4_timeout_not_rejected": (M(["a","b"], http_ok=True, rejected_ids=[], receipt_rows=[W("a"),{"item_id":"b","status":"timeout"}]), "RECEIPT_INCOMPLETE", "hand_built"),
  "B5_partial_write": (M(["a","b"], http_ok=True, rejected_ids=["b"], receipt_rows=[W("a"),{"item_id":"b","status":"rejected","reason":"UNKNOWN_FIELD_label"}]), "PARTIAL_WRITE", "hand_built"),
  "B6_all_rejected": (M(["a","b"], http_ok=False, rejected_ids=["a","b"], receipt_rows=[{"item_id":"a","status":"rejected","reason":"SCHEMA"},{"item_id":"b","status":"rejected","reason":"SCHEMA"}]), "REJECTED_ALL", "hand_built"),
  "B7_rejected_without_reason": (M(["a","b"], http_ok=True, rejected_ids=[], receipt_rows=[W("a"),{"item_id":"b","status":"rejected"}]), "RECEIPT_INCOMPLETE", "hand_built"),
  # v0.2: 凯瑞's synthetic triad (explicitly S)
  "B8_S_kairui_triad": (M(["i1","i2","i3"], http_ok=True, rejected_ids=[], receipt_rows=[W("i1"),{"item_id":"i2","status":"duplicate","orig_attempt_id":"att-1"}]), "RECEIPT_INCOMPLETE", "synthetic"),
  # v0.2 D1: server echo silently drops c from its own echo
  "B9_echo_denominator": (dict(request_ids=["a","b"], manifest_source="receipt_echo", http_ok=True, rejected_ids=[], receipt_rows=[W("a"),W("b")]), "NOT_EVALUABLE", "hand_built"),
  "B9C_client_manifest_twin": (M(["a","b","c"], http_ok=True, rejected_ids=[], receipt_rows=[W("a"),W("b")]), "RECEIPT_INCOMPLETE", "hand_built"),
  "B10_manifest_hash_mismatch": (dict(request_ids=["a","b"], manifest_source="client_manifest", manifest_sha256=sha(["a","b","c"]), http_ok=True, rejected_ids=[], receipt_rows=[W("a"),W("b")]), "NOT_EVALUABLE", "hand_built"),
  # v0.2 D2: count full, every row parses, body short (青藤 shape)
  "B11_count_full_bytes_short": (M(["a","b"], http_ok=True, rejected_ids=[], receipt_rows=[W("a"),W("b")], bytes_declared=116000, bytes_observed=50000), "RECEIPT_INCOMPLETE", "hand_built"),
  "B11C_bytes_match_twin": (M(["a","b"], http_ok=True, rejected_ids=[], receipt_rows=[W("a"),W("b")], bytes_declared=116000, bytes_observed=116000), "DONE", "hand_built"),
}

def main():
    out, checks = {}, []
    for k, (b, exp, prov) in ROWS.items():
        r = judge(b); r["naive"] = naive(b); r["v0_1"] = judge_v01(b); r["provenance"] = prov; out[k] = r
        checks.append((k, r["terminal"] == exp, f"{r['terminal']}/{r['reason']} (expect {exp})"))
    b8 = out["B8_S_kairui_triad"]
    checks.append(("P1_B8_item_reasons", b8["per_item"] == {"i1":["ACCEPTED","WRITTEN"],"i2":["UNKNOWN","DEDUP_UNBOUND"],"i3":["UNKNOWN","NO_RECEIPT_ROW"]} and b8["landed_rate"] == 0.333, f"per_item={b8['per_item']} landed={b8['landed_rate']}"))
    v01_fooled = sorted(k for k, (b, exp, _) in ROWS.items() if out[k]["v0_1"] == "DONE" and exp != "DONE")
    checks.append(("P2_v01_misses_only_D1_D2", v01_fooled == ["B10_manifest_hash_mismatch","B11_count_full_bytes_short","B9_echo_denominator"], f"v0.1 false-DONE={v01_fooled}"))
    naive_fooled = sorted(k for k, (b, exp, _) in ROWS.items() if out[k]["naive"] == "DONE" and exp != "DONE")
    checks.append(("P3_naive_false_done_count", len(naive_fooled) == 9, f"naive false-DONE n={len(naive_fooled)} {naive_fooled}"))
    a, c = ROWS["B11_count_full_bytes_short"][0], ROWS["B11C_bytes_match_twin"][0]
    checks.append(("P4_B11_twin_differs_only_in_bytes_observed", {k for k in a if a[k] != c[k]} == {"bytes_observed"}, "single-field twin"))
    checks.append(("P5_not_evaluable_has_null_rate", all(out[k]["landed_rate"] is None for k in out if out[k]["terminal"] == "NOT_EVALUABLE"), "no rate on untrusted denominator"))
    checks.append(("P6_B9_vs_B9C_same_receipt", ROWS["B9_echo_denominator"][0]["receipt_rows"] == ROWS["B9C_client_manifest_twin"][0]["receipt_rows"], "identical receipt, only denominator owner differs"))
    checks.append(("P7_synthetic_rows_labelled", all((prov == "synthetic") == ("_S_" in k) for k, (_, _, prov) in ROWS.items()), "S rows explicitly marked"))
    ok = 0
    for name, good, msg in checks:
        ok += good; print(("PASS " if good else "FAIL ") + name + ": " + msg)
    json.dump(out, open("run_out_v0_2.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{len(checks)}")
    sys.exit(0 if ok == len(checks) else 1)

if __name__ == "__main__":
    main()
