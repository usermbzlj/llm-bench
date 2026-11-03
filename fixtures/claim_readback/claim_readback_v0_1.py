#!/usr/bin/env python3
"""CLAIM_READBACK v0.1  (shape + three-log/correlation-key rule credit: 凯瑞's Agent, EigenFlux; impl Grok Bot)

Problem: a consumer pipeline shows an item in a list, the detail fetch returns
404 (or times out, or returns 200 with an empty body), and the feedback/score
call is still ACCEPTED. Downstream treats "feedback accepted" as "item was read
and judged". The read never happened; the judgment is on the list preview.

Rule (凯瑞's Agent): log exposure, read result and feedback as three separate
records joined by ONE shared correlation key. Feedback acceptance is never
evidence of a successful read.

Verdicts (per row):
  READ_VERIFIED       exposure + detail read 2xx with non-empty body whose sha matches
                      the read log + feedback, all three under the same correlation key
  DETAIL_UNREAD       feedback/claim present but detail read failed (4xx/5xx/timeout),
                      was never attempted, or returned an empty body  -> FAIL
  EVIDENCE_DROPPED    detail read reported ok but the read log is missing or carries
                      no body digest -> UNKNOWN (cannot verify, never PASS)
  CORRELATION_BROKEN  the three records do not share one correlation key -> UNKNOWN
  READ_VERSION_MISMATCH detail body revision != exposed list revision -> FAIL
  NOT_CLAIMED         read failed AND no feedback/claim submitted -> honest, out of denominator
Report gate: a report whose read_n is computed from feedback_accepted_n
  -> FEEDBACK_AS_READ_PROOF.
Naive baseline: "feedback accepted -> read ok".
provenance: K1 synthetic(凯瑞's Agent de-identified shape: list visible + detail 404 +
feedback accepted); rest hand_built. analyze_only, stdlib only. exit 0 iff selftest all pass.
"""
from __future__ import annotations
import hashlib, json, sys

def sha8(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:8]

def judge(r):
    exp, rd, fb = r.get("exposure"), r.get("read"), r.get("feedback")
    claimed = bool(fb and fb.get("accepted"))
    read_ok = bool(rd and rd.get("attempted") and isinstance(rd.get("status"), int)
                   and 200 <= rd["status"] < 300 and rd.get("body_bytes", 0) > 0)
    if not read_ok:
        if not claimed:
            return {"status": "NOT_CLAIMED", "code": "HONEST_SKIP"}
        if not rd or not rd.get("attempted"):
            return {"status": "FAIL", "code": "DETAIL_UNREAD", "why": "no read attempted"}
        if isinstance(rd.get("status"), int) and 200 <= rd["status"] < 300:
            return {"status": "FAIL", "code": "DETAIL_UNREAD", "why": "2xx empty body"}
        return {"status": "FAIL", "code": "DETAIL_UNREAD", "why": f"read status {rd.get('status')}"}
    if not claimed:
        return {"status": "NOT_CLAIMED", "code": "READ_NO_FEEDBACK"}
    keys = {x.get("corr") for x in (exp, rd, fb) if x}
    if not exp or len(keys) != 1 or None in keys:
        return {"status": "UNKNOWN", "code": "CORRELATION_BROKEN", "keys": sorted(map(str, keys))}
    log = rd.get("read_log")
    if not log or not log.get("body_sha8"):
        return {"status": "UNKNOWN", "code": "EVIDENCE_DROPPED"}
    if log["body_sha8"] != rd.get("body_sha8"):
        return {"status": "UNKNOWN", "code": "EVIDENCE_DROPPED", "why": "log digest != body digest"}
    if exp.get("revision") is not None and rd.get("revision") != exp.get("revision"):
        return {"status": "FAIL", "code": "READ_VERSION_MISMATCH"}
    return {"status": "PASS", "code": "READ_VERIFIED"}

def naive(r):
    return "PASS" if (r.get("feedback") or {}).get("accepted") else "NOT_CLAIMED"

def report(rows, read_from_feedback=False):
    res = [judge(r) for r in rows]
    st = [x["status"] for x in res]
    fb_n = sum(1 for r in rows if (r.get("feedback") or {}).get("accepted"))
    read_n = fb_n if read_from_feedback else st.count("PASS")
    denom = st.count("PASS") + st.count("FAIL")
    return {"feedback_accepted_n": fb_n, "read_verified_n": read_n, "fail_n": st.count("FAIL"),
            "unknown_n": st.count("UNKNOWN"), "not_claimed_n": st.count("NOT_CLAIMED"),
            "denominator": denom,
            "read_rate": (st.count("PASS") / denom) if denom else None,
            "gate": "FEEDBACK_AS_READ_PROOF" if read_from_feedback and read_n != st.count("PASS") else "OK"}

BODY = b'{"id":"it-1","rev":3,"text":"detail body"}'
B8 = sha8(BODY)
def E(c="c1", rev=3): return {"corr": c, "list_visible": True, "revision": rev}
def R(status=200, c="c1", body=BODY, rev=3, log=True, attempted=True, log_sha=None):
    d = {"attempted": attempted, "status": status, "corr": c, "body_bytes": len(body) if body else 0,
         "body_sha8": sha8(body) if body else None, "revision": rev}
    if log: d["read_log"] = {"body_sha8": log_sha if log_sha is not None else d["body_sha8"]}
    return d
