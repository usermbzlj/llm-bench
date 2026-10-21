#!/usr/bin/env python3
"""canon_manifest.py v0.1 - per-digest canonicalization profile gate (llm-bench #3).

Problem (found by 李晨熙, 2026-10-21): one fixture pack carried two digests computed
under two canonicalizations - test_vector_set_digest WITH a trailing "\n", typed_reason
enum digest WITHOUT it. Both look like valid sha256; a recomputer that picks the
"wrong" profile reports a mismatch that is really a profile mismatch, or worse, a
recomputer that tries both silently 'fixes' tampering.

Rule: every digest field declares its profile explicitly. A pack is accepted only if
each declared digest recomputes under ITS declared profile, and the judge never
tries alternative profiles.

Verdicts per digest field:
  OK                        recomputes under declared profile
  PROFILE_UNDECLARED        no profile -> cannot judge (never guess)
  PROFILE_MISMATCH          value matches a DIFFERENT profile than declared
                            (honest mixup, distinct from tampering)
  DIGEST_MISMATCH           matches no known profile (tamper / wrong input)
Pack-level:
  MIXED_CANON_PROFILE       declared profiles differ across fields in one pack
                            (allowed only with mixed_profiles_ack: true)

Also in this file (same family, from today's PMs):
  UNKNOWN must carry a source (read_timeout|field_missing|parse_error) -> else UNKNOWN_UNSOURCED  (AI-Film-Studio)
  time deltas require equal clock_source_id -> else INCOMPARABLE, never a number                  (AI-Film-Studio)
  a reference window must declare start,end,n -> else REF_WINDOW_UNDECLARED                         (数境重构)
Run: python3 canon_manifest.py   (exit 0 iff every row's verdict == expect)
"""
import hashlib, json, sys

def canon(obj_list, trailing_newline):
    lines = [json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(',', ':')) for o in obj_list]
    s = "\n".join(lines) + ("\n" if trailing_newline else "")
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

PROFILES = {"jsonl_sorted_lf_trailing": True, "jsonl_sorted_lf_no_trailing": False}

def judge_field(f, payload):
    prof = f.get("profile")
    if prof not in PROFILES:
        return "PROFILE_UNDECLARED"
    if canon(payload, PROFILES[prof]) == f["value"]:
        return "OK"
    for other, tn in PROFILES.items():
        if other != prof and canon(payload, tn) == f["value"]:
            return "PROFILE_MISMATCH"
    return "DIGEST_MISMATCH"

def judge_pack(pack, payloads):
    out = {name: judge_field(f, payloads[name]) for name, f in pack["digests"].items()}
    profs = {f.get("profile") for f in pack["digests"].values()}
    if len(profs) > 1 and not pack.get("mixed_profiles_ack"):
        out["_pack"] = "MIXED_CANON_PROFILE"
    else:
        out["_pack"] = "OK" if all(v == "OK" for v in out.values()) else "FIELD_FAIL"
    return out

def judge_unknown(r):
    if r.get("state") != "UNKNOWN": return "N/A"
    return "OK" if r.get("unknown_source") in ("read_timeout", "field_missing", "parse_error") else "UNKNOWN_UNSOURCED"

def judge_delta(a, b):
    if not a.get("clock_source_id") or a.get("clock_source_id") != b.get("clock_source_id"):
        return "INCOMPARABLE"
    return b["t_ms"] - a["t_ms"]

def judge_ref(r):
    return "OK" if all(r.get(k) is not None for k in ("ref_start", "ref_end", "ref_n")) and r["ref_n"] > 0 else "REF_WINDOW_UNDECLARED"

# ---- fixtures ----
TV = [{"id": "T-01", "verdict": "PASS"}, {"id": "T-02", "verdict": "REJECT"}]
EN = [{"reason": "ISSUER_IS_RECOMPUTER"}, {"reason": "ISSUER_NOT_DETACHED"}]
P = {"tv": TV, "enum": EN}
d = lambda x, tn: canon(x, tn)

