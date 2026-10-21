#!/usr/bin/env python3
"""LEMF v0.5 (adds LOOKAHEAD_READ, NUMBER_UNSOURCED [spec: 戴笠], NEUTRAL_REF_INSUFFICIENT + declared lookback backoff [q: 贺水仙的大龙虾])
LEMF v0.4 (adds ABSTAIN terminal, dual pass rate, neutral_ref provenance, share-drift window; spec: 荷马史诗)
LEMF v0.3 — intraday full-day turnover extrapolation contract (spec: 荷马史诗).
analyze_only. No accuracy check: a forecast is judged on its contract, not on whether the number was right.
Five gates, any miss = FAIL (v0.3 is NOT backward compatible: the triplet is now a quadruple):
  TRIPLET_MISSING          every extrapolated value carries (read_at, cum_at_read, share_assumption, share_assumption_at)
  SHARE_TIME_MISMATCH      |share_assumption_at - read_at| > 15 min  (荷马史诗: 11:00 share applied to an 11:32 reading
                           on 10/21 overshot the close by 16.1%; the gate checks the convention, not the number)
  THRESHOLD_MISLABELED     void threshold must carry thr_label + neutral_ref; label NEUTRAL only if |thr-neutral_ref|<=0.01,
                           otherwise it must be CONSERVATIVE_xxx (a conservative cut must never read as a "stricter method")
  VOID_UNOBSERVABLE        the share assumption names a same-day void condition computable from
                           readings timestamped <= the time it is evaluated (no 'if close is below...')
  CONTINUED_AFTER_VOID     once the void condition fires, every later output declares void and gives NO number
                           (a 'corrected' number is a FAIL: it hides the failure)
"""
import json, sys, hashlib

FIXTURE_VERSION = "v0.5-fixtures-20261021"  # frozen: fields will not change under this tag (木木 sign-off anchor)
COLS = ("case_id", "expect", "must_catch", "probe_id")
from pathlib import Path

CLOSE = "15:00"

def t(s): h, m = s.split(":"); return int(h) * 60 + int(m)

def eval_void(cond, readings, at):
    """cond = {"num": "13:05", "den": "11:30", "op": "<", "thr": 0.55}; ratio of cumulative readings.
    Returns (observable, fired)."""
    for k in ("num", "den"):
        if cond.get(k) is None or t(cond[k]) > t(at) or cond[k] not in readings:
            return False, False
    if cond.get("uses_close") or t(cond["num"]) >= t(CLOSE):
        return False, False
    r = readings[cond["num"]] / readings[cond["den"]]
    fired = r < cond["thr"] if cond["op"] == "<" else r > cond["thr"]
    return True, fired

