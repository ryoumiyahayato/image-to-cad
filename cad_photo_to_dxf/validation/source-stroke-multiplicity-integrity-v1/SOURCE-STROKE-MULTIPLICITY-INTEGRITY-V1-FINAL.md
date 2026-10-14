# Source Stroke Multiplicity Integrity V1

Status: `COMPLETE` (DEV-only foundational correction; production semantics unchanged)

## Outcome

The audit confirms both upstream destructive representation and pair-identity loss. The earliest bounded DEV loss is raw Hough normalization's longest-first per-orientation cap; 2-pixel duplicate normalization previously also retained only aggregate ancestor IDs. The latter now emits a non-destructive `source_stroke_group` containing every member geometry and endpoint pair. A new DEV-only source-stroke registry preserves confirmed or ambiguous instances, independent endpoints, local multiplicity profiles, non-destructive coincident/near-coincident groups, and optional derived consolidated hypotheses with member references.

No production reconstruction, rendering, span guard, axis guard, text/glyph guard, straight-validity gate, candidate membership, human label, or FinalStructure authority changed. Existing destructive production paths remain documented rather than rewritten.

## Required questions

- A. Multiple source stroke instances currently representable: **PARTIAL**. The new DEV registry represents them explicitly; legacy `LineSegment` consumers retain aggregate IDs but not per-ID geometry.
- B. Coincident strokes with different extents preserved: **PARTIAL** system-wide; **YES** in the new registry/group representation.
- C. Near-coincident strokes preserved: **PARTIAL** system-wide; **YES** in the new registry/group representation through 3 px when source/topology evidence identifies distinct instances.
- D. Independent endpoint sets preserved: **PARTIAL** system-wide; **YES** in the new representation.
- E. Destructive extent union present: **YES**.
- F. Longest-segment-wins present: **YES**.
- G. Contained valid strokes can be suppressed as duplicates/already-covered: **YES**.
- H. Derived consolidation can retain member provenance: **YES**.
- I. CASE15 is primarily **PAIR_IDENTITY_LOSS**. CASE16 is **BOTH** because alternative 792/793/794-axis detector hypotheses are split between the survivor and a filtered duplicate before identity-blind pair admission.
- J. Generic multiplicity-integrity mechanism justified: **YES**.

## Architectural separation

`SourceStrokeObservation` is detector/source evidence. `SourceStrokeInstance` is a confirmed instance or an explicit `MULTIPLICITY_AMBIGUOUS` hypothesis. `CoincidentStrokeGroup` is non-destructive and retains all member geometry/endpoints. `DerivedConsolidatedHypothesis` is optional and never replaces members. Rendering remains untouched. FinalStructure remains the sole reconstruction authority.

Aggregated historic source IDs are not resurrected into fake instances because their member geometries are already unavailable. Multiple observations collapse to one source instance only when callers supply a shared instance ID and independent equivalence evidence, which is how the thick-stroke control avoids hallucinating two semantic strokes.

## Bounded real-case audit

Ten existing DEV cases were used: CASE15/16, four prior hollow/piecewise/boundary-switch/near-collinear failures, two valid pair controls, and two valid single-stroke controls. No new source document, candidate, model, label, LOCKED_BLIND item, or H1/H2 material was opened. The structured audit records per-case evidence availability and does not infer absent raw multiplicity.

## Synthetic acceptance matrix

Cases A-L pass. Exact long/medium/short coincidence preserves three instances, six endpoints, and a local multiplicity profile of `1,2,3,2,1`. Nested exact coincidence preserves 12 rectangle edge instances and three coincident side identities. The 1/2/3 px controls preserve all trajectories. Thin hollow geometry keeps two source edges; a true thick stroke remains one source instance with two detector observations only after filled-band equivalence evidence. Partial/contained overlaps preserve endpoints, while damage fragments join only with independent continuity evidence.

## Pair identity

The DEV identity consumer admits only positive shared source identity, rejects disjoint confirmed identities, and returns non-admitted `MULTIPLICITY_AMBIGUOUS` for detector-only evidence. This is intentionally not wired into the frozen 147 eligibility path because those records do not carry independently proven shared identity; doing so would reject valid controls wholesale. CASE15/16 therefore remain in V1, and the next target is to freeze a geometry-only endpoint/topology identity evidence contract before any V2 membership decision.

## Frozen replay and governance

- Frozen pool replay: `PASS`; 147 records; V1 remains 122 eligible.
- Membership changed: `NO`; no V2 artifact was created.
- SOURCE_GAP_REVIEW_V1_2 remains `PAUSED`; current human evidence is unchanged.
- Production semantic delta: `NONE`.

## Structured artifacts

- `destructive-operation-audit.json`: `414c972d21140483df28162397b3ee7c6f2823fe1026edb33c439e0a5fed8e90`
- `pair-identity-evidence.json`: `8b26ffdcb3227d754e2d367a93708db6302ceb63ce6eeff65dcacee0d1cd887d`
- `real-case-multiplicity-audit.json`: `10ba9fb96c7dbd1d84cbcb2d348120f9e2c6784a39da7719307c718a72317672`
- `synthetic-multiplicity-results.json`: `6410f228f321b57aee877aef50a129e1f1f022ff7ae9d5c6104b31ebf5377529`

## Remaining locations

Production recentering, endpoint snapping, collinear extent union, duplicate suppression, thick-fragment consolidation, parallel centerline collapse, late-restoration coverage suppression, and the DEV 1200-item cap remain destructive. Replacing all of them would be a broader redesign. The foundational registry/grouping contract is now available for incremental adoption without creating a competing FinalStructure.

## Tests

Focused multiplicity tests cover exact/partial/contained coincidence, 1-3 px offsets, exact and near-coincident nested rectangles, hollow versus thick strokes, continuous and damaged single lines, pair identity, endpoints, provenance, non-destructive derived hypotheses, no destructive resurrection, quantized Hough member preservation, and absence of candidate-specific exceptions.

NEXT_TARGET: `FREEZE_GENERIC_ENDPOINT_TOPOLOGY_SOURCE_IDENTITY_EVIDENCE_FOR_DEV_PAIR_ADMISSION_BEFORE_V2_ELIGIBILITY`