ROWS = [
 ("C-01 both trailing, declared", {"digests": {"tv": {"profile": "jsonl_sorted_lf_trailing", "value": d(TV, 1)},
                                               "enum": {"profile": "jsonl_sorted_lf_trailing", "value": d(EN, 1)}}},
  {"tv": "OK", "enum": "OK", "_pack": "OK"}),
 ("C-02 today's real shape: mixed profiles, no ack", {"digests": {"tv": {"profile": "jsonl_sorted_lf_trailing", "value": d(TV, 1)},
                                               "enum": {"profile": "jsonl_sorted_lf_no_trailing", "value": d(EN, 0)}}},
  {"tv": "OK", "enum": "OK", "_pack": "MIXED_CANON_PROFILE"}),
 ("C-03 mixed but acknowledged", {"mixed_profiles_ack": True, "digests": {"tv": {"profile": "jsonl_sorted_lf_trailing", "value": d(TV, 1)},
                                               "enum": {"profile": "jsonl_sorted_lf_no_trailing", "value": d(EN, 0)}}},
  {"tv": "OK", "enum": "OK", "_pack": "OK"}),
 ("C-04 declared trailing, value is no-trailing (the b950 bug)", {"digests": {"tv": {"profile": "jsonl_sorted_lf_trailing", "value": d(TV, 0)},
                                               "enum": {"profile": "jsonl_sorted_lf_trailing", "value": d(EN, 1)}}},
  {"tv": "PROFILE_MISMATCH", "enum": "OK", "_pack": "FIELD_FAIL"}),
 ("C-05 tampered payload", {"digests": {"tv": {"profile": "jsonl_sorted_lf_trailing", "value": d([{"id": "T-01", "verdict": "REJECT"}] + TV[1:], 1)},
                                               "enum": {"profile": "jsonl_sorted_lf_trailing", "value": d(EN, 1)}}},
  {"tv": "DIGEST_MISMATCH", "enum": "OK", "_pack": "FIELD_FAIL"}),
 ("C-06 profile missing", {"digests": {"tv": {"value": d(TV, 1)}, "enum": {"profile": "jsonl_sorted_lf_trailing", "value": d(EN, 1)}}},
  {"tv": "PROFILE_UNDECLARED", "enum": "OK", "_pack": "MIXED_CANON_PROFILE"}),
]

def try_both_judge(f, payload):  # counterexample: the "helpful" recomputer
    return "OK" if f["value"] in (canon(payload, True), canon(payload, False)) else "DIGEST_MISMATCH"

def main():
    bad = 0
    for name, pack, exp in ROWS:
        got = judge_pack(pack, P)
        ok = got == exp; bad += not ok
        print(("PASS " if ok else "FAIL ") + name, json.dumps(got, ensure_ascii=False))
    # counterexample: try-both judge greens C-04 (the honest bug) -> hides it
    ce = try_both_judge(ROWS[3][1]["digests"]["tv"], TV)
    print("COUNTEREXAMPLE try-both judge on C-04 ->", ce, "(hides PROFILE_MISMATCH)")
    bad += ce != "OK"
    side = [
     ("U-01 UNKNOWN no source", judge_unknown({"state": "UNKNOWN"}), "UNKNOWN_UNSOURCED"),
     ("U-02 UNKNOWN read_timeout", judge_unknown({"state": "UNKNOWN", "unknown_source": "read_timeout"}), "OK"),
     ("K-01 same ms, different clock", judge_delta({"clock_source_id": "mono:bootA", "t_ms": 1000}, {"clock_source_id": "wall:ntp", "t_ms": 1450}), "INCOMPARABLE"),
     ("K-02 same clock", judge_delta({"clock_source_id": "mono:bootA", "t_ms": 1000}, {"clock_source_id": "mono:bootA", "t_ms": 1450}), 450),
     ("R-01 clean but no window", judge_ref({"excludes_eval_day": True}), "REF_WINDOW_UNDECLARED"),
     ("R-02 window declared", judge_ref({"ref_start": "2026-10-07", "ref_end": "2026-10-20", "ref_n": 14}), "OK"),
    ]
    for name, got, exp in side:
        ok = got == exp; bad += not ok
        print(("PASS " if ok else "FAIL ") + name, got)
    print("ALL_PASS" if bad == 0 else f"{bad} FAIL")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
