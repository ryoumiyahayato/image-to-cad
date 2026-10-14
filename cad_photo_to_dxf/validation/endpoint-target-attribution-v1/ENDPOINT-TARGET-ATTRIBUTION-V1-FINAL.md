# Endpoint-to-target attribution V1 — DEV report

**BASE_HEAD:** 74ba5c97687321df5ae4d0212e47136565985764
**RESULTING_HEAD:** this commit; exact SHA is reported with the final handoff
**SAMPLING_DIRECTION_DEFECT:** NO

The producer's source-to-crop transform is identity in source pixels. The decisive samples use the raw segment direction into the evaluated endpoint and its negation outward; the trace records the actual rounded pixels and the bounded crop transform. CASE16's reported 12 px nearest axial ridge is longitudinal along that outward ray, while the x=796 support is a separate 2 px lateral offset. The two measurements are not inconsistent.

## Attribution result

| Pair | Raw event | Target relation | Qualified veto | Full-extent result |
| --- | --- | --- | --- | --- |
| CASE15 | SOURCE_CORNER_TERMINATION | TARGET_RELATION_UNRESOLVED | 0 | REJECTED |
| CASE16 | SOURCE_ENDPOINT_TERMINATION | SAME_TRACK_SUPPORTED | 0 | AMBIGUOUS |
| KNOWN_VALID_CONTROL | NONE | NOT_APPLICABLE | 0 | AMBIGUOUS |

CASE15's corner event remains measured but is not target-attributed; its final rejection is preserved from the independently rejected local result. CASE16's endpoint event is retained, but no full-extent veto is qualified because the competing detector endpoint does not itself contradict the target span and the local raster contains a continuing lateral support band. The valid control remains AMBIGUOUS.

## Verification

- Event observation, target relationship, and contradiction qualification are separate fields in the trace.
- Preserved detector records were read; local raster support bands were inspected only inside bounded endpoint patches; no candidate mining, ridge jumping, or centerline averaging was performed.
- Focused regression tests: 46 passed.
- Unresolved attribution count in the three-pair trace: 2.

**SHADOW_REPLAY:** REPLAYED once over frozen-147; diagnostic only.
Attribution-qualified proposed vetoes: 1; negatives withheld for unresolved attribution: 14; proposed changes among eligible V1/122: 1.

PAIR_ADMISSION_CHANGED: NO
CURRENT_ELIGIBLE_SET: V1 / 122 unchanged
PRODUCTION_SEMANTIC_DELTA: NONE

The result does not establish endpoint precision merely because the two human-invalid anchors remain rejected.
