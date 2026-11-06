#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.28

Adds two peer-supplied shapes on top of v0.27 (prior files untouched; S7-S39
rows re-run here by import so one command checks S7-S41).

  S40 CREDENTIAL_POOL_402_EXHAUST_EMPTY_RESET
      After a single 402 the pool is marked exhausted with reset_at empty;
      the next request silently falls back to another model. Client sees
      HTTP 200 + normal text; only response.model != request.model.
      Naive greens on status==200 / ok / text_nonempty / model present.
      Struct requires (not synthesizable):
        - http_status (int)
        - request_model, response_model (str; mismatch is the signal)
        - pool_state in {healthy, exhausted}
        - reset_at (None/""/missing vs concrete timestamp)
        - fallback_applied (bool; must be declared when models differ)
      Rules:
        - http_status==200 AND response_model != request_model
          AND (pool_state==exhausted OR fallback_applied)
          AND (reset_at is None or reset_at=="") ->
          FAIL/POOL_EXHAUST_EMPTY_RESET_MODEL_SWAP
        - http_status==200 AND models equal AND pool_state==healthy
          AND not fallback_applied -> OK
        - models differ but fallback_applied undeclared ->
          UNKNOWN/FALLBACK_UNDECLARED
        - pool_state==exhausted AND reset_at missing key ->
          UNKNOWN/RESET_AT_UNDECLARED
        - http_status==200 alone never proves model identity
      Credit: 礼花 (EigenFlux PM + broadcast — twin arms: exhausted+empty
      reset_at vs healthy; analyze_only; desensitized; observed_v0_3 fields).

  S41 STREAM_TOOLCALL_INDEX_NAME_REPLAY
      Streaming tool_calls pass through upstream block indices shared with
      text/thinking (often starting at 2) and re-emit name/id every frame.
      Naive greens on "got tool_calls" / len>0 / first name present.
      Struct requires:
        - frames: list of {index, name?, id?}
        - index_set_ok: whether set(indices)=={0..n-1} (declared bool)
        - name_once: whether each name appears exactly once (declared bool)
      Rules:
        - missing frames -> UNKNOWN/FRAMES_UNDECLARED
        - computed set(indices) != {0..n-1} -> FAIL/INDEX_NOT_0_N1
        - any name appearing >1 time -> FAIL/NAME_REPLAYED
        - any id appearing >1 time -> FAIL/ID_REPLAYED
        - claiming OK without index_set_ok/name_once declared when frames
          present -> UNKNOWN/STREAM_ATTEST_UNDECLARED
        - indices 0..n-1 contiguous AND each name/id once -> OK
      Credit: 礼花 (EigenFlux PM — twin arms: passthrough index+replay vs
      remapped 0..n-1 first-frame-only; machine-checkable criteria).

Each shape: must-fail arm (naive wrong) + green twin.
analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_28.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_27 as v27


def s40_naive(r):
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    hs = r.get("http_status")
    if hs == 200:
        return "OK"
    if r.get("text_nonempty") is True:
        return "OK"
    if r.get("response_model"):
        return "OK"
    if hs and hs >= 400:
        return "FAIL"
    return "FAIL"


def s40_struct(r):
    if "http_status" not in r:
        return "UNKNOWN/HTTP_STATUS_UNDECLARED"
    hs = r.get("http_status")
    req = r.get("request_model")
    resp = r.get("response_model")
    pool = r.get("pool_state")
    claiming_ok = (
        r.get("status") == "ok"
        or r.get("ok") is True
        or hs == 200
        or r.get("text_nonempty") is True
    )
    if claiming_ok and (req is None or resp is None):
        return "UNKNOWN/MODEL_PAIR_UNDECLARED"
    if "pool_state" not in r and claiming_ok:
        return "UNKNOWN/POOL_STATE_UNDECLARED"
    if pool == "exhausted" and "reset_at" not in r:
        return "UNKNOWN/RESET_AT_UNDECLARED"

    models_differ = (req is not None and resp is not None and req != resp)
    reset = r.get("reset_at")
    reset_empty = reset is None or reset == ""
    fallback = r.get("fallback_applied")

    if hs == 200 and models_differ:
        if fallback is None:
            return "UNKNOWN/FALLBACK_UNDECLARED"
        if (pool == "exhausted" or fallback is True) and reset_empty:
            return "FAIL/POOL_EXHAUST_EMPTY_RESET_MODEL_SWAP"
        if fallback is True:
            return "FAIL/SILENT_MODEL_SWAP"
        return "FAIL/MODEL_MISMATCH"

    if hs == 200 and req == resp and pool == "healthy" and fallback is not True:
        return "OK"

    if hs and hs >= 400:
        return "FAIL"
    return "FAIL"


def s41_naive(r):
    frames = r.get("frames") or r.get("tool_calls")
    if r.get("status") == "ok":
        return "OK"
    if r.get("got_tool_calls") is True:
        return "OK"
    if isinstance(frames, list) and len(frames) > 0:
        return "OK"
    if r.get("first_name"):
        return "OK"
    return "FAIL"


def _frame_names_ids(frames):
    names, ids, indices = [], [], []
    for f in frames:
        if not isinstance(f, dict):
            continue
        if "index" in f:
            indices.append(f["index"])
        if "name" in f and f["name"] is not None:
            names.append(f["name"])
        if "id" in f and f["id"] is not None:
            ids.append(f["id"])
    return indices, names, ids


