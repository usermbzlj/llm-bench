#!/usr/bin/env python3
"""SCHEMA_ABSENT_ALARM v0.1

Structure-only fixture. Failure shapes from Jerry (EigenFlux):

  1. SCHEMA_ABSENT_NO_ALARM — schema row never existed (schema_row_present
     is null/false-from-never), so a param change produces no alarm.
     Reporting OK / NO_ALARM / silent is a must-fail (假静默).
  2. NOT_COLLECTED_AS_ABSENT — this-round not collected conflated with
     schema-never-existed. Distinct states: SCHEMA_ABSENT vs
     NOT_COLLECTED_THIS_ROUND. Mixing → must-fail.
  3. PAGE_WIDTH_SILENT_DROP — same query_shape_digest; 4th (or later)
     same-shape request silently dropped when page_width changes the
     expected page set. No drop receipt / no alarm → must-fail.
  4. Honest arms for each family (alarm fires, or explicit
     NOT_COLLECTED / DROP_RECORDED states).

Honest path:
  - schema_row_present=false (never) + param_changed → must alarm
    (SCHEMA_ABSENT_ALARM) or explicit FAIL, never silent OK.
  - schema_row_present=true + collected=false → NOT_COLLECTED_THIS_ROUND
    (not SCHEMA_ABSENT).
  - same query_shape_digest + drop_ordinal>=4 + page_width delta →
    DROP_RECORDED or alarm; silent success forbidden.

General fixture; analyze_only. Stdlib only.
Credit: Jerry (structure); Grok Bot (impl).
"""
from __future__ import annotations

import json
import sys
from typing import Any


def _present_state(receipt: dict[str, Any]) -> str:
    """Normalize schema presence into never|present|unknown."""
    v = receipt.get("schema_row_present")
    if v is True:
        return "present"
    if v is False:
        # distinguish never-existed vs collected-false via provenance
        prov = receipt.get("schema_provenance")  # never|deleted|unknown|None
        if prov == "never" or prov is None:
            return "never"
        return "absent_other"
    return "unknown"


