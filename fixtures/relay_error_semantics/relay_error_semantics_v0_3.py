#!/usr/bin/env python3
"""RELAY_ERROR_SEMANTICS v0.3

Layers four shapes on top of v0.2 (imported unchanged) plus one paired check.
All rows hand_built; drop observed_v0_3.jsonl next to this file to add real ones.

  * CONTENT_LENGTH_MISMATCH  declared Content-Length != bytes received. Body is
                             truncated in transit; JSON may still parse if the
                             cut lands on a boundary.            credit: Marvis
  * SSE_ERROR_MASKED_200     upstream rejection delivered as an `error` event
                             inside a 200 text/event-stream.     credit: Aran
  * TOOL_CALL_TRUNCATED      mid-stream disconnect leaves a half-emitted
                             tool_call (arguments not valid JSON). Must never
                             be executed.                        credit: Aran
  * ORPHAN_TOOL_RESULT       request has a role=tool message with no preceding
                             assistant tool_calls of that id, relay still 200s.
                                                                 credit: Aran
  * ERROR_SEMANTICS_DIVERGE  paired official-vs-relay row: status differs while
    + RETRY_AFTER_LOST       body is byte-identical; 429->500 that also drops
                             Retry-After changes retry behaviour.credit: 小花花

Precedence (emitted as field `check_order`): transport/length -> SSE events ->
tool-call integrity -> request integrity -> v0.2 classify.
A schema-only validator (does body parse? does it have choices?) is run as a
baseline and must call every must-fail row here OK/valid.

analyze_only. Stdlib only. Run: python3 relay_error_semantics_v0_3.py
"""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relay_error_semantics_v0_2 as v2

CHECK_ORDER = ["CONTENT_LENGTH", "SSE_EVENTS", "TOOL_CALL_INTEGRITY", "REQUEST_INTEGRITY", "V0_2"]
NEW = {
    "CONTENT_LENGTH_MISMATCH": (True,  "billed",  "BOUNDED_RETRY_FLAG_RELAY"),
    "SSE_ERROR_MASKED_200":    (True,  "unknown", "PARSE_EVENT_ERROR_THEN_V0_2_RULES"),
    "TOOL_CALL_TRUNCATED":     (True,  "billed",  "NEVER_EXECUTE_RETRY_WHOLE_TURN"),
    "ORPHAN_TOOL_RESULT":      (False, "billed",  "FIX_CLIENT_FLAG_RELAY_NO_VALIDATION"),
}
MATRIX = {**v2.MATRIX, **NEW}


def _json_ok(s):
    try:
        json.loads(s); return True
    except Exception:
        return False


def classify(row):
    cl, body = row.get("content_length"), row.get("body_snapshot")
    if cl is not None and body is not None and cl != len(body.encode("utf-8")):
        return "CONTENT_LENGTH_MISMATCH", "CONTENT_LENGTH"
    for ev in row.get("sse_events") or []:
        if ev.get("event") == "error" or (isinstance(ev.get("data"), dict) and "error" in ev["data"]):
            return "SSE_ERROR_MASKED_200", "SSE_EVENTS"
    for tc in row.get("tool_calls") or []:
        if not _json_ok(tc.get("arguments", "")):
            return "TOOL_CALL_TRUNCATED", "TOOL_CALL_INTEGRITY"
    seen = set()
    for m in row.get("request_messages") or []:
        for tc in m.get("tool_calls") or []:
            seen.add(tc.get("id"))
        if m.get("role") == "tool" and m.get("tool_call_id") not in seen and (row.get("status") or 0) // 100 == 2:
            return "ORPHAN_TOOL_RESULT", "REQUEST_INTEGRITY"
    return v2.classify(row), "V0_2"


def schema_only(row):
    """Baseline: body parses as JSON (or stream has data) -> valid."""
    b = row.get("body_snapshot")
    return (b is not None and _json_ok(b)) or bool(row.get("sse_events"))


def R(rid, exp, must_fail, snap, **kw):
    row, _, _ = v2.R(rid, kw.pop("status", 200), snap, exp, must_fail, **{k: kw[k] for k in list(kw) if k in ("fr", "usage", "stream", "stream_done", "billed", "code")})
    row.update({k: v for k, v in kw.items() if k in ("content_length", "sse_events", "tool_calls", "request_messages")})
    return row, exp, must_fail


