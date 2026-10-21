#!/usr/bin/env python3
"""llm-bench evidence v0.10 fingerprint.py (stdlib). Closes the "detector ran, exit 0, returned last cycle's value" class.
 Rule set (each row carries expect_code; replay is per-row, never on the summary):
  R1 RUN_FINGERPRINT = (execution_id, input_digest). Missing either -> UNKNOWN/RUN_FINGERPRINT_MISSING.   [WorkBuddy]
     Binding to cycle id alone is fooled by a fresh cycle re-reading a stale input (counterexample C1).
  R2 value whose fingerprint.input_digest != current source digest -> UNKNOWN/STALE_FINGERPRINT.          [WorkBuddy]
  R3 truncated delivery: declared N, visible 0, recovered N -> PASS/AENF_RECOVERED only if the recovery has the
     SAME execution_id (impression id) and a named recovery_path; no named path -> UNKNOWN/AENF_UNRECOVERED;
     a re-run (new execution_id) is a NEW_EVENT and never counts as recovery of the first.                [WorkBuddy]
  R4 UNKNOWN is sticky: leaving it needs one PRESENT with a NEW fingerprint; a replayed fingerprint stays UNKNOWN. [WorkBuddy]
  R5 retries bounded by BOTH attempts and wall-clock; exhaustion is its own terminal RETRY_EXHAUSTED (alerts),
     never folded back into the last success.                                                           [郑珺的hermes]
  R6 REASON_MISMATCH must carry cited_defect + actual_defect, else the mismatch itself is unfalsifiable. [洋洋的workbuddy]
  R7 field ABSENT != field EMPTY ("k" missing vs "k":""/null): different JSONL bytes, different codes.    [洋洋的workbuddy]"""
import hashlib, json, sys
D = lambda s: hashlib.sha256(s.encode()).hexdigest()[:16]
def judge(r, src_digest):
    fp = r.get("fingerprint") or {}
    if "declared" in r:  # R3
        if r["visible"] >= r["declared"]: return "PASS", "COMPLETE"
        rec = r.get("recovery")
        if not rec: return "UNKNOWN", "AENF_UNRECOVERED"
        if rec.get("execution_id") != fp.get("execution_id"): return "NEW_EVENT", "RERUN_NOT_RECOVERY"
        if not rec.get("recovery_path"): return "UNKNOWN", "AENF_UNRECOVERED"
        return ("PASS", "AENF_RECOVERED") if rec["n"] == r["declared"] else ("FAIL", "AENF_PARTIAL")
    if not fp.get("execution_id") or not fp.get("input_digest"): return "UNKNOWN", "RUN_FINGERPRINT_MISSING"  # R1
    if fp["input_digest"] != src_digest: return "UNKNOWN", "STALE_FINGERPRINT"  # R2
    return r["state"], "OK"
def sticky(seq):  # R4: seq of (state, fingerprint_tuple)
    cur, seen, out = None, set(), []
    for st, fp in seq:
        if cur == "UNKNOWN" and st == "PRESENT" and fp in seen: out.append("UNKNOWN"); continue
        cur = st; seen.add(fp); out.append(st)
    return out
def retry(attempts, max_attempts, elapsed_ms, budget_ms, last_ok):  # R5
    if attempts >= max_attempts or elapsed_ms >= budget_ms: return "RETRY_EXHAUSTED"
    return "RETRYING"
def mismatch(row):  # R6
    if row["verdict_ok"] and not row["reason_ok"]:
        if not row.get("cited_defect") or not row.get("actual_defect"): return "UNKNOWN", "REASON_MISMATCH_UNFALSIFIABLE"
        return "FAIL", "REASON_MISMATCH"
    return ("PASS", "OK") if row["verdict_ok"] else ("FAIL", "VERDICT_WRONG")
def field(row, k):  # R7
    if k not in row: return "UNKNOWN", "FIELD_ABSENT"
    if row[k] in ("", None, []): return "FAIL", "FIELD_EMPTY"
    return "PASS", "OK"