def judge(case):
    rd = case["readings"]
    void_at = None
    outs = case["outputs"]
    if outs and all(o.get("value") is None and o.get("abstain_reason") for o in outs):
        return "ABSTAIN"   # v0.4: abstaining is its own terminal state, never PASS
    for o in case["outputs"]:
        at = o["at"]
        cond = case.get("_cond")
        if cond and void_at is None:
            obs, fired = eval_void(cond, rd, at)
            if obs and fired:
                void_at = at          # condition fired at or before this output
        if void_at is not None:
            if o.get("value") is not None or not o.get("declared_void"):
                return "CONTINUED_AFTER_VOID"
            continue
        if o.get("value") is not None:
            trip = o.get("triplet") or {}
            if any(trip.get(k) is None for k in ("read_at", "cum_at_read", "share_assumption", "share_assumption_at")):
                return "TRIPLET_MISSING"
            # v0.5 LOOKAHEAD_READ: an output may only use a reading taken at or before the output time.
            if t(trip["read_at"]) > t(at):
                return "LOOKAHEAD_READ"
            # v0.5 NUMBER_UNSOURCED: the number must be reproducible from its own quadruple and the day's readings.
            # cum_at_read must equal readings[read_at]; value must equal cum_at_read/share_assumption within 0.5%,
            # unless an explicit `adjustment` {factor, source} is declared (then value = cum/share*factor).
            if trip["read_at"] in rd and trip["cum_at_read"] != rd[trip["read_at"]]:
                return "NUMBER_UNSOURCED"
            adj = trip.get("adjustment") or {}
            if adj and not adj.get("source"):
                return "NUMBER_UNSOURCED"
            implied = trip["cum_at_read"] / trip["share_assumption"] * adj.get("factor", 1.0)
            if abs(o["value"] - implied) / implied > 0.005:
                return "NUMBER_UNSOURCED"
            curve = trip.get("share_curve")   # v0.4: {"HH:MM": cumulative share}, empirical, declared
            if curve:
                a, b = trip["share_assumption_at"], trip["read_at"]
                if a not in curve or b not in curve:
                    return "SHARE_TIME_MISMATCH"
                if abs(curve[a] - curve[b]) > 0.01:   # |delta share| <= 1pp, window adapts to the curve slope
                    return "SHARE_TIME_MISMATCH"
            elif abs(t(trip["share_assumption_at"]) - t(trip["read_at"])) > 15:
                return "SHARE_TIME_MISMATCH"
            cond = trip.get("void_condition")
            if not cond:
                return "VOID_UNOBSERVABLE"
            if not cond.get("uses_close") and t(cond.get("num", CLOSE)) < t(CLOSE):
                lab, ref = cond.get("thr_label"), cond.get("neutral_ref")
                if lab is None or ref is None:
                    return "THRESHOLD_MISLABELED"
                srcd = cond.get("neutral_ref_src") or {}
                # v0.4: neutral_ref must trace to a rolling N-day measured distribution, not to the day it judges
                # v0.5 backoff: thin history (holidays, new listing, halted sessions) may extend the lookback to at most
                # 3x window_days, declared as backoff={"extended_to_days": K}; it still needs n_samples >= 5.
                # The eval day is NEVER a fallback. Fewer than 5 clean samples => NEUTRAL_REF_INSUFFICIENT if a number
                # is emitted (the correct terminal is ABSTAIN with abstain_reason=NEUTRAL_REF_INSUFFICIENT).
                bo = srcd.get("backoff") or {}
                wd, ns = srcd.get("window_days"), srcd.get("n_samples")
                if (not isinstance(wd, int) or wd < 5 or not isinstance(ns, int)
                        or not (0 <= srcd.get("quantile", -1) <= 1) or srcd.get("includes_eval_day", True)):
                    return "NEUTRAL_REF_UNSOURCED"
                if ns < wd:
                    k = bo.get("extended_to_days")
                    if not isinstance(k, int) or k <= wd or k > 3 * wd:
                        return "NEUTRAL_REF_UNSOURCED" if not bo else "NEUTRAL_REF_INSUFFICIENT"
                    if ns < 5:
                        return "NEUTRAL_REF_INSUFFICIENT"
                if lab == "NEUTRAL" and abs(cond["thr"] - ref) > 0.01:
                    return "THRESHOLD_MISLABELED"
                if lab != "NEUTRAL" and not lab.startswith("CONSERVATIVE_"):
                    return "THRESHOLD_MISLABELED"
            obs, _ = eval_void(cond, rd, CLOSE)
            if not obs:
                return "VOID_UNOBSERVABLE"
            case["_cond"] = cond
    return "PASS"

def rates(verdicts):
    p = sum(v == "PASS" for v in verdicts); a = sum(v == "ABSTAIN" for v in verdicts); f = len(verdicts) - p - a
    excl = p / (p + f) if p + f else None
    incl = p / len(verdicts) if verdicts else None
    return p, f, a, excl, incl

def always_abstain(c):
    c = json.loads(json.dumps(c))
    c["outputs"] = [{"at": o["at"], "value": None, "abstain_reason": "ALWAYS"} for o in c["outputs"]]
    return c

def main():
    rows = [json.loads(l) for l in Path(__file__).with_name("fixtures.jsonl").read_text().splitlines() if l.strip()]
    bad = 0
    print("fixture_version", FIXTURE_VERSION)
    for c in rows:
        if list(c)[:4] != list(COLS) or c["must_catch"] != (c["expect"] != "PASS"):
            bad += 1; print("BAD columns", c.get("case_id"))
    seen = {}
    for c in rows:   # merge rule: two rows may only collapse if probe_id differs -> same probe_id + same expect + same inputs is a dup
        key = (c["probe_id"], c["expect"], json.dumps({k: v for k, v in c.items() if k not in ("case_id", "provenance", "note")}, sort_keys=True))
        if key in seen: bad += 1; print("BAD duplicate", c["case_id"], "==", seen[key])
        seen[key] = c["case_id"]
    for c in rows:
        got = judge(dict(c))
        ok = got == c["expect"]
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {c['case_id']:<44} prov={c.get("provenance","?"):<26} expect={c['expect']:<22} got={got}")
    # counterexample: an implementation that abstains on every input
    v = [judge(always_abstain(c)) for c in rows]
    p, f, a, excl, incl = rates(v)
    print(f"always-abstain impl: pass={p} fail={f} abstain={a} pass/(pass+fail)={excl} pass/(all)={incl:.3f}  "
          f"[v0.3 judge would have scored this {len(rows)}/{len(rows)} PASS]")
    if a != len(rows):
        bad += 1; print("BAD always-abstain must be ABSTAIN on every row")
    print("fixtures_sha256", hashlib.sha256(Path(__file__).with_name("fixtures.jsonl").read_bytes()).hexdigest())
    print("RESULT", "PASS" if bad == 0 else f"FAIL ({bad})")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
