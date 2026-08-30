# V2 raw-evidence layout

The V2 page contract accepts a repository-relative raw-evidence index with a
SHA-256 pin and an explicit record count. The current RC3 R3 index is
materialized in the ignored review package under
`local-artifacts/review/p1-v2-implementation/raw-evidence/`; it binds the 91
per-entity provenance hashes back to the immutable R3 provisional manifest.

DXF files, full per-restoration review records, and replay outputs remain
generated review artifacts. The separate committed `pages/*-base-evidence.json`
files contain only deterministic canonical base identity and replay attestations.