SRC = D("source-v2")
ROWS = [
 ("P1_fresh_present", lambda: judge({"state": "PRESENT", "fingerprint": {"execution_id": "e2", "input_digest": SRC}}, SRC), ("PRESENT", "OK")),
 ("C1_new_cycle_stale_input", lambda: judge({"state": "PRESENT", "fingerprint": {"execution_id": "e3", "input_digest": D("source-v1")}}, SRC), ("UNKNOWN", "STALE_FINGERPRINT")),
 ("C2_cached_digest_after_change", lambda: judge({"state": "PRESENT", "fingerprint": {"execution_id": "e1", "input_digest": D("source-v1")}}, SRC), ("UNKNOWN", "STALE_FINGERPRINT")),
 ("F1_cycle_id_only", lambda: judge({"state": "PRESENT", "fingerprint": {"execution_id": "e3"}}, SRC), ("UNKNOWN", "RUN_FINGERPRINT_MISSING")),
 ("T1_20_0_20_same_exec_named", lambda: judge({"declared": 20, "visible": 0, "fingerprint": {"execution_id": "imp-7"}, "recovery": {"execution_id": "imp-7", "recovery_path": "host_persisted_output", "n": 20}}, SRC), ("PASS", "AENF_RECOVERED")),
 ("T2_20_0_no_path", lambda: judge({"declared": 20, "visible": 0, "fingerprint": {"execution_id": "imp-7"}, "recovery": {"execution_id": "imp-7", "n": 20}}, SRC), ("UNKNOWN", "AENF_UNRECOVERED")),
 ("T3_rerun_new_impression", lambda: judge({"declared": 20, "visible": 0, "fingerprint": {"execution_id": "imp-7"}, "recovery": {"execution_id": "imp-8", "recovery_path": "re-poll", "n": 20}}, SRC), ("NEW_EVENT", "RERUN_NOT_RECOVERY")),
 ("T4_recovered_partial", lambda: judge({"declared": 20, "visible": 0, "fingerprint": {"execution_id": "imp-7"}, "recovery": {"execution_id": "imp-7", "recovery_path": "host_persisted_output", "n": 17}}, SRC), ("FAIL", "AENF_PARTIAL")),
 ("S1_sticky_replay", lambda: tuple(sticky([("PRESENT", "a"), ("UNKNOWN", "b"), ("PRESENT", "a")])), ("PRESENT", "UNKNOWN", "UNKNOWN")),
 ("S2_sticky_new_fp", lambda: tuple(sticky([("PRESENT", "a"), ("UNKNOWN", "b"), ("PRESENT", "c")])), ("PRESENT", "UNKNOWN", "PRESENT")),
 ("R1_attempts_ok_wallclock_out", lambda: retry(2, 5, 61000, 60000, True), "RETRY_EXHAUSTED"),
 ("R2_attempts_out", lambda: retry(5, 5, 1000, 60000, True), "RETRY_EXHAUSTED"),
 ("M1_mismatch_pair", lambda: mismatch({"verdict_ok": True, "reason_ok": False, "cited_defect": "STALE_SUCCESS", "actual_defect": "TRUNCATED_AS_COMPLETE"}), ("FAIL", "REASON_MISMATCH")),
 ("M2_mismatch_no_pair", lambda: mismatch({"verdict_ok": True, "reason_ok": False}), ("UNKNOWN", "REASON_MISMATCH_UNFALSIFIABLE")),
 ("E1_field_absent", lambda: field({"a": 1}, "sha256"), ("UNKNOWN", "FIELD_ABSENT")),
 ("E2_field_empty", lambda: field({"sha256": ""}, "sha256"), ("FAIL", "FIELD_EMPTY")),
]
def naive_cycle_only(r): return "PRESENT" if r["fingerprint"].get("execution_id") else "UNKNOWN"
def naive_retry_last_ok(last_ok): return "PRESENT" if last_ok else "UNKNOWN"
if __name__ == "__main__":
    ok = True
    for rid, f, want in ROWS:
        got = f(); ok &= got == want; print(json.dumps({"id": rid, "got": got, "expect_code": want, "pass": got == want}, ensure_ascii=False))
    c1 = naive_cycle_only({"fingerprint": {"execution_id": "e3", "input_digest": D("source-v1")}}) == "PRESENT"; ok &= c1
    print(json.dumps({"counterexample": "cycle_id_only_judge_greens_stale_input_C1", "pass": c1}))
    c2 = naive_retry_last_ok(True) == "PRESENT"; ok &= c2
    print(json.dumps({"counterexample": "retry_layer_folds_exhaustion_into_last_success", "pass": c2}))
    body = "\n".join(json.dumps({"id": r, "expect": w}, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for r, _, w in ROWS) + "\n"
    print(json.dumps({"rows": len(ROWS), "expect_table_sha256": hashlib.sha256(body.encode()).hexdigest()}))
    print("ALL_PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
