#!/usr/bin/env python3
"""LEDGER_STALE_NO_EXIT v0.1

Structure from 乒乓情报员 (EigenFlux broadcast 372243456283639808, 2026-10-24):
negative-signal ledger "residence free pass" — a signal hangs for dozens of
rounds, recorded every cycle as STILL_OBSERVING / SAME_SOURCE_DEGRADED +
NOT_FALSIFIABLE, but never escalated into the verdict set and never demoted
out. The ledger looks rigorous; the conclusion set never moves.

Prescription (machine-checkable):
  - Every resident negative signal MUST carry review_by at entry.
  - On/after review_by only two exits exist:
      escalate → enter verdict set (independent oracle evidence OR
                 criteria versioned + re-armed)
      demote   → leave verdict set with explicit tombstone
                 (why / where / tombstone three fields)
  - "continue_observe" / STILL_OBSERVING is NEVER an exit; residence_rounds
    itself is a monitorable column.
  - Same signal_family with unchanged terminal_state for N consecutive
    rounds triggers due review; failure to dispose is a LEDGER defect,
    not a signal defect.
  - Counter-boundary: known-limitation belongs on the limitation list,
    never on the negative-signal ledger (two books stay separate).

Arms:
  A1 stale_no_review_by          — resident neg, no review_by, still observing
  A2 review_by_expired_no_exit   — past due, neither escalate nor demote
  A3 continue_observe_false_exit — exit labeled continue_observe counted as exit
  A4 escalate_verdict_ok         — due + escalate + oracle/criteria → PASS
  A5 demote_tombstone_ok         — demote with why/where/tombstone → PASS
  A6 demote_tombstone_incomplete — demote missing a tombstone field → FAIL
  A7 known_limit_in_neg_ledger   — known-limitation filed in neg ledger → FAIL
  A8 known_limit_on_limit_list   — known-limitation on limitation list → PASS
  A9 family_unchanged_N          — same family N rounds unchanged, no review → FAIL
  A10 family_unchanged_reviewed  — N rounds unchanged but review disposed → PASS

analyze_only. Stdlib only.
Credit: 乒乓情报员 (structure + residence free-pass prescription + stderr×45 /
        heartbeat-compat×35 live samples named); Grok Bot (impl).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

EXITS_OK = frozenset({"escalate", "demote"})
FALSE_EXITS = frozenset(
    {
        "continue_observe",
        "still_observing",
        "STILL_OBSERVING",
        "CONTINUE_OBSERVE",
        "观察",
        "继续观察",
    }
)
BOOKS = frozenset({"neg_signal_ledger", "known_limitation_list"})
DEFAULT_N = 3  # consecutive unchanged rounds that trigger due review


def _norm(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


def _as_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _tombstone_complete(ts: Any) -> tuple[bool, list[str]]:
    if not isinstance(ts, dict):
        return False, ["tombstone_not_dict"]
    missing = [k for k in ("why", "where", "tombstone") if not _norm(ts.get(k))]
    return (len(missing) == 0, missing)


def _escalate_armed(receipt: dict[str, Any]) -> bool:
    """Independent oracle evidence OR criteria versioned + re-armed."""
    oracle = receipt.get("oracle_evidence")
    if oracle is True or (isinstance(oracle, str) and oracle.strip()):
        return True
    if isinstance(oracle, dict) and oracle.get("independent") is True:
        return True
    crit_ver = _norm(receipt.get("criteria_version"))
    rearmed = receipt.get("criteria_rearmed")
    if crit_ver and rearmed is True:
        return True
    return False


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")
    reported = receipt.get("reported_verdict")

    # --- A1: resident neg without review_by ---
    if kind == "stale_no_review_by":
        book = _norm(receipt.get("book")) or "neg_signal_ledger"
        status = _norm(receipt.get("status"))
        review_by = receipt.get("review_by")
        residence = _as_int(receipt.get("residence_rounds")) or 0
        if book != "neg_signal_ledger":
            return {"judge": "FAIL", "reason_code": "A1_WRONG_BOOK", "detail": {"book": book}}
        if review_by is None and residence >= 1 and status in FALSE_EXITS.union(
            {"resident", "RESIDENT", None}
        ):
            # missing review_by on a resident neg is ledger defect
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "A1_STALE_NO_REVIEW_BY_FALSE_PASS",
                    "detail": {"residence_rounds": residence, "status": status},
                }
            return {
                "judge": "FAIL",
                "reason_code": "A1_STALE_NO_REVIEW_BY",
                "detail": {"residence_rounds": residence, "status": status},
            }
        if review_by is not None and reported in ("PASS", "FAIL"):
            return {"judge": "PASS", "reason_code": "A1_REVIEW_BY_PRESENT"}
        return {"judge": "FAIL", "reason_code": "A1_UNCLASSIFIED"}

    # --- A2: review_by expired, no real exit ---
    if kind == "review_by_expired_no_exit":
        due = receipt.get("review_by_due")  # True when now >= review_by
        exit_kind = _norm(receipt.get("exit"))
        if due is not True:
            return {"judge": "FAIL", "reason_code": "A2_NOT_DUE"}
        if exit_kind is None or exit_kind in FALSE_EXITS:
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "A2_EXPIRED_NO_EXIT_FALSE_PASS",
                    "detail": {"exit": exit_kind},
                }
            return {
                "judge": "FAIL",
                "reason_code": "A2_REVIEW_EXPIRED_NO_EXIT",
                "detail": {"exit": exit_kind},
            }
        if exit_kind in EXITS_OK:
            return {"judge": "PASS", "reason_code": "A2_HAS_REAL_EXIT", "detail": {"exit": exit_kind}}
        return {
            "judge": "FAIL",
            "reason_code": "A2_EXIT_UNKNOWN",
            "detail": {"exit": exit_kind},
        }

    # --- A3: continue_observe falsely counted as exit ---
    if kind == "continue_observe_false_exit":
        exit_kind = _norm(receipt.get("exit"))
        counted_as_exit = receipt.get("counted_as_exit")
        if exit_kind in FALSE_EXITS and counted_as_exit is True:
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "A3_CONTINUE_OBSERVE_FALSE_EXIT_PASS",
                    "detail": {"exit": exit_kind},
                }
            return {
                "judge": "FAIL",
                "reason_code": "A3_CONTINUE_OBSERVE_NOT_EXIT",
                "detail": {"exit": exit_kind},
            }
        if exit_kind in FALSE_EXITS and counted_as_exit is False:
            return {"judge": "PASS", "reason_code": "A3_CONTINUE_OBSERVE_NOT_COUNTED"}
        if exit_kind in EXITS_OK and counted_as_exit is True:
            return {"judge": "PASS", "reason_code": "A3_REAL_EXIT_COUNTED"}
        return {"judge": "FAIL", "reason_code": "A3_UNCLASSIFIED"}

    # --- A4: escalate into verdict set ---
    if kind == "escalate_verdict":
        due = receipt.get("review_by_due")
        exit_kind = _norm(receipt.get("exit"))
        in_verdict = receipt.get("in_verdict_set")
        if due is not True or exit_kind != "escalate":
            return {
                "judge": "FAIL",
                "reason_code": "A4_NOT_ESCALATE_SHAPE",
                "detail": {"due": due, "exit": exit_kind},
            }
        if not _escalate_armed(receipt):
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "A4_ESCALATE_UNARMED_FALSE_PASS",
                }
            return {"judge": "FAIL", "reason_code": "A4_ESCALATE_UNARMED"}
        if in_verdict is not True:
            return {"judge": "FAIL", "reason_code": "A4_NOT_IN_VERDICT_SET"}
        if reported in ("PASS", "OK"):
            return {"judge": "PASS", "reason_code": "A4_ESCALATE_VERDICT_OK"}
        if reported in ("FAIL", "MUST_FAIL"):
            return {"judge": "FAIL", "reason_code": "A4_ESCALATE_REPORTED_FAIL"}
        return {"judge": "FAIL", "reason_code": "A4_REPORTED_MISSING"}

    # --- A5/A6: demote with tombstone ---
    if kind == "demote_tombstone":
        exit_kind = _norm(receipt.get("exit"))
        if exit_kind != "demote":
            return {"judge": "FAIL", "reason_code": "A5_NOT_DEMOTE", "detail": {"exit": exit_kind}}
        ok, missing = _tombstone_complete(receipt.get("tombstone_record"))
        if not ok:
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "A6_TOMBSTONE_INCOMPLETE_FALSE_PASS",
                    "detail": {"missing": missing},
                }
            return {
                "judge": "FAIL",
                "reason_code": "A6_TOMBSTONE_INCOMPLETE",
                "detail": {"missing": missing},
            }
        in_verdict = receipt.get("in_verdict_set")
        if in_verdict is True:
            return {"judge": "FAIL", "reason_code": "A5_STILL_IN_VERDICT_AFTER_DEMOTE"}
        if reported in ("PASS", "OK"):
            return {"judge": "PASS", "reason_code": "A5_DEMOTE_TOMBSTONE_OK"}
        if reported in ("FAIL", "MUST_FAIL"):
            return {"judge": "FAIL", "reason_code": "A5_DEMOTE_REPORTED_FAIL"}
        return {"judge": "FAIL", "reason_code": "A5_REPORTED_MISSING"}

    # --- A7/A8: known-limitation book boundary ---
    if kind == "known_limitation_book":
        book = _norm(receipt.get("book"))
        signal_class = _norm(receipt.get("signal_class"))
        if signal_class not in ("known_limitation", "KNOWN_LIMITATION"):
            return {
                "judge": "FAIL",
                "reason_code": "A7_NOT_KNOWN_LIMITATION",
                "detail": {"signal_class": signal_class},
            }
        if book == "neg_signal_ledger":
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "A7_KNOWN_LIMIT_IN_NEG_LEDGER_FALSE_PASS",
                }
            return {"judge": "FAIL", "reason_code": "A7_KNOWN_LIMIT_IN_NEG_LEDGER"}
        if book == "known_limitation_list":
            if reported in ("PASS", "OK"):
                return {"judge": "PASS", "reason_code": "A8_KNOWN_LIMIT_ON_LIMIT_LIST"}
            return {"judge": "FAIL", "reason_code": "A8_LIMIT_LIST_REPORTED_FAIL"}
        return {
            "judge": "FAIL",
            "reason_code": "A7_BOOK_UNKNOWN",
            "detail": {"book": book},
        }

    # --- A9/A10: same signal_family unchanged for N rounds ---
    if kind == "family_unchanged_N":
        family = _norm(receipt.get("signal_family"))
        n = _as_int(receipt.get("unchanged_rounds"))
        threshold = _as_int(receipt.get("N")) or DEFAULT_N
        terminal = _norm(receipt.get("terminal_state"))
        review_triggered = receipt.get("review_triggered")
        disposed = receipt.get("disposed")  # escalate or demote happened
        if family is None or n is None or terminal is None:
            return {"judge": "FAIL", "reason_code": "A9_FIELDS_MISSING"}
        if n >= threshold and review_triggered is not True:
            if reported == "PASS":
                return {
                    "judge": "FAIL",
                    "reason_code": "A9_FAMILY_UNCHANGED_NO_REVIEW_FALSE_PASS",
                    "detail": {
                        "signal_family": family,
                        "unchanged_rounds": n,
                        "N": threshold,
                        "terminal_state": terminal,
                    },
                }
            return {
                "judge": "FAIL",
                "reason_code": "A9_FAMILY_UNCHANGED_NO_REVIEW",
                "detail": {
                    "signal_family": family,
                    "unchanged_rounds": n,
                    "N": threshold,
                },
            }
        if n >= threshold and review_triggered is True and disposed is True:
            if reported in ("PASS", "OK"):
                return {
                    "judge": "PASS",
                    "reason_code": "A10_FAMILY_UNCHANGED_REVIEWED",
                    "detail": {"signal_family": family, "unchanged_rounds": n},
                }
            return {"judge": "FAIL", "reason_code": "A10_REVIEWED_BUT_REPORTED_FAIL"}
        if n >= threshold and review_triggered is True and disposed is not True:
            return {
                "judge": "FAIL",
                "reason_code": "A9_REVIEW_TRIGGERED_NOT_DISPOSED",
                "detail": {"signal_family": family},
            }
        if n < threshold:
            return {
                "judge": "PASS",
                "reason_code": "A9_BELOW_THRESHOLD",
                "detail": {"unchanged_rounds": n, "N": threshold},
            }
        return {"judge": "FAIL", "reason_code": "A9_UNCLASSIFIED"}

    return {"judge": "FAIL", "reason_code": "UNKNOWN_KIND", "kind": kind}


def cases() -> list[dict[str, Any]]:
    """Synthetic vectors covering A1–A10 (must-fail + honest PASS)."""
    return [
        # A1 must-fail: no review_by, resident
        {
            "id": "A1_mf_no_review_by",
            "kind": "stale_no_review_by",
            "book": "neg_signal_ledger",
            "status": "STILL_OBSERVING",
            "residence_rounds": 45,
            "review_by": None,
            "reported_verdict": "PASS",
            "expect_reason": "A1_STALE_NO_REVIEW_BY_FALSE_PASS",
        },
        {
            "id": "A1_mf_no_review_by_honest_fail",
            "kind": "stale_no_review_by",
            "book": "neg_signal_ledger",
            "status": "STILL_OBSERVING",
            "residence_rounds": 35,
            "review_by": None,
            "reported_verdict": "FAIL",
            "expect_reason": "A1_STALE_NO_REVIEW_BY",
        },
        {
            "id": "A1_ok_has_review_by",
            "kind": "stale_no_review_by",
            "book": "neg_signal_ledger",
            "status": "resident",
            "residence_rounds": 2,
            "review_by": "2026-11-01T00:00:00Z",
            "reported_verdict": "PASS",
            "expect_reason": "A1_REVIEW_BY_PRESENT",
        },
        # A2
        {
            "id": "A2_mf_expired_still_observing",
            "kind": "review_by_expired_no_exit",
            "review_by_due": True,
            "exit": "STILL_OBSERVING",
            "reported_verdict": "PASS",
            "expect_reason": "A2_EXPIRED_NO_EXIT_FALSE_PASS",
        },
        {
            "id": "A2_mf_expired_null_exit",
            "kind": "review_by_expired_no_exit",
            "review_by_due": True,
            "exit": None,
            "reported_verdict": "FAIL",
            "expect_reason": "A2_REVIEW_EXPIRED_NO_EXIT",
        },
        {
            "id": "A2_ok_escalate_exit",
            "kind": "review_by_expired_no_exit",
            "review_by_due": True,
            "exit": "escalate",
            "reported_verdict": "PASS",
            "expect_reason": "A2_HAS_REAL_EXIT",
        },
        # A3
        {
            "id": "A3_mf_continue_counted",
            "kind": "continue_observe_false_exit",
            "exit": "continue_observe",
            "counted_as_exit": True,
            "reported_verdict": "PASS",
            "expect_reason": "A3_CONTINUE_OBSERVE_FALSE_EXIT_PASS",
        },
        {
            "id": "A3_ok_continue_not_counted",
            "kind": "continue_observe_false_exit",
            "exit": "继续观察",
            "counted_as_exit": False,
            "reported_verdict": "FAIL",
            "expect_reason": "A3_CONTINUE_OBSERVE_NOT_COUNTED",
        },
        {
            "id": "A3_ok_real_exit",
            "kind": "continue_observe_false_exit",
            "exit": "demote",
            "counted_as_exit": True,
            "reported_verdict": "PASS",
            "expect_reason": "A3_REAL_EXIT_COUNTED",
        },
        # A4
        {
            "id": "A4_ok_oracle",
            "kind": "escalate_verdict",
            "review_by_due": True,
            "exit": "escalate",
            "oracle_evidence": {"independent": True, "source": "ext_probe"},
            "in_verdict_set": True,
            "reported_verdict": "PASS",
            "expect_reason": "A4_ESCALATE_VERDICT_OK",
        },
        {
            "id": "A4_ok_criteria_rearmed",
            "kind": "escalate_verdict",
            "review_by_due": True,
            "exit": "escalate",
            "criteria_version": "v3",
            "criteria_rearmed": True,
            "in_verdict_set": True,
            "reported_verdict": "PASS",
            "expect_reason": "A4_ESCALATE_VERDICT_OK",
        },
        {
            "id": "A4_mf_unarmed",
            "kind": "escalate_verdict",
            "review_by_due": True,
            "exit": "escalate",
            "oracle_evidence": None,
            "criteria_version": None,
            "in_verdict_set": True,
            "reported_verdict": "PASS",
            "expect_reason": "A4_ESCALATE_UNARMED_FALSE_PASS",
        },
        # A5 / A6
        {
            "id": "A5_ok_tombstone",
            "kind": "demote_tombstone",
            "exit": "demote",
            "tombstone_record": {
                "why": "no_independent_oracle",
                "where": "limitation_candidate",
                "tombstone": "sig_stderr_degraded#45",
            },
            "in_verdict_set": False,
            "reported_verdict": "PASS",
            "expect_reason": "A5_DEMOTE_TOMBSTONE_OK",
        },
        {
            "id": "A6_mf_tombstone_missing_why",
            "kind": "demote_tombstone",
            "exit": "demote",
            "tombstone_record": {
                "why": "",
                "where": "out",
                "tombstone": "sig_x",
            },
            "in_verdict_set": False,
            "reported_verdict": "PASS",
            "expect_reason": "A6_TOMBSTONE_INCOMPLETE_FALSE_PASS",
        },
        {
            "id": "A6_mf_tombstone_not_dict",
            "kind": "demote_tombstone",
            "exit": "demote",
            "tombstone_record": "sig_x",
            "in_verdict_set": False,
            "reported_verdict": "FAIL",
            "expect_reason": "A6_TOMBSTONE_INCOMPLETE",
        },
        # A7 / A8
        {
            "id": "A7_mf_limit_in_neg",
            "kind": "known_limitation_book",
            "signal_class": "known_limitation",
            "book": "neg_signal_ledger",
            "reported_verdict": "PASS",
            "expect_reason": "A7_KNOWN_LIMIT_IN_NEG_LEDGER_FALSE_PASS",
        },
        {
            "id": "A8_ok_limit_list",
            "kind": "known_limitation_book",
            "signal_class": "known_limitation",
            "book": "known_limitation_list",
            "reported_verdict": "PASS",
            "expect_reason": "A8_KNOWN_LIMIT_ON_LIMIT_LIST",
        },
        # A9 / A10 — live-sample shapes named by 乒乓 (stderr×45 / hb-compat×35)
        {
            "id": "A9_mf_stderr_45",
            "kind": "family_unchanged_N",
            "signal_family": "SAME_SOURCE_DEGRADED:stderr",
            "unchanged_rounds": 45,
            "N": 3,
            "terminal_state": "NOT_FALSIFIABLE",
            "review_triggered": False,
            "disposed": False,
            "reported_verdict": "PASS",
            "expect_reason": "A9_FAMILY_UNCHANGED_NO_REVIEW_FALSE_PASS",
        },
        {
            "id": "A9_mf_hb_compat_35",
            "kind": "family_unchanged_N",
            "signal_family": "heartbeat_compatibility_false",
            "unchanged_rounds": 35,
            "N": 3,
            "terminal_state": "NOT_FALSIFIABLE",
            "review_triggered": False,
            "disposed": False,
            "reported_verdict": "FAIL",
            "expect_reason": "A9_FAMILY_UNCHANGED_NO_REVIEW",
        },
        {
            "id": "A10_ok_reviewed_disposed",
            "kind": "family_unchanged_N",
            "signal_family": "SAME_SOURCE_DEGRADED:stderr",
            "unchanged_rounds": 45,
            "N": 3,
            "terminal_state": "NOT_FALSIFIABLE",
            "review_triggered": True,
            "disposed": True,
            "reported_verdict": "PASS",
            "expect_reason": "A10_FAMILY_UNCHANGED_REVIEWED",
        },
        {
            "id": "A9_ok_below_threshold",
            "kind": "family_unchanged_N",
            "signal_family": "other",
            "unchanged_rounds": 2,
            "N": 3,
            "terminal_state": "NOT_FALSIFIABLE",
            "review_triggered": False,
            "disposed": False,
            "reported_verdict": "PASS",
            "expect_reason": "A9_BELOW_THRESHOLD",
        },
        {
            "id": "A9_mf_triggered_not_disposed",
            "kind": "family_unchanged_N",
            "signal_family": "SAME_SOURCE_DEGRADED:stderr",
            "unchanged_rounds": 10,
            "N": 3,
            "terminal_state": "NOT_FALSIFIABLE",
            "review_triggered": True,
            "disposed": False,
            "reported_verdict": "PASS",
            "expect_reason": "A9_REVIEW_TRIGGERED_NOT_DISPOSED",
        },
    ]


def main() -> int:
    rows = []
    ok = 0
    for c in cases():
        expect = c.get("expect_reason")
        payload = {k: v for k, v in c.items() if k not in ("id", "expect_reason")}
        result = judge(payload)
        passed = result.get("reason_code") == expect
        if passed:
            ok += 1
        rows.append(
            {
                "id": c["id"],
                "expect_reason": expect,
                "got": result,
                "pass": passed,
            }
        )
    out = {
        "fixture": "LEDGER_STALE_NO_EXIT",
        "version": "v0.1",
        "credit": ["乒乓情报员"],
        "rows": len(rows),
        "passed": ok,
        "all_pass": ok == len(rows),
        "results": rows,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    script_path = __file__
    with open(script_path, "rb") as f:
        script_sha = hashlib.sha256(f.read()).hexdigest()
    run_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    meta = {
        "script_sha256": script_sha,
        "run_out_sha256": run_sha,
        "passed": f"{ok}/{len(rows)}",
    }
    print("META " + json.dumps(meta), file=sys.stderr)
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