def judge(receipt: dict[str, Any]) -> dict[str, Any]:
    kind = receipt.get("kind")

    if kind == "schema_alarm":
        present = _present_state(receipt)
        param_changed = bool(receipt.get("param_changed"))
        collected_this_round = receipt.get("collected_this_round")
        observed = receipt.get("observed_class")
        # SCHEMA_ABSENT_ALARM | NOT_COLLECTED_THIS_ROUND | OK | NO_ALARM | FAIL

        if present == "never" and param_changed:
            if observed in ("OK", "NO_ALARM", None, ""):
                return {
                    "judge": "FAIL",
                    "reason_code": "SCHEMA_ABSENT_NO_ALARM",
                    "detail": {"present": present, "observed": observed},
                }
            if observed == "SCHEMA_ABSENT_ALARM":
                return {"judge": "PASS", "reason_code": "HONEST_SCHEMA_ABSENT_ALARM"}
            if observed == "FAIL":
                return {"judge": "PASS", "reason_code": "HONEST_SCHEMA_ABSENT_FAIL"}
            if observed == "NOT_COLLECTED_THIS_ROUND":
                return {
                    "judge": "FAIL",
                    "reason_code": "NOT_COLLECTED_AS_ABSENT",
                    "detail": {"note": "never-existed mislabeled as not-collected"},
                }
            return {
                "judge": "FAIL",
                "reason_code": "SCHEMA_ABSENT_UNEXPECTED",
                "detail": {"observed": observed},
            }

        if present == "present" and collected_this_round is False:
            if observed == "SCHEMA_ABSENT_ALARM":
                return {
                    "judge": "FAIL",
                    "reason_code": "NOT_COLLECTED_AS_ABSENT",
                    "detail": {"note": "not-collected labeled as schema-absent"},
                }
            if observed == "NOT_COLLECTED_THIS_ROUND":
                return {"judge": "PASS", "reason_code": "HONEST_NOT_COLLECTED"}
            if observed in ("OK", "NO_ALARM"):
                return {
                    "judge": "FAIL",
                    "reason_code": "NOT_COLLECTED_SILENT_OK",
                    "detail": {"observed": observed},
                }
            return {
                "judge": "FAIL",
                "reason_code": "NOT_COLLECTED_UNEXPECTED",
                "detail": {"observed": observed},
            }

        if present == "present" and collected_this_round is True and not param_changed:
            if observed == "OK":
                return {"judge": "PASS", "reason_code": "HONEST_SCHEMA_OK"}
            return {
                "judge": "FAIL",
                "reason_code": "SCHEMA_OK_UNEXPECTED",
                "detail": {"observed": observed},
            }

        return {
            "judge": "FAIL",
            "reason_code": "SCHEMA_ALARM_UNCLASSIFIED",
            "detail": {
                "present": present,
                "param_changed": param_changed,
                "collected_this_round": collected_this_round,
                "observed": observed,
            },
        }

    if kind == "page_width_drop":
        shape = receipt.get("query_shape_digest")
        page_width = receipt.get("page_width")
        prev_width = receipt.get("prev_page_width")
        drop_ordinal = receipt.get("drop_ordinal")  # 1-based same-shape count
        drop_recorded = receipt.get("drop_recorded")
        alarm_fired = receipt.get("alarm_fired")
        observed = receipt.get("observed_class")
        # OK | DROP_RECORDED | PAGE_WIDTH_SILENT_DROP | ALARM

        if not isinstance(shape, str) or not shape:
            return {"judge": "FAIL", "reason_code": "SHAPE_DIGEST_MISSING"}
        if not isinstance(drop_ordinal, int) or drop_ordinal < 1:
            return {"judge": "FAIL", "reason_code": "DROP_ORDINAL_INVALID"}

        width_changed = (
            prev_width is not None
            and page_width is not None
            and prev_width != page_width
        )

        # 4th+ same-shape with width change must not be silent OK
        if drop_ordinal >= 4 and width_changed:
            if observed in ("OK", "NO_ALARM", None, "") and not drop_recorded and not alarm_fired:
                return {
                    "judge": "FAIL",
                    "reason_code": "PAGE_WIDTH_SILENT_DROP",
                    "detail": {
                        "drop_ordinal": drop_ordinal,
                        "page_width": page_width,
                        "prev_page_width": prev_width,
                        "query_shape_digest": shape,
                    },
                }
            if observed == "DROP_RECORDED" or drop_recorded is True:
                return {"judge": "PASS", "reason_code": "HONEST_DROP_RECORDED"}
            if observed == "ALARM" or alarm_fired is True:
                return {"judge": "PASS", "reason_code": "HONEST_DROP_ALARM"}
            if observed == "PAGE_WIDTH_SILENT_DROP":
                # classifier correctly named the failure mode on a probe
                return {"judge": "PASS", "reason_code": "HONEST_SILENT_DROP_LABELED"}
            return {
                "judge": "FAIL",
                "reason_code": "PAGE_WIDTH_DROP_UNEXPECTED",
                "detail": {"observed": observed, "drop_recorded": drop_recorded},
            }

        # early ordinals or no width change: OK is fine
        if drop_ordinal < 4 or not width_changed:
            if observed == "OK":
                return {"judge": "PASS", "reason_code": "HONEST_EARLY_OR_STABLE"}
            if observed in ("DROP_RECORDED", "ALARM") and drop_ordinal >= 4:
                return {"judge": "PASS", "reason_code": "HONEST_CAUTIOUS_DROP"}
            return {
                "judge": "FAIL",
                "reason_code": "PAGE_WIDTH_EARLY_UNEXPECTED",
                "detail": {"observed": observed, "drop_ordinal": drop_ordinal},
            }

        return {"judge": "FAIL", "reason_code": "PAGE_WIDTH_UNCLASSIFIED"}

    return {"judge": "FAIL", "reason_code": "UNCLASSIFIED", "kind": kind}


