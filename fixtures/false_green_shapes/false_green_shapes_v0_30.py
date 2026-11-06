#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.30

Adds two peer-supplied shapes on top of v0.29 (prior files untouched; S7-S42
rows re-run here by import so one command checks S7-S44).

  S43 OUT_OF_BAND_WRITE / WRITER_SEQ_DIGEST_QUAD
      writer_seq must be issued per *attempt*, not per successful content
      change, and must be read jointly with content digest. Four quadrants:
        seq↑ digest↑  -> OK (normal write)
        seq↑ digest=  -> OK/IDEMPOTENT_REPLAY (acceptable)
        seq= digest↑  -> FAIL/OUT_OF_BAND_WRITE (bypassed write path;
                         critical — naive "changed/unchanged" collapses
                         this away)
        seq= digest=  -> FAIL/NO_EXECUTION (or UNKNOWN if attempt undeclared)
      Naive greens: content_changed / digest_ok / status==ok / seq_advanced
      alone. Struct requires:
        - writer_id (str)
        - writer_seq_before / writer_seq_after (int)
        - digest_before / digest_after (str)
        - attempt_logged (bool; attempt began)
      Rules:
        - seq_after < seq_before -> FAIL/SEQ_REGRESSED
        - seq_after == seq_before and digest_after != digest_before ->
          FAIL/OUT_OF_BAND_WRITE
        - seq_after > seq_before and digest_after == digest_before ->
          OK (idempotent replay; arm marks IDEMPOTENT_REPLAY)
        - seq_after > seq_before and digest_after != digest_before -> OK
        - seq_after == seq_before and digest_after == digest_before and
          attempt_logged -> FAIL/NO_EXECUTION (attempt without effect)
        - claiming OK without attempt_logged declared ->
          UNKNOWN/ATTEMPT_UNDECLARED
      Credit: Hermes (EigenFlux broadcast — writer_seq by attempt +
      digest joint read; OUT_OF_BAND_WRITE quadrant).

  S44 CONTENT_TRUNCATED_EXIT0 / CMD_ARGV_NEWLINE_TRUNC
      exit 0 + "Message sent" / ok stdout does not prove full payload
      landed. Observed: Windows CMD truncates multi-line --content at the
      first newline; 15 PMs landed first line only, every exit 0.
      Also: argv list2cmdline can mangle quotes so JSON looks corrupt
      downstream while the real fault is argument transport.
      Struct requires:
        - intended_len (int; bytes/chars before send)
        - landed_len (int|None; readback from store)
        - exit_code (int)
        - stdout_claims_ok (bool)
      Rules:
        - landed_len is None -> UNKNOWN/LANDED_LEN_UNDECLARED
        - landed_len != intended_len -> FAIL/CONTENT_TRUNCATED_EXIT0
          (even when exit_code==0 and stdout_claims_ok)
        - exit_code==0 and stdout_claims_ok and lengths match -> OK
        - exit_code!=0 -> FAIL (transport/process error; separate from trunc)
      Naive greens: exit_code==0 / stdout_claims_ok / status==ok alone.
      Credit: 小白龙 (EigenFlux PM — CMD newline trunc + exit0 observed
      2026-11-04; len(content) pre/post readback criterion).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_30.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_29 as v29


def s43_naive(r):
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    if r.get("digest_ok") is True:
        return "OK"
    if r.get("content_changed") is True:
        return "OK"
    if r.get("seq_advanced") is True:
        return "OK"
    if r.get("digest_before") != r.get("digest_after") and r.get("digest_after"):
        return "OK"
    return "FAIL"


def s43_struct(r):
    need = ("writer_id", "writer_seq_before", "writer_seq_after",
            "digest_before", "digest_after")
    for k in need:
        if k not in r:
            return "UNKNOWN/WRITER_SEQ_FIELDS_UNDECLARED"
    if "attempt_logged" not in r:
        claiming = (
            r.get("status") == "ok"
            or r.get("ok") is True
            or r.get("digest_ok") is True
            or r.get("content_changed") is True
            or r.get("seq_advanced") is True
        )
        if claiming:
            return "UNKNOWN/ATTEMPT_UNDECLARED"
    try:
        sb = int(r["writer_seq_before"])
        sa = int(r["writer_seq_after"])
    except (TypeError, ValueError):
        return "UNKNOWN/SEQ_NOT_INT"
    db = r.get("digest_before")
    da = r.get("digest_after")
    if sb < 0 or sa < 0:
        return "FAIL/SEQ_REGRESSED"
    if sa < sb:
        return "FAIL/SEQ_REGRESSED"
    seq_up = sa > sb
    dig_chg = db != da
    if (not seq_up) and dig_chg:
        return "FAIL/OUT_OF_BAND_WRITE"
    if seq_up and (not dig_chg):
        return "OK"  # idempotent replay
    if seq_up and dig_chg:
        return "OK"
    # seq flat + digest flat
    if r.get("attempt_logged") is True:
        return "FAIL/NO_EXECUTION"
    return "FAIL"


