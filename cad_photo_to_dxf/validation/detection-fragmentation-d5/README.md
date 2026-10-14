# Detection Fragmentation D5

## Scope and method

This is a diagnosis-only DEV study. It reuses captured binary/source/final artifacts and reruns only the current `detect_lines` configuration plus the existing thick-stroke consolidation and eligibility gates. It does not replay the full pipeline, change production semantics, run VALIDATION, or inspect LOCKED_BLIND.

The representative A2-SG-009 spans were visually qualified as real solid structural axes/rules with explicit junction or node endpoints. Auto-discovered dimension-text lookalikes were rejected. Continuity is not inferred from collinearity: every retained A2 span has complete conservative source-visible support and complete binary support within the established 4 px correspondence radius; the five new spans are also continuous within a 2 px binary corridor.

Coverage below is along the qualified target axis. Stage tuples are `fragment count / covered px / largest gap px`. Exact endpoints, widths, histories, Hough/LSD splits, and eligibility reasons are in `diagnostic-report.json`.

## Representative results

| Case | Target px | Detector emission | Post-consolidation | Eligible | Final | First fragmentation |
|---|---:|---:|---:|---:|---:|---|
| D2-001 (upper-left) | 518 | 12 / 456 / 21 | 12 / 456 / 21 | 12 / 456 / 21 | 0 / 518 gap | Hough/LSD segment emission |
| D5-UL-01 | 159 | 5 / 118 / 20 | 5 / 118 / 20 | 3 / 48 / 111 | 0 / 159 gap | Hough/LSD segment emission; eligibility is secondary |
| D5-UL-02 | 89 | 5 / 68 / 20 | 5 / 68 / 20 | 0 / 0 / 89 | 0 / 89 gap | Hough/LSD segment emission; all fragments then fail minimum length |
| D5-UR-01 | 113 | 3 / 89 / 24 | 3 / 89 / 24 | 3 / 89 / 24 | 0 / 113 gap | Hough/LSD segment emission |
| D5-UR-02 | 111 | 4 / 87 / 23 | 4 / 87 / 23 | 3 / 87 / 23 | 0 / 111 gap | Hough/LSD segment emission; one short fragment is secondary |
| D5-UR-03 | 132 | 5 / 111 / 21 | 5 / 111 / 21 | 4 / 111 / 21 | 0 / 132 gap | Hough/LSD segment emission; one short fragment is secondary |
| D2-005 control | 736 | 9 / 736 / 0 | 1 / 736 / 0 | 1 / 736 / 0 | 736 / 0 gap | None; consolidation succeeds |
| D2-006 control | 2641 | 13 / 2299 / 154 | 2 / 2438 / 132 | 2 / 2438 / 132 | 112 / 1312 gap | Hough/LSD segment emission; consolidation improves but does not repair |

The D2-006 source-visible mask is intentionally not used to requalify the case because the conservative damage classifier masks much of that thick stroke. Its prior high-confidence D2 qualification establishes continuous source and processing input; the binary trace here independently measures 2641/2641 with no gap. The D2 registry's original final metric is 107/2641 with a 1397 px gap; the 112/1312 figure above is the current 4 px raster correspondence measurement.

## Causal localization

The first insufficient handoff is `detect_lines` Hough/LSD segment emission to prepared raw lines.

- The uncapped prepared output has exactly the same target gaps as the production top-5,000 output. Global proposal truncation is not responsible.
- Segment preparation/recentering does not create or enlarge any qualified failure gap.
- A2-SG-009 thin fragments are outside the existing thick-only consolidation scope, so the post-consolidation gap is unchanged.
- D2-006 is the same first-loss family on A2-SG-022: the detector union has a 154 px gap. Thick consolidation reduces it to 132 px but cannot associate the remaining thin/unrecentered edge fragment with the consolidated thick group.
- Eligibility is adequate on D2-001 and all three upper-right cases. It causes additional loss only after detector fragmentation on D5-UL-01, D5-UL-02, and one D5-UR-02 fragment.
- Ownership/text filtering is destructive later, but it is not the first continuity loss in this case set.

Therefore:

- A2-SG-009 upper-left first fragmentation: `detect_lines` Hough/LSD segment emission.
- A2-SG-009 upper-right first fragmentation: `detect_lines` Hough/LSD segment emission.
- Cross-source repeat: **YES**, via D2-006 on A2-SG-022.
- Dominant exact mechanism: Hough/LSD emit endpoint-bounded fragments over source-qualified, binary-continuous axes; the union contains real uncovered intervals before recentering, capping, consolidation, or eligibility. The existing consolidation only repairs overlapping/nearby recentered thick fragments, leaving thin A2 fragments untouched and the mixed thick/thin D2-006 remainder unassociated.

## Next production change candidate (not implemented)

1. **Decision point:** the `detect_lines` → `consolidate_source_supported_thick_fragments` handoff in `reconstruct_straight_lines`.
2. **Failure mechanism:** detector primitives terminate at local edge/junction changes; their union leaves source-backed gaps. The current consolidation requires recentered thick fragments and a width-scaled proximity relation, so it cannot preserve thin A2 rules or associate D2-006's remaining unrecentered edge fragment.
3. **Source justification:** every positive case is a manually qualified same-structure span with explicit endpoints and continuous captured binary/source support in a narrow corridor; no candidate is justified by collinearity alone.
4. **Minimum semantic change:** add a pre-eligibility, source-connected axis-fragment consolidation path at this existing handoff. It may replace multiple fragments by their existing union extent only when a narrow, scale-normalized corridor contains one connected source-supported stroke path from the first endpoint to the last. It must not extend beyond observed fragment endpoints or synthesize support across blank pixels.
5. **Positive cases:** D2-001, D5-UL-01, D5-UL-02, D5-UR-01, D5-UR-02, D5-UR-03, and D2-006.
6. **Negative controls:** D2-R01 coordinate mismatch, D2-R02 damaged/ambiguous source, D2-R04 intentional openings, rejected dimension-text discovery spans, real double rules, and the existing no-source-gap consolidation test.
7. **D2-005 regression:** must remain one continuous 736 px eligible centerline with no duplicate CAD line or new noise.
8. **D2-006 expectation:** consolidate the qualified continuous stroke only if the connected thick-stroke band proves endpoint-to-endpoint support; otherwise preserve the current two fragments and report the rejected association. Never bridge the span merely because the fragments are parallel.
9. **Unsupported bridging/noise prevention:** require same connected foreground path inside a narrow scale-normalized corridor, bounded orientation/coordinate variation, endpoints confined to observed fragment extent, and zero traversal through unsupported blank space; retain later ownership/text filters and reject ambiguous branches/openings.
10. **Cross-source status:** proven for the first-loss mechanism (A2-SG-009 and A2-SG-022), but the thin and mixed thick/thin consolidation subcases must both remain explicit in implementation tests.

This is a candidate design only. Production implementation is not authorized by D5.
