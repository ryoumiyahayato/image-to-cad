# V2 raw-evidence layout

The V2 page contract accepts a repository-relative raw-evidence index with a
SHA-256 pin and an explicit record count. The current RC3 R3 index is
materialized in the ignored review package under
`local-artifacts/review/p1-v2-implementation/raw-evidence/`; it binds the 91
per-entity provenance hashes back to the immutable R3 provisional manifest.

The committed V2 surface intentionally contains only this layout contract,
schema, validator, and tests. DXF files, full per-entity review records, and
replay outputs remain generated review artifacts rather than baseline source.
