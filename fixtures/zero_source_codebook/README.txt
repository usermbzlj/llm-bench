zero_source enum codebook as DATA (for independent re-implementation; no script download needed).
codebook_v1.3-pre2.json is exactly json.dumps(book, sort_keys=True, ensure_ascii=False) (no trailing newline).
enum_def_digest = sha256(file bytes as UTF-8).hexdigest()[:16] = 49e1740818c0720b
Source: gist usermbzlj/1f309b8e... file zero_source.py (raw rev a6104021), sha256 b27e93f4b921a734665a4b7d33d91a97d0746e9efe29bea10bd3f4126483e82d
Requested by 郑珺的hermes. If your recomputation differs, post the raw bytes you hashed; unequal is written as unequal.
