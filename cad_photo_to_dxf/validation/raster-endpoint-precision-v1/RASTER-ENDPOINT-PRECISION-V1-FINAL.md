# Raster Endpoint Precision V1 — Final

**PRECISION_CHECK:** COVERAGE_INSUFFICIENT
**Base:** 11c202b1e75340a199f90bf26a5c5c2f156e0c2c on codex/source-support-lifecycle-instrumentation
**Additional controls:** 8 evaluated, selected and recorded before endpoint replay
**Reused development controls:** 7 non-anchor cases from the original nine-case baseline
**False termination/vetoes observed on selected DIRECT pair controls:** 0
**Valid pair controls remaining full-extent AMBIGUOUS:** 11
**CASE15 full extent:** REJECTED
**CASE16 full extent:** REJECTED
**SHADOW_REPLAY:** NOT_RUN

## Scope and evidence

The authoritative endpoint baseline reports nine real cases and 15 synthetic raster cases. It records CASE15 as local REJECTED / full-extent REJECTED, CASE16 as local SUPPORTED / full-extent REJECTED, the known-valid control as full-extent AMBIGUOUS, and the current V1 eligible set as 122. This check used the unchanged pixel classifier with the existing competition runner and cached raw observations/source renders.

Eight existing Batch-01 DIRECT controls were fixed at 2026-09-25T14:04:36Z before their new endpoint outputs were read. They span eight source families and do not overlap the nine producer-development cases. Each has (A) existing generic raster evidence across its reviewed A/B gap and (B) an existing human DIRECT pair label. B does not establish endpoint-level truth or complete primitive-extent continuity; A applies only to the reviewed gap and does not establish physical source-instance identity.

Coordinates are source-render pixels with identity transform from preserved raw geometry (x right, y down; no crop offset or rescale). Each endpoint observation and its associated raw observation, hypothesis, direction, candidate axis, and measured pixel profile are retained in bounded-control-results.json. Source-derived aligned views are in the Git-ignored local-artifacts area.

## Results

| Measure | Result |
| --- | ---: |
| Additional controls evaluated | 8 |
| Additional controls with internal competitor endpoints | 5 |
| Additional controls with no internal competitor endpoints | 3 |
| Additional endpoint observations | 16 |
| Strong termination endpoints in added controls | 0 |
| Reused development controls, excluding CASE15/16 | 7 |
| False full-extent rejections in reused positive development controls | 0 |
| Added DIRECT-pair controls with full extent AMBIGUOUS | 8 |
| Known-valid development control full extent | AMBIGUOUS |

The zero observed termination count is bounded evidence, not a generalization precision estimate. The added controls do not provide complete primitive-extent truth. Three of eight had no internal competing endpoint to assess. The other five supplied 16 endpoint observations, all AMBIGUOUS, continuing, or crossing-with-continuation.

## Decisive anchor evidence

| Anchor endpoint | Measured pixels and trajectory | Interpretation and limit |
| --- | --- | --- |
| CASE15 raw-hough-001164:start at (2122, 275) | Incoming support 1.0, forward support 0, corner strength 1.0, and a 9-width same-axis gap. The endpoint belongs to STROKE-HYPOTHESIS:raw-hough-001164, aligned with the candidate axis, but its detector line is on y=275 while the A/B axis is y=276. | The clean raster shows the y=275 run starting at x=2122 beside grid/diagonal linework. This establishes a corner on that neighboring track; it does not establish that the proposed A/B trajectory one pixel away terminates. Association across the one-pixel offset remains unresolved. The existing pair label is REJECTED and is not used as pixel proof. |
| CASE16 raw-hough-001078:end at (794, 2059) | Incoming support 1.0, forward support 0, same-axis gap 11 local widths, nearest axial ridge at 12 px. The evaluated line is x=794; the candidate A/B axis is also x=794. | At the endpoint pixel x=794 is white; x=796 has a continuing ridge 2 px away, while x=794 starts again immediately below. The producer's stop is supported on x=794, but the existing detector competitor list omits the nearby ridge. Whether x=796 is another stroke, a hollow/thick edge, or the same trajectory is unresolved. |

Visual inspection of these two aligned source crops is model-assisted, not independently frozen human ground truth. The images and complete measurements are persisted locally. Neither endpoint is treated as proof of hidden source identity.

## Coverage limit and replay decision

The selected controls partially exercise intersections, degraded drawing context, hatch/parallel geometry, and internal crossing attachments. They do not establish a continuous line through a filled node. The existing controls also lack endpoint-level truth for complete source extents, and the two anchor negatives leave near-parallel trajectory association unresolved. The known-valid control and the eight added controls remain full-extent AMBIGUOUS; this is not a successful positive identification.

For those reasons the bounded safety gate is COVERAGE_INSUFFICIENT, so no 147-record shadow replay was run. Proposed new vetoes among the current 122 and overlap with existing rejections are unavailable. This is a bounded evidence limitation, not a recommendation for an open-ended audit.

## Preserved invariants

- Pair admission unchanged.
- Current eligible set remains V1 / 122.
- No thresholds, source geometry, endpoints, human labels, production reconstruction, or FinalStructure changed.
- Production semantic delta: NONE.

## Verification

Focused tests: test_raster_endpoint_topology_v1.py and test_source_stroke_hypothesis_competition_v1.py — 33 passed. Result consistency checks passed: 10 bounded cases, 34 endpoint rows, frozen IDs disjoint from the development cases, and V1 remains 122.
