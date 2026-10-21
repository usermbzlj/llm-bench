#!/usr/bin/env python3
"""sampled-digest coverage judge v0.1  (data + must-fail criterion: Hermes on EigenFlux)
analyze_only, stdlib only.

A change detector that hashes size + head window + tail window (instead of the whole file)
can only ever say CHANGED or SAMPLED_MISS. A miss is NOT evidence of "unchanged".
Rules:
  coverage = covered_bytes / file_size
  hit                              -> CHANGED
  miss, coverage == 1.0            -> UNCHANGED (full hash)
  miss, coverage <  1.0            -> SAMPLED_MISS   (never UNCHANGED)
  miss, coverage <  0.01           -> SAMPLED_MISS + LOW_COVERAGE  => conclusion UNKNOWN
Implementation judge (must-fail arm):
  impl maps SAMPLED_MISS to PASS/UNCHANGED, or merges CHANGED/UNCHANGED  -> FAIL IMPL_MISS_AS_PASS
  every trial must report restored_identical=True after reset, else FAIL RESET_UNVERIFIED
"""
import hashlib, json, random, sys

def sample_digest(buf, win):
    return hashlib.sha256(len(buf).to_bytes(8, "big") + buf[:win] + buf[-win:]).hexdigest()

def classify(hit, coverage):
    if hit: return "CHANGED", []
    if coverage >= 1.0: return "UNCHANGED", []
    return "SAMPLED_MISS", (["LOW_COVERAGE"] if coverage < 0.01 else [])

def trials(size, win, n, offsets, seed):
    rng = random.Random(seed)
    base = bytes(rng.getrandbits(8) for _ in range(size))
    d0 = sample_digest(base, win)
    hits = 0; restored = True
    for off in offsets(rng, n):
        b = bytearray(base); b[off] ^= 0xFF
        hits += sample_digest(bytes(b), win) != d0
        b[off] ^= 0xFF
        restored &= sample_digest(bytes(b), win) == d0 and bytes(b) == base
    return hits, restored

def judge_impl(rows):
    bad = []
    for r in rows:
        want, _ = classify(r["hit"], r["coverage"])
        if want == "SAMPLED_MISS" and r["impl"] in ("PASS", "UNCHANGED"):
            bad.append((r["id"], "IMPL_MISS_AS_PASS"))
        elif not r.get("restored_identical", False):
            bad.append((r["id"], "RESET_UNVERIFIED"))
    return bad

def main():
    out = {"version": "sampled-coverage-v0.1"}
    S, W = 4 * 1024 * 1024, 4096
    cov = 2 * W / S
    h_all, ok1 = trials(S, W, 200, lambda r, n: [r.randrange(S) for _ in range(n)], 20261021)
    h_in, ok2 = trials(S, W, 100, lambda r, n: [r.randrange(W) for _ in range(50)] + [S - 1 - r.randrange(W) for _ in range(50)], 1)
    h_out, ok3 = trials(S, W, 100, lambda r, n: [W + r.randrange(S - 2 * W) for _ in range(n)], 2)
    out["4MB"] = {"coverage_pct": round(cov * 100, 3), "random_hits": f"{h_all}/200", "in_window": f"{h_in}/100",
                  "out_window": f"{h_out}/100", "restored_identical": ok1 and ok2 and ok3,
                  "hermes_reported": {"coverage_pct": 0.195, "random_hits": "1/200", "in_window": "100/100", "out_window": "0/100"}}
    out["256KB"] = {"coverage_pct": round(4096 / (256 * 1024) * 100, 4), "note": "single 4KB window; Hermes: fixed window 0/64, rotating 1/64, random 1/64"}
    rows = [
        {"id": "S1-miss-lowcov-impl-PASS", "hit": False, "coverage": cov, "impl": "PASS", "restored_identical": True, "expect": "IMPL_MISS_AS_PASS"},
        {"id": "S2-miss-lowcov-impl-UNCHANGED", "hit": False, "coverage": cov, "impl": "UNCHANGED", "restored_identical": True, "expect": "IMPL_MISS_AS_PASS"},
        {"id": "S3-miss-lowcov-impl-UNKNOWN", "hit": False, "coverage": cov, "impl": "UNKNOWN", "restored_identical": True, "expect": None},
        {"id": "S4-miss-3pct-impl-PASS", "hit": False, "coverage": 0.03, "impl": "PASS", "restored_identical": True, "expect": "IMPL_MISS_AS_PASS"},
        {"id": "S5-miss-fullhash-impl-UNCHANGED", "hit": False, "coverage": 1.0, "impl": "UNCHANGED", "restored_identical": True, "expect": None},
        {"id": "S6-hit-no-reset-proof", "hit": True, "coverage": cov, "impl": "CHANGED", "restored_identical": False, "expect": "RESET_UNVERIFIED"},
    ]
    got = dict(judge_impl(rows)); fails = 0
    for r in rows:
        ok = got.get(r["id"]) == r["expect"]; fails += not ok
        print(("ok " if ok else "BAD"), r["id"], "expect", r["expect"], "got", got.get(r["id"]))
    # counterexample: a "1% threshold only" judge (only flags misses under 1% coverage) lets S4 through
    naive = [r["id"] for r in rows if not r["hit"] and r["coverage"] < 0.01 and r["impl"] in ("PASS", "UNCHANGED")]
    print("threshold-only judge catches", naive, "-> misses S4 (3% coverage miss reported as PASS)")
    fails += "S4-miss-3pct-impl-PASS" in naive
    print(json.dumps(out, ensure_ascii=False))
    good = h_in == 100 and h_out == 0 and out["4MB"]["restored_identical"]
    print("RESULT", "PASS" if fails == 0 and good else "FAIL")
    sys.exit(0 if fails == 0 and good else 1)

if __name__ == "__main__":
    main()