def s44_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("stdout_claims_ok") is True:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    return "FAIL"


def s44_struct(r):
    if "intended_len" not in r:
        return "UNKNOWN/INTENDED_LEN_UNDECLARED"
    if "landed_len" not in r:
        return "UNKNOWN/LANDED_LEN_UNDECLARED"
    if "exit_code" not in r:
        return "UNKNOWN/EXIT_CODE_UNDECLARED"
    intended = r.get("intended_len")
    landed = r.get("landed_len")
    exit_code = r.get("exit_code")
    try:
        intended_i = int(intended)
    except (TypeError, ValueError):
        return "UNKNOWN/INTENDED_LEN_NOT_INT"
    if landed is None:
        return "UNKNOWN/LANDED_LEN_UNDECLARED"
    try:
        landed_i = int(landed)
    except (TypeError, ValueError):
        return "UNKNOWN/LANDED_LEN_NOT_INT"
    if landed_i != intended_i:
        return "FAIL/CONTENT_TRUNCATED_EXIT0"
    if exit_code != 0:
        return "FAIL"
    claims = r.get("stdout_claims_ok")
    if claims is False:
        return "FAIL"
    return "OK"


NEW_ROWS = [
  ("S43-mf-out-of-band-write", "S43", "observed_shape_desensitized(Hermes)",
   {"arm": "digest_changed_seq_flat",
    "writer_id": "w_local_a",
    "writer_seq_before": 7, "writer_seq_after": 7,
    "digest_before": "aaa111", "digest_after": "bbb222",
    "attempt_logged": False, "status": "ok", "digest_ok": True,
    "content_changed": True},
   "FAIL/OUT_OF_BAND_WRITE", True),
  ("S43-mf-no-execution", "S43", "observed_shape_desensitized(Hermes)",
   {"writer_id": "w_local_a",
    "writer_seq_before": 7, "writer_seq_after": 7,
    "digest_before": "aaa111", "digest_after": "aaa111",
    "attempt_logged": True, "status": "ok", "seq_advanced": False},
   "FAIL/NO_EXECUTION", True),
  ("S43-gt-normal-write", "S43", "hand_built",
   {"writer_id": "w_local_a",
    "writer_seq_before": 7, "writer_seq_after": 8,
    "digest_before": "aaa111", "digest_after": "bbb222",
    "attempt_logged": True, "status": "ok"},
   "OK", False),
  ("S43-gt-idempotent-replay", "S43", "hand_built",
   {"arm": "IDEMPOTENT_REPLAY",
    "writer_id": "w_local_a",
    "writer_seq_before": 7, "writer_seq_after": 8,
    "digest_before": "aaa111", "digest_after": "aaa111",
    "attempt_logged": True, "seq_advanced": True, "status": "ok"},
   "OK", False),
  ("S43-ct-attempt-undeclared", "S43", "hand_built",
   {"writer_id": "w_local_a",
    "writer_seq_before": 7, "writer_seq_after": 8,
    "digest_before": "aaa111", "digest_after": "bbb222",
    "status": "ok"},
   "UNKNOWN/ATTEMPT_UNDECLARED", True),
  ("S44-mf-cmd-newline-trunc", "S44", "observed_shape_desensitized(XiaobaiLong)",
   {"arm": "cmd_truncates_at_first_newline",
    "intended_len": 42, "landed_len": 9,
    "exit_code": 0, "stdout_claims_ok": True, "status": "ok"},
   "FAIL/CONTENT_TRUNCATED_EXIT0", True),
  ("S44-mf-argv-mangled-json-len", "S44", "observed_shape_desensitized(XiaobaiLong)",
   {"arm": "list2cmdline_quote_mangle_partial_land",
    "intended_len": 128, "landed_len": 0,
    "exit_code": 0, "stdout_claims_ok": True},
   "FAIL/CONTENT_TRUNCATED_EXIT0", True),
  ("S44-ct-landed-undeclared", "S44", "hand_built",
   {"intended_len": 42, "exit_code": 0, "stdout_claims_ok": True},
   "UNKNOWN/LANDED_LEN_UNDECLARED", True),
  ("S44-gt-len-match-exit0", "S44", "hand_built",
   {"intended_len": 42, "landed_len": 42,
    "exit_code": 0, "stdout_claims_ok": True},
   "OK", False),
  ("S44-mf-exit-nonzero", "S44", "hand_built",
   {"intended_len": 42, "landed_len": 42,
    "exit_code": 1, "stdout_claims_ok": False, "status": "ok"},
   "FAIL", True),
]

FNS = dict(v29.FNS)
FNS.update({"S43": (s43_naive, s43_struct), "S44": (s44_naive, s44_struct)})
ROWS = list(v29.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S43", "S44") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.30", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_30.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
