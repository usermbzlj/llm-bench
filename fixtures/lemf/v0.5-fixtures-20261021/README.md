# LEMF fixtures — v0.5-fixtures-20261021 (frozen)

Intraday full-day turnover extrapolation contract, analyze_only. 26 rows, judged on the contract, not on whether the number was right.

- Columns 1-4 on every row: `case_id / expect / must_catch / probe_id`. `must_catch` is true iff `expect != PASS`.
- Merge rule: rows are distinct cases only when they differ in probe, expectation or inputs; `validate.py` fails on any pair with the same `probe_id`, same `expect` and identical inputs.
- Frozen: no field changes under this tag. The next change ships as a new tag, so a signed digest of this version stays a usable anchor.
- Run: `python3 validate.py` (stdlib only). Expected: `RESULT PASS`, `fixtures_sha256 fdf9fc38346dc8797b931847886a429103b45298778cbb49506e7af8b7a2c3a2`.
- Counterexample built in: an implementation that abstains on every row scores 0 pass / 26 abstain here, while the v0.3 judge would have scored it 26/26 PASS.

Spec credits: 荷马史诗 (contract, real 10/21 path), 戴笠 (NUMBER_UNSOURCED), 贺水仙的大龙虾 (thin-history backoff), 木木 (four-column convention + version pinning).
Previous gist: ddecbfd7f83ba9d92d5093cc5b195e52 (same 26 cases, without the four leading columns).
