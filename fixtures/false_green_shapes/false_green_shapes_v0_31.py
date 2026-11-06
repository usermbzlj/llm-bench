#!/usr/bin/env python3
"""FALSE_GREEN_SHAPES v0.31

Adds two peer-supplied shapes on top of v0.30 (prior files untouched; S7-S44
rows re-run here by import so one command checks S7-S46).

  S45 STALE_MANIFEST_CRITERION_DRIFT / DIR_SCAN_FALSE_GREEN
      exit 0 + non-empty output dir must not green a run whose committed
      manifest is from a prior run_id / input hash / criterion_version.
      Orthogonal to S43 (writer_seq×digest): this axis is cross-run
      freshness of the *committed* manifest vs current invocation.
      Green only when ALL hold:
        - exit_code == 0
        - committed_manifest.run_id == current_run_id
        - committed_manifest.input_sha256 == current_input_sha256
        - committed_manifest.criterion_version == current_criterion_version
        - committed_manifest.artifact_sha256 == readback_sha256
      Naive greens: exit_code==0 / dir_nonempty / status==ok / file_present
      alone. Struct requires the fields above; missing any when claiming OK
      -> UNKNOWN/*_UNDECLARED. Mismatch -> FAIL/STALE_MANIFEST.
      Credit: 凯瑞's Agent (EigenFlux — synthetic must-fail/green-twin rows
      for criterion_version drift + stale dir/manifest; explicitly NOT an
      observed incident).

  S46 IDEMPOTENCY_KEY_ROWCOUNT_COLLISION / LEDGER_GAP_FALSE_HIT
      Presence of an idempotency_key + duplicate_key_hit must not green when
      the key was derived from local ledger row count (or equivalent gap-
      sensitive local state). Missing ledger rows can make two different
      payloads share a key; naive treats that as idempotent replay.
      Distinct from S21 (key absent), S26 (key unstable across attempts),
      S37 (non-idempotent replay / dup rows).
      Struct requires:
        - key_derivation (str): "content_digest" | "external_issuer" |
          "ledger_row_count" | other
        - claimed_idempotent (bool)
        - ledger_rows_missing (int; gaps in local ledger used for keying)
        - payload_digest_a / payload_digest_b (str; the two attempts)
      Rules:
        - claiming idempotent without key_derivation -> UNKNOWN
        - key_derivation in (ledger_row_count,) and ledger_rows_missing>0
          and payload digests differ and claimed_idempotent ->
          FAIL/KEY_COLLISION_FALSE_IDEMPOTENT
        - key_derivation in (content_digest, external_issuer) and digests
          equal and claimed_idempotent -> OK
        - digests differ and claimed_idempotent and derivation safe ->
          FAIL (should not claim hit)
      Credit: WorkBuddy (EigenFlux PM — multi-account publish pipeline;
      ledger gap → same key → false idempotent hit; also notes terminal-
      state undeclared hiding backlog — tracked as open owe).

analyze_only. Stdlib only. Run: python3 false_green_shapes_v0_31.py
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import false_green_shapes_v0_30 as v30


def s45_naive(r):
    if r.get("exit_code") == 0:
        return "OK"
    if r.get("dir_nonempty") is True:
        return "OK"
    if r.get("file_present") is True:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    return "FAIL"


def s45_struct(r):
    claiming = (
        r.get("exit_code") == 0
        or r.get("dir_nonempty") is True
        or r.get("file_present") is True
        or r.get("status") == "ok"
        or r.get("ok") is True
    )
    need = (
        "current_run_id", "current_input_sha256", "current_criterion_version",
        "manifest_run_id", "manifest_input_sha256", "manifest_criterion_version",
        "manifest_artifact_sha256", "readback_sha256", "exit_code",
    )
    for k in need:
        if k not in r:
            if claiming:
                return f"UNKNOWN/{k.upper()}_UNDECLARED"
            return "UNKNOWN/MANIFEST_FIELDS_UNDECLARED"
    try:
        exit_code = int(r["exit_code"])
    except (TypeError, ValueError):
        return "UNKNOWN/EXIT_CODE_NOT_INT"
    if exit_code != 0:
        return "FAIL"
    if r["manifest_run_id"] != r["current_run_id"]:
        return "FAIL/STALE_MANIFEST"
    if r["manifest_input_sha256"] != r["current_input_sha256"]:
        return "FAIL/STALE_MANIFEST"
    if r["manifest_criterion_version"] != r["current_criterion_version"]:
        return "FAIL/STALE_MANIFEST"
    if r["manifest_artifact_sha256"] != r["readback_sha256"]:
        return "FAIL/STALE_MANIFEST"
    return "OK"


def s46_naive(r):
    if r.get("claimed_idempotent") is True:
        return "OK"
    if r.get("idempotency_key_present") is True and r.get("duplicate_key_hit") is True:
        return "OK"
    if r.get("status") == "ok":
        return "OK"
    if r.get("ok") is True:
        return "OK"
    return "FAIL"


def s46_struct(r):
    claiming = (
        r.get("claimed_idempotent") is True
        or (r.get("idempotency_key_present") is True and r.get("duplicate_key_hit") is True)
        or r.get("status") == "ok"
        or r.get("ok") is True
    )
    if "key_derivation" not in r:
        if claiming:
            return "UNKNOWN/KEY_DERIVATION_UNDECLARED"
        return "UNKNOWN/KEY_DERIVATION_UNDECLARED"
    deriv = r.get("key_derivation")
    for k in ("payload_digest_a", "payload_digest_b", "claimed_idempotent"):
        if k not in r:
            if claiming:
                return f"UNKNOWN/{k.upper()}_UNDECLARED"
            return "UNKNOWN/KEY_COLLISION_FIELDS_UNDECLARED"
    if "ledger_rows_missing" not in r and deriv == "ledger_row_count":
        return "UNKNOWN/LEDGER_ROWS_MISSING_UNDECLARED"
    missing = r.get("ledger_rows_missing", 0)
    try:
        missing_i = int(missing)
    except (TypeError, ValueError):
        return "UNKNOWN/LEDGER_ROWS_MISSING_NOT_INT"
    dig_a = r.get("payload_digest_a")
    dig_b = r.get("payload_digest_b")
    claimed = r.get("claimed_idempotent") is True
    if deriv == "ledger_row_count" and missing_i > 0 and dig_a != dig_b and claimed:
        return "FAIL/KEY_COLLISION_FALSE_IDEMPOTENT"
    if dig_a != dig_b and claimed:
        return "FAIL/KEY_COLLISION_FALSE_IDEMPOTENT"
    if dig_a == dig_b and claimed and deriv in ("content_digest", "external_issuer"):
        return "OK"
    if dig_a == dig_b and claimed and deriv == "ledger_row_count" and missing_i == 0:
        # same digest + no gap: collision risk not proven; still OK on content
        return "OK"
    if not claimed:
        return "FAIL"
    return "OK"


NEW_ROWS = [
  ("S45-mf-stale-manifest-criterion", "S45", "synthetic_peer_agent(凯瑞的 Agent)",
   {"arm": "criterion_v1_artifact_lingers_under_v2",
    "current_run_id": "r2", "current_input_sha256": "I2",
    "current_criterion_version": "v2",
    "manifest_run_id": "r1", "manifest_input_sha256": "I1",
    "manifest_criterion_version": "v1",
    "manifest_artifact_sha256": "D1", "readback_sha256": "D1",
    "exit_code": 0, "dir_nonempty": True, "file_present": True,
    "status": "ok"},
   "FAIL/STALE_MANIFEST", True),
  ("S45-mf-input-hash-drift", "S45", "hand_built",
   {"current_run_id": "r2", "current_input_sha256": "I2",
    "current_criterion_version": "v2",
    "manifest_run_id": "r2", "manifest_input_sha256": "I1",
    "manifest_criterion_version": "v2",
    "manifest_artifact_sha256": "D2", "readback_sha256": "D2",
    "exit_code": 0, "dir_nonempty": True, "status": "ok"},
   "FAIL/STALE_MANIFEST", True),
  ("S45-mf-readback-mismatch", "S45", "hand_built",
   {"current_run_id": "r2", "current_input_sha256": "I2",
    "current_criterion_version": "v2",
    "manifest_run_id": "r2", "manifest_input_sha256": "I2",
    "manifest_criterion_version": "v2",
    "manifest_artifact_sha256": "D2", "readback_sha256": "D9",
    "exit_code": 0, "dir_nonempty": True, "status": "ok"},
   "FAIL/STALE_MANIFEST", True),
  ("S45-gt-fresh-manifest", "S45", "synthetic_peer_agent(凯瑞的 Agent)",
   {"current_run_id": "r2", "current_input_sha256": "I2",
    "current_criterion_version": "v2",
    "manifest_run_id": "r2", "manifest_input_sha256": "I2",
    "manifest_criterion_version": "v2",
    "manifest_artifact_sha256": "D2", "readback_sha256": "D2",
    "exit_code": 0, "dir_nonempty": True, "file_present": True,
    "status": "ok"},
   "OK", False),
  ("S45-ct-manifest-undeclared", "S45", "hand_built",
   {"exit_code": 0, "dir_nonempty": True, "status": "ok"},
   "UNKNOWN/CURRENT_RUN_ID_UNDECLARED", True),
  ("S46-mf-rowcount-collision", "S46", "observed_shape_desensitized(WorkBuddy)",
   {"arm": "ledger_gap_same_key_different_payload",
    "key_derivation": "ledger_row_count",
    "ledger_rows_missing": 3,
    "payload_digest_a": "pay-A", "payload_digest_b": "pay-B",
    "claimed_idempotent": True, "idempotency_key_present": True,
    "duplicate_key_hit": True, "status": "ok"},
   "FAIL/KEY_COLLISION_FALSE_IDEMPOTENT", True),
  ("S46-mf-digest-differ-claimed", "S46", "hand_built",
   {"key_derivation": "content_digest",
    "ledger_rows_missing": 0,
    "payload_digest_a": "pay-A", "payload_digest_b": "pay-B",
    "claimed_idempotent": True, "status": "ok"},
   "FAIL/KEY_COLLISION_FALSE_IDEMPOTENT", True),
  ("S46-gt-content-digest-hit", "S46", "hand_built",
   {"key_derivation": "content_digest",
    "ledger_rows_missing": 0,
    "payload_digest_a": "pay-A", "payload_digest_b": "pay-A",
    "claimed_idempotent": True, "idempotency_key_present": True,
    "duplicate_key_hit": True},
   "OK", False),
  ("S46-gt-external-issuer", "S46", "hand_built",
   {"key_derivation": "external_issuer",
    "ledger_rows_missing": 0,
    "payload_digest_a": "pay-A", "payload_digest_b": "pay-A",
    "claimed_idempotent": True},
   "OK", False),
  ("S46-ct-derivation-undeclared", "S46", "hand_built",
   {"claimed_idempotent": True, "idempotency_key_present": True,
    "duplicate_key_hit": True, "status": "ok"},
   "UNKNOWN/KEY_DERIVATION_UNDECLARED", True),
]

FNS = dict(v30.FNS)
FNS.update({"S45": (s45_naive, s45_struct), "S46": (s46_naive, s46_struct)})
ROWS = list(v30.ROWS) + NEW_ROWS
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
    new_wrong = sum(1 for r in out if r["shape"] in ("S45", "S46") and r["naive"] != r["expected"])
    res = {"fixture": "FALSE_GREEN_SHAPES", "version": "0.31", "selftest": f"{ok}/{total}",
           "naive_wrong_rows": naive_wrong, "naive_wrong_new_shapes": f"{new_wrong}/{len(NEW_ROWS)}",
           "naive_forced_verdicts_on_cant_tell": forced, "forced_verdict_control": ctl, "rows": out}
    json.dump(res, open("run_out_v0_31.json", "w"), ensure_ascii=False, indent=1)
    print(f"selftest {ok}/{total}; naive wrong {naive_wrong}/{len(ROWS)} (new shapes {new_wrong}/{len(NEW_ROWS)}); forced verdicts on can't-tell {forced}/{len(ct)}")
    for r in out:
        if not r["pass"]:
            print("FAIL_ROW", r)
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())
