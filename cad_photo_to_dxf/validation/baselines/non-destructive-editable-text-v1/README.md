# Non-destructive editable text regression baseline v1

- Contract: `non-destructive-editable-text-v1`
- Baseline source: `5f7846e00b41913c003f178558a110e6475c0ee0`
- Candidate audited: `80be85aba985e457bc7bff1e9ece49f50e7a46d2`
- Phase-12 commit anchor: `6f5f69329aabf0bd3a7eda84baf66eb1959bdcba`
- Phase-12 manifest blob anchor: `533ae15afcef24dd4444f9acc3d504bbd94d9c87`
- Recorded legacy tag: `baseline/phase12-final-acceptance-2026-07-30` (absent)
- Configurations: 12
- Unique pages: 10

The versioned files are compact summaries. They retain all contract hashes, counts, decisions, and integrity anchors but never store full entity vertices, text geometry arrays, or repeated A/B/C payloads. Complete raw page evidence is written only when `--raw-evidence-dir` is supplied and is indexed by `raw-evidence-manifest.json`.

The historical tag name is retained only as an identifier. Validation uses the immutable phase-12 commit and manifest blob. This baseline validates editable-text semantics and protected/non-text partitions. `text_geometry_hash` may change for P1B geometry; `full_structure_id` is recorded but is not an independent gate.