def F(c="c1", acc=True): return {"corr": c, "accepted": acc, "score": 1}

ROWS = {
  "K1_list_visible_detail_404_feedback_accepted": (dict(exposure=E(), read=R(404, body=b"", log=False), feedback=F(), provenance="synthetic(凯瑞's Agent)"), "FAIL", "DETAIL_UNREAD"),
  "K1C_same_but_detail_200": (dict(exposure=E(), read=R(200), feedback=F(), provenance="hand_built"), "PASS", "READ_VERIFIED"),
  "K2_detail_timeout_feedback_accepted": (dict(exposure=E(), read=R("timeout", body=b"", log=False), feedback=F(), provenance="hand_built"), "FAIL", "DETAIL_UNREAD"),
  "K3_200_empty_body_feedback_accepted": (dict(exposure=E(), read=R(200, body=b""), feedback=F(), provenance="hand_built"), "FAIL", "DETAIL_UNREAD"),
  "K4_no_read_attempted_scored_from_preview": (dict(exposure=E(), read=None, feedback=F(), provenance="hand_built"), "FAIL", "DETAIL_UNREAD"),
  "K5_read_ok_but_read_log_missing": (dict(exposure=E(), read=R(200, log=False), feedback=F(), provenance="hand_built"), "UNKNOWN", "EVIDENCE_DROPPED"),
  "K5B_read_log_digest_mismatch": (dict(exposure=E(), read=R(200, log_sha="deadbeef"), feedback=F(), provenance="hand_built"), "UNKNOWN", "EVIDENCE_DROPPED"),
  "K6_feedback_joined_to_other_exposure": (dict(exposure=E("c1"), read=R(200, c="c1"), feedback=F("c2"), provenance="hand_built"), "UNKNOWN", "CORRELATION_BROKEN"),
  "K6B_no_correlation_key": (dict(exposure=E(None), read=R(200, c=None), feedback=F(None), provenance="hand_built"), "UNKNOWN", "CORRELATION_BROKEN"),
  "K7_detail_older_revision_than_list": (dict(exposure=E(rev=4), read=R(200, rev=3), feedback=F(), provenance="hand_built"), "FAIL", "READ_VERSION_MISMATCH"),
  "K8_detail_404_no_feedback_honest": (dict(exposure=E(), read=R(404, body=b"", log=False), feedback=None, provenance="hand_built"), "NOT_CLAIMED", "HONEST_SKIP"),
  "K8B_detail_404_feedback_rejected": (dict(exposure=E(), read=R(404, body=b"", log=False), feedback=F(acc=False), provenance="hand_built"), "NOT_CLAIMED", "HONEST_SKIP"),
}

def main():
    out, checks = {}, []
    for k, (row, st, code) in ROWS.items():
        r = judge(row); r["naive"] = naive(row); out[k] = r
        checks.append((k, r["status"] == st and r["code"] == code, f"{r['status']}/{r['code']} (expect {st}/{code})"))
    false_pass = [k for k, (row, st, _) in ROWS.items() if st != "PASS" and naive(row) == "PASS"]
    checks.append(("P1_naive_false_read_count", len(false_pass) == 9, f"naive 'feedback accepted -> read' false on {len(false_pass)}/12: {false_pass}"))
    rows = [r for r, _, _ in ROWS.values()]
    honest, inflated = report(rows), report(rows, read_from_feedback=True)
    checks.append(("P2_report_counts", honest["read_verified_n"] == 1 and honest["feedback_accepted_n"] == 10 and honest["fail_n"] == 5 and honest["unknown_n"] == 4 and honest["denominator"] == 6, json.dumps(honest)))
    checks.append(("P3_feedback_as_read_proof_gated", inflated["gate"] == "FEEDBACK_AS_READ_PROOF" and honest["gate"] == "OK", json.dumps(inflated)))
    a, b = ROWS["K1_list_visible_detail_404_feedback_accepted"][0]["read"], ROWS["K1C_same_but_detail_200"][0]["read"]
    diff = sorted(f for f in set(a) | set(b) if a.get(f) != b.get(f))
    checks.append(("P4_K1_pair_differs_only_in_read_result", diff == ["body_bytes", "body_sha8", "read_log", "status"], f"diff={diff}"))
    checks.append(("P5_feedback_never_sufficient", all(judge(dict(r, read=None))["status"] != "PASS" for r in rows), "dropping the read record never yields PASS"))
    ok = sum(c[1] for c in checks)
    json.dump({"rows": out, "report_honest": honest, "report_feedback_as_read": inflated,
               "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks], "selftest": f"{ok}/{len(checks)}"},
              open("run_out_v0_1.json", "w"), ensure_ascii=False, indent=1)
    for n, o, d in checks: print(("PASS " if o else "FAIL ") + n + " " + d)
    print(f"selftest {ok}/{len(checks)}")
    sys.exit(0 if ok == len(checks) else 1)

if __name__ == "__main__":
    main()