OKB, U = v2.OKB, v2.U
TC_OK = [{"id": "c1", "name": "get_price", "arguments": '{"symbol":"BTCUSDT"}'}]
ROWS = [
    R("L01_content_length_short", "CONTENT_LENGTH_MISMATCH", True, OKB, content_length=len(OKB) + 37, fr="stop", usage=U, billed=True),
    R("L02_content_length_twin_ok", "OK", False, OKB, content_length=len(OKB), fr="stop", usage=U, billed=True),
    R("S01_error_event_in_200_sse", "SSE_ERROR_MASKED_200", True, OKB, stream=True, stream_done=True, fr="stop", usage=U,
      sse_events=[{"event": "message", "data": {"choices": [{"delta": {"content": "h"}}]}},
                  {"event": "error", "data": {"error": {"code": "context_length_exceeded"}}}]),
    R("S02_data_error_no_event_name", "SSE_ERROR_MASKED_200", True, OKB, stream=True, stream_done=True, fr="stop", usage=U,
      sse_events=[{"data": {"error": {"type": "overloaded_error"}}}]),
    R("S03_sse_clean_twin", "OK", False, OKB, stream=True, stream_done=True, fr="stop", usage=U,
      sse_events=[{"event": "message", "data": {"choices": [{"delta": {"content": "hi"}}]}}]),
    R("T01_half_tool_call_args", "TOOL_CALL_TRUNCATED", True, OKB, fr="tool_calls", usage=U, billed=True,
      tool_calls=[{"id": "c1", "name": "place_order", "arguments": '{"symbol":"BTCUSDT","qty":'}]),
    R("T02_tool_call_twin_ok", "OK", False, OKB, fr="tool_calls", usage=U, tool_calls=TC_OK),
    R("Q01_orphan_tool_result", "ORPHAN_TOOL_RESULT", True, OKB, fr="stop", usage=U, billed=True,
      request_messages=[{"role": "user", "content": "price?"}, {"role": "tool", "tool_call_id": "c9", "content": "42"}]),
    R("Q02_paired_tool_result_twin", "OK", False, OKB, fr="stop", usage=U,
      request_messages=[{"role": "user", "content": "price?"}, {"role": "assistant", "tool_calls": TC_OK},
                        {"role": "tool", "tool_call_id": "c1", "content": "42"}]),
]

# paired official-vs-relay rows (小花花's real-shape row, plus a control)
PAIRS = [
    {"id": "P01_429_vs_500_same_body", "official": {"status": 429, "retry_after": 2},
     "relay": {"status": 500, "retry_after": None},
     "body": json.dumps({"error": {"message": "rate limited", "type": "requests"}}),
     "expected": "ERROR_SEMANTICS_DIVERGE", "retry_after_lost": True},
    {"id": "P02_429_vs_429_control", "official": {"status": 429, "retry_after": 2},
     "relay": {"status": 429, "retry_after": 2},
     "body": json.dumps({"error": {"message": "rate limited", "type": "requests"}}),
     "expected": "SAME", "retry_after_lost": False},
]


def pair_verdict(p):
    o, r = p["official"], p["relay"]
    lost = o.get("retry_after") is not None and r.get("retry_after") is None
    return ("ERROR_SEMANTICS_DIVERGE" if o["status"] != r["status"] else "SAME"), lost


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    rows = ROWS + v2.load_observed(os.path.join(here, "observed_v0_3.jsonl"))
    ok = total = 0; out = []; schema_false_ok = 0
    for row, exp, mf in rows:
        got, stage = classify(row)
        passed = got == exp
        ok += passed; total += 1
        if mf and schema_only(row):
            schema_false_ok += 1
        out.append({"id": row["id"], "expected": exp, "got": got, "check_stage": stage,
                    "action": MATRIX[got][2], "must_fail": mf, "pass": passed})
    pairs = []
    for p in PAIRS:
        v, lost = pair_verdict(p)
        passed = v == p["expected"] and lost == p["retry_after_lost"]
        ok += passed; total += 1
        body_only = "SAME"  # body byte-identical -> body-only diff passes it
        pairs.append({"id": p["id"], "got": v, "retry_after_lost": lost, "body_only_baseline": body_only, "pass": passed})
    must = [o for o in out if o["must_fail"]]
    ctrl = [
        ("C1_schema_only_baseline_misses_every_must_fail", schema_false_ok == len(must)),
        ("C2_every_new_class_has_ok_twin", all(any(o["id"][0] == m["id"][0] and o["got"] == "OK" for o in out) for m in must)),
        ("C3_v0_2_alone_calls_S01_OK", v2.classify(ROWS[2][0]) == "OK"),
        ("C4_body_only_diff_misses_P01", pairs[0]["got"] != pairs[0]["body_only_baseline"]),
        ("C5_v0_2_selftest_still_green", all(v2.classify(r) == e for r, e, _ in v2.ROWS)),
    ]
    for _, c in ctrl:
        ok += bool(c); total += 1
    res = {"fixture": "RELAY_ERROR_SEMANTICS", "version": "0.3", "check_order": CHECK_ORDER,
           "selftest": f"{ok}/{total}", "schema_only_baseline_false_ok": schema_false_ok,
           "must_fail_rows": len(must), "controls": {k: bool(v) for k, v in ctrl}, "rows": out, "pairs": pairs}
    json.dump(res, open(os.path.join(here, "run_out_v0_3.json"), "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; schema-only baseline calls {schema_false_ok}/{len(must)} must-fail rows valid")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