def s41_struct(r):
    if "frames" not in r:
        return "UNKNOWN/FRAMES_UNDECLARED"
    frames = r.get("frames")
    if not isinstance(frames, list):
        return "UNKNOWN/FRAMES_UNDECLARED"
    if len(frames) == 0:
        return "FAIL/NO_TOOL_CALLS"

    indices, names, ids = _frame_names_ids(frames)
    n = len(indices)
    expected = set(range(n)) if n else set()
    index_ok = set(indices) == expected and len(indices) == n
    from collections import Counter
    name_counts = Counter(names)
    id_counts = Counter(ids)
    name_once = all(c == 1 for c in name_counts.values()) if names else True
    id_once = all(c == 1 for c in id_counts.values()) if ids else True

    claiming_ok = (
        r.get("status") == "ok"
        or r.get("got_tool_calls") is True
        or r.get("ok") is True
    )
    if claiming_ok and ("index_set_ok" not in r or "name_once" not in r):
        return "UNKNOWN/STREAM_ATTEST_UNDECLARED"

    if not index_ok:
        return "FAIL/INDEX_NOT_0_N1"
    if not name_once:
        return "FAIL/NAME_REPLAYED"
    if not id_once:
        return "FAIL/ID_REPLAYED"
    # attestations must match computed truth when present
    if r.get("index_set_ok") is False or r.get("name_once") is False:
        return "FAIL/ATTEST_CONTRADICTS"
    return "OK"


NEW_ROWS = [
  # S40 must-fail: exhausted + empty reset_at + model swap under HTTP 200
  ("S40-mf-exhaust-empty-reset-swap", "S40", "observed_shape_desensitized(礼花)",
   {"arm": "pool_exhausted_empty_reset", "http_status": 200,
    "request_model": "gpt-4o-mini", "response_model": "gpt-3.5-turbo",
    "pool_state": "exhausted", "reset_at": None,
    "fallback_applied": True, "text_nonempty": True, "status": "ok"},
   "FAIL/POOL_EXHAUST_EMPTY_RESET_MODEL_SWAP", True),
  # S40 control: models differ but fallback undeclared
  ("S40-ct-fallback-undeclared", "S40", "hand_built",
   {"http_status": 200, "request_model": "gpt-4o-mini",
    "response_model": "gpt-3.5-turbo", "pool_state": "exhausted",
    "reset_at": None, "text_nonempty": True, "status": "ok"},
   "UNKNOWN/FALLBACK_UNDECLARED", True),
  # S40 control: exhausted without reset_at key
  ("S40-ct-reset-undeclared", "S40", "hand_built",
   {"http_status": 200, "request_model": "gpt-4o-mini",
    "response_model": "gpt-4o-mini", "pool_state": "exhausted",
    "fallback_applied": False, "status": "ok"},
   "UNKNOWN/RESET_AT_UNDECLARED", True),
  # S40 green twin: healthy pool, models match
  ("S40-gt-healthy-match", "S40", "observed_shape_desensitized(礼花)",
   {"arm": "pool_healthy_control", "http_status": 200,
    "request_model": "gpt-4o-mini", "response_model": "gpt-4o-mini",
    "pool_state": "healthy", "reset_at": None,
    "fallback_applied": False, "text_nonempty": True, "status": "ok"},
   "OK", False),
  # S40 must-fail: empty-string reset_at same as None
  ("S40-mf-exhaust-reset-emptystr", "S40", "hand_built",
   {"http_status": 200, "request_model": "claude-3-5",
    "response_model": "claude-3-haiku", "pool_state": "exhausted",
    "reset_at": "", "fallback_applied": True, "ok": True},
   "FAIL/POOL_EXHAUST_EMPTY_RESET_MODEL_SWAP", True),

  # S41 must-fail: passthrough indices starting at 2 + name/id replay
  ("S41-mf-index-passthrough-replay", "S41", "observed_shape_desensitized(礼花)",
   {"arm": "upstream_index_passthrough",
    "frames": [
      {"index": 2, "name": "search", "id": "call_a"},
      {"index": 3, "name": "search", "id": "call_a"},
      {"index": 4, "name": "search", "id": "call_a"},
    ],
    "got_tool_calls": True, "status": "ok",
    "index_set_ok": False, "name_once": False},
   "FAIL/INDEX_NOT_0_N1", True),
  # S41 must-fail: remapped indices but name replayed every frame
  ("S41-mf-name-replayed", "S41", "hand_built",
   {"frames": [
      {"index": 0, "name": "calc", "id": "call_b"},
      {"index": 1, "name": "calc", "id": "call_b"},
    ],
    "got_tool_calls": True, "status": "ok",
    "index_set_ok": True, "name_once": False},
   "FAIL/NAME_REPLAYED", True),
  # S41 control: claiming ok without attestations
  ("S41-ct-attest-undeclared", "S41", "hand_built",
   {"frames": [{"index": 0, "name": "search", "id": "call_c"}],
    "status": "ok", "got_tool_calls": True},
   "UNKNOWN/STREAM_ATTEST_UNDECLARED", True),
  # S41 green twin: remapped 0..n-1, name/id first-frame only
  ("S41-gt-remapped-first-only", "S41", "observed_shape_desensitized(礼花)",
   {"arm": "client_remap_first_frame",
    "frames": [
      {"index": 0, "name": "search", "id": "call_d"},
      {"index": 1},
      {"index": 2},
    ],
    "got_tool_calls": True, "status": "ok",
    "index_set_ok": True, "name_once": True},
   "OK", False),
  # S41 must-fail: id replayed even if name once (split frames)
  ("S41-mf-id-replayed", "S41", "hand_built",
   {"frames": [
      {"index": 0, "name": "a", "id": "same"},
      {"index": 1, "name": "b", "id": "same"},
    ],
    "got_tool_calls": True, "index_set_ok": True, "name_once": True},
   "FAIL/ID_REPLAYED", True),
]


FNS = dict(v27.FNS)
FNS.update({"S40": (s40_naive, s40_struct), "S41": (s41_naive, s41_struct)})
ROWS = list(v27.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S40", "S41") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.28", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_28.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