FIXTURES = [
    {
        "case_id": "SCHEMA-ABSENT-NO-ALARM",
        "receipt": {
            "kind": "schema_alarm",
            "schema_row_present": False,
            "schema_provenance": "never",
            "param_changed": True,
            "collected_this_round": False,
            "observed_class": "NO_ALARM",
            "note": "schema从未存在，参数变更无告警",
        },
        "expect": "SCHEMA_ABSENT_NO_ALARM",
    },
    {
        "case_id": "SCHEMA-ABSENT-SILENT-OK",
        "receipt": {
            "kind": "schema_alarm",
            "schema_row_present": False,
            "schema_provenance": "never",
            "param_changed": True,
            "collected_this_round": False,
            "observed_class": "OK",
        },
        "expect": "SCHEMA_ABSENT_NO_ALARM",
    },
    {
        "case_id": "HONEST-SCHEMA-ABSENT-ALARM",
        "receipt": {
            "kind": "schema_alarm",
            "schema_row_present": False,
            "schema_provenance": "never",
            "param_changed": True,
            "collected_this_round": False,
            "observed_class": "SCHEMA_ABSENT_ALARM",
        },
        "expect": "HONEST_SCHEMA_ABSENT_ALARM",
    },
    {
        "case_id": "NOT-COLLECTED-AS-ABSENT",
        "receipt": {
            "kind": "schema_alarm",
            "schema_row_present": True,
            "schema_provenance": None,
            "param_changed": False,
            "collected_this_round": False,
            "observed_class": "SCHEMA_ABSENT_ALARM",
            "note": "本轮未采集被标成 schema absent",
        },
        "expect": "NOT_COLLECTED_AS_ABSENT",
    },
    {
        "case_id": "ABSENT-MISLABEL-NOT-COLLECTED",
        "receipt": {
            "kind": "schema_alarm",
            "schema_row_present": False,
            "schema_provenance": "never",
            "param_changed": True,
            "collected_this_round": False,
            "observed_class": "NOT_COLLECTED_THIS_ROUND",
        },
        "expect": "NOT_COLLECTED_AS_ABSENT",
    },
    {
        "case_id": "HONEST-NOT-COLLECTED",
        "receipt": {
            "kind": "schema_alarm",
            "schema_row_present": True,
            "param_changed": False,
            "collected_this_round": False,
            "observed_class": "NOT_COLLECTED_THIS_ROUND",
        },
        "expect": "HONEST_NOT_COLLECTED",
    },
    {
        "case_id": "NOT-COLLECTED-SILENT-OK",
        "receipt": {
            "kind": "schema_alarm",
            "schema_row_present": True,
            "param_changed": False,
            "collected_this_round": False,
            "observed_class": "OK",
        },
        "expect": "NOT_COLLECTED_SILENT_OK",
    },
    {
        "case_id": "HONEST-SCHEMA-OK",
        "receipt": {
            "kind": "schema_alarm",
            "schema_row_present": True,
            "param_changed": False,
            "collected_this_round": True,
            "observed_class": "OK",
        },
        "expect": "HONEST_SCHEMA_OK",
    },
    {
        "case_id": "PAGE-WIDTH-SILENT-DROP-4TH",
        "receipt": {
            "kind": "page_width_drop",
            "query_shape_digest": "qsd:list_users:v3",
            "page_width": 50,
            "prev_page_width": 20,
            "drop_ordinal": 4,
            "drop_recorded": False,
            "alarm_fired": False,
            "observed_class": "OK",
            "note": "同形第4次因 page_width 变化静默丢弃",
        },
        "expect": "PAGE_WIDTH_SILENT_DROP",
    },
    {
        "case_id": "HONEST-DROP-RECORDED",
        "receipt": {
            "kind": "page_width_drop",
            "query_shape_digest": "qsd:list_users:v3",
            "page_width": 50,
            "prev_page_width": 20,
            "drop_ordinal": 4,
            "drop_recorded": True,
            "alarm_fired": False,
            "observed_class": "DROP_RECORDED",
        },
        "expect": "HONEST_DROP_RECORDED",
    },
    {
        "case_id": "HONEST-DROP-ALARM",
        "receipt": {
            "kind": "page_width_drop",
            "query_shape_digest": "qsd:list_users:v3",
            "page_width": 100,
            "prev_page_width": 20,
            "drop_ordinal": 5,
            "drop_recorded": False,
            "alarm_fired": True,
            "observed_class": "ALARM",
        },
        "expect": "HONEST_DROP_ALARM",
    },
    {
        "case_id": "HONEST-EARLY-SAME-SHAPE",
        "receipt": {
            "kind": "page_width_drop",
            "query_shape_digest": "qsd:list_users:v3",
            "page_width": 20,
            "prev_page_width": 20,
            "drop_ordinal": 2,
            "drop_recorded": False,
            "alarm_fired": False,
            "observed_class": "OK",
        },
        "expect": "HONEST_EARLY_OR_STABLE",
    },
]


def main() -> int:
    rows = []
    ok = 0
    for fx in FIXTURES:
        got = judge(fx["receipt"])
        reason = got.get("reason_code")
        passed = reason == fx["expect"]
        if passed:
            ok += 1
        rows.append(
            {
                "case_id": fx["case_id"],
                "expect": fx["expect"],
                "got": reason,
                "judge": got.get("judge"),
                "pass": passed,
                "detail": got.get("detail"),
            }
        )
    out = {
        "fixture": "SCHEMA_ABSENT_ALARM",
        "version": "0.1",
        "total": len(FIXTURES),
        "passed": ok,
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok == len(FIXTURES) else 1


if __name__ == "__main__":
    sys.exit(main())
