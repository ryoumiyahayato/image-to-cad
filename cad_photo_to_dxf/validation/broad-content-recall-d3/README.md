# BROAD-CONTENT-RECALL-D3

This diagnostic freezes a source-coordinate region-level recall census for DEV
source group `A2-SG-009`. It does not alter production reconstruction semantics.

The four plan regions are registered in `region-registry.json`. Regions A and B
are the failing upper-page cases; regions C and D are same-source lower-page
success controls. The exporter consumes the previously captured production
bundle and VQA final output, maps every diagnostic layer into the same source
coordinate system, and writes runtime artifacts below the ignored
`local-artifacts/draftsman/broad-content-recall-d3/` root.

The source-visible baseline is deliberately conservative: binary-supported
drawing pixels are retained after broad physical-damage regions and broad blobs
are excluded. FinalStructure is never used to define source truth. Consequently,
the census can localize loss after binary evidence, but does not quantify source
content already lost before or during binarization. Coverage values are spatial
diagnostics, not semantic-accuracy claims.

The census finds that upper-page final retention is 6.13%, versus 99.16% in the
lower controls. Upper raw coverage is incomplete, 28,576 source-supported pixels
are seen and later deleted, and only 7,057 pixels are fallback-rescued. The lower
controls instead depend on fallback for 160,282 pixels. This supports two broad
failure families: `FALLBACK_COVERAGE_GAP` and `OWNERSHIP_OVER_SUPPRESSION`.

Three DEV sanity reruns reproduce their frozen FinalStructure IDs and entity
counts exactly. LOCKED_BLIND was neither run nor inspected, and VALIDATION was
not used.
