# Raster internal endpoint topology evidence V1

Base checkpoint: `575d574c6b7b5a5f2e4d51f9f2bd7dba3b12c693`. This is a DEV evidence replay over nine frozen cases. The raster producer reads the preserved source render pixels at each internal competing detector endpoint. Candidate IDs, junction tokens, hypothesis counts, and human labels cannot affect its topology classification. They are carried only as context. No pair admission, production reconstruction, frozen guard, or eligible-set revision changed.

## Evidence rule

`RasterEndpointTopologyEvidence` persists incoming and forward axial support, support through the candidate endpoint, side flanks, angular branch support, estimated stroke width, nearby ridge distance, gap in stroke widths, local occupancy, local hypothesis counts, and reasons. The producer measures a local binary raster made from the source grayscale with a local Otsu threshold. Angular probes require visible attachment near the endpoint to avoid treating a parallel hollow edge as a branch.

A persistent incoming ridge and matching forward ridge give continuation; an attached side branch in that configuration gives crossing with continuation. A side branch with no forward ridge gives a corner, and two opposite branches give a T termination. A short aligned interruption followed by several pixels of resumed ridge is probable dropout. A clean incoming ridge that stops for multiple local widths without a nearby resumption can give a simple source endpoint. Weak or conflicting observations remain ambiguous. Detector endpoint position alone never supplies source support. Exact coincident physical multiplicity remains unobservable from one raster locus, even when its common ridge continues through an internal detector endpoint.

Only raster-backed competing terminations can become `INDEPENDENT_INTERNAL_SOURCE_ENDPOINT` in competition coverage. Earlier synthetic junction tokens remain diagnostic but no longer reject a whole extent. The new replay supplies raster evidence explicitly. The admission path is untouched.

## Bounded real replay

| Case | Local gap | Internal raster topology | Competition | Full extent single stroke | Whole pair |
| --- | --- | --- | --- | --- | --- |
| CASE15 | REJECTED | 1 corner, 5 ambiguous, 1 continuing | SUPPORTED | REJECTED | REJECTED |
| CASE16 | SUPPORTED | 1 stop, 1 dropout, 2 continuing, 7 ambiguous | SUPPORTED | REJECTED | REJECTED |
| Known valid control | SUPPORTED | 3 continuing | AMBIGUOUS | AMBIGUOUS | AMBIGUOUS |
| Nested/coincident extents | SUPPORTED | 2 ambiguous, 1 continuing | AMBIGUOUS | AMBIGUOUS | AMBIGUOUS |
| Hollow/double edge | SUPPORTED | 2 ambiguous | AMBIGUOUS | AMBIGUOUS | AMBIGUOUS |
| Piecewise offset | REJECTED | 1 crossing continuation, 1 continuing | AMBIGUOUS | AMBIGUOUS | REJECTED |
| Source-boundary switch | AMBIGUOUS | 2 continuing | AMBIGUOUS | AMBIGUOUS | AMBIGUOUS |
| Legitimate crossing | SUPPORTED | 3 ambiguous, 1 crossing continuation, 1 continuing | AMBIGUOUS | AMBIGUOUS | AMBIGUOUS |
| Legitimate damaged continuation | SUPPORTED | 1 crossing continuation, 1 continuing | AMBIGUOUS | AMBIGUOUS | AMBIGUOUS |

CASE16’s positive stop occurs at preserved raw endpoint `(794, 2059)`. Its incoming raster support is 1.0, forward support is 0, and the sampled empty distance is eleven local stroke widths. The adjacent candidate end at `(791, 2059)` remains ambiguous under the branch check; other ends without incoming support also remain ambiguous, and one aligned short interruption is labeled dropout. This is a generic pixel decision, not a case-specific exception. It supports rejection of the *full extent*, while the local gap remains supported. The human `INVALID_PRIMITIVE_FOR_GAP_REVIEW` label is unchanged and was not an input. The evidence claims a source-supported internal stop, not a counted number of physical source instances.

The known valid control, legitimate crossing, and damaged continuation received **zero false full-extent terminations**. Other invalid cases remain ambiguous when the raster does not establish an internal stop. No existing semantic or human judgment was silently promoted into raster evidence.

## Synthetic raster calibration

All **15/15** generated raster fixtures passed: continuous line; perpendicular and oblique crossings; T and corner terminations; separated collinear segments; dropout; noisy line; long/medium/short exact coincident extents; 1, 2, and 3 px near-coincident extents; nested rectangles with a shared side locus; hollow rectangle; and true thick stroke. The exact coincident fixture has a continuing common ridge and is not interpreted as proof of an invisible short physical instance. The near-coincident fixtures each have a visibly attached corner and recover a corner. Test expectations are used only after production, never passed into the producer. The hollow edge and thick stroke continue without false termination.

Focused verification: `33 passed` across the new topology and existing competition tests. The four compact JSON files in this directory and the matching runtime directory persist all profiles, case outcomes, synthetic outcomes, and competition integration. Current eligible set remains V1 with 122 entries. Next target: independent validation of raster endpoint precision over additional preapproved controls before any pair admission revision; no new case mining or model run is part of this checkpoint.
