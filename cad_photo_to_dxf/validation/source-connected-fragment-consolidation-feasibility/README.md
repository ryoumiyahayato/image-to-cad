# Source-connected fragment consolidation feasibility

## Result

`CANDIDATE_NOT_SAFE`

The counterfactual source-connected rule recovers all seven required positives, including D2-006 through an actually connected thick binary band. It does not provide a clean guard against the hardest dimension/text lookalikes. Four of five D5-rejected dimension spans pass every non-semantic condition needed to recover the positives. They therefore remain `AMBIGUOUS`, which fails the required negative-control criterion.

This is a diagnostic replay only. It changes no Hough/LSD threshold, detector threshold, consolidation behavior, eligibility, ownership/fallback, artifact suppression, or `FinalStructure` behavior. The measured positive envelope below is a separation probe, not a proposed production threshold.

## Positive cases

Coverage is reported as source/binary path coverage through the largest internal detector gap. The corridor is the minimum full width that connects the two observed inner endpoints in the captured binary. Consolidation remains confined to the union of observed fragment extents (`observed_extent_extension_px = 0` in every case). Exact measurements for every internal gap are in `diagnostic-report.json`.

| Case | Fragment inner endpoints | Gap px | Orientation delta | Transverse offset px | Source/binary coverage | Required corridor | Conflict | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| D2-001 | (1323.573, 865.625) → (1320.244, 886.871) | 21.246 | 0.645° | 3.959 | 1.000 / 1.000 | 17 px; half-width 6.026×scale | no parallel conflict; qualified structural nodes elsewhere in extent | MERGE |
| D5-UL-01 | (1404, 625) → (1406.574, 645.615) | 20.615 | 0.381° | 2.453 | 1.000 / 1.000 | 11 px; half-width 3.766×scale | no parallel conflict; qualified node/junction topology | MERGE |
| D5-UL-02 | (1474, 683) → (1474.043, 703.125) | 20.125 | 0.009° | 0.040 | 1.000 / 1.000 | 3 px; half-width 0.753×scale | no parallel conflict; qualified endpoint nodes | MERGE |
| D5-UR-01 | (2264.406, 1151.867) → (2288.105, 1151.253) | 23.699 | 0.433° | 1.860 | 1.000 / 1.000 | 15 px; half-width 5.273×scale | no parallel conflict; qualified circular nodes | MERGE |
| D5-UR-02 | (2325.650, 1080.304) → (2348.122, 1082.673) | 22.472 | 1.427° | 1.736 | 1.000 / 1.000 | 17 px; half-width 6.026×scale | no parallel conflict; qualified outer-wall junction | MERGE |
| D5-UR-03 | (2816.641, 726.873) → (2814, 748) | 21.127 | 0.553° | 2.822 | 1.000 / 1.000 | 17 px; half-width 6.026×scale | no parallel conflict; qualified circular node | MERGE |
| D2-006 | (5366.873, 1600.049) → (5498.124, 1581.315) | 131.251 | 0.095° | 18.484 | 1.000 / 1.000 | 1 px on thick binary band | no parallel conflict; source basis is prior high-confidence D2 qualification | MERGE |

D2-006 is not rescued by generic endpoint bridging: its captured binary contains an endpoint-to-endpoint connected foreground band, with no blank traversal. Its conservative source-visible mask is damage-confounded, so source identity remains based on the existing high-confidence D2 qualification; the source mask itself also connects the measured endpoints at a 15 px half-width.

## Negative controls

| Control | Measurement | Result | Rejection or ambiguity reason |
|---|---|---|---|
| D2-R01 | 114/371 supported at 4 px; 96 px unsupported run | REJECT | target mismatch; the coordinate does not follow the physical rule |
| D2-R02 | 79/801 supported at 4 px; 547 px unsupported run | REJECT | scan/tape damage makes continuity and endpoint identity ambiguous |
| D2-R04 | 500/651 supported at 4 px; 80 px unsupported run | REJECT | intentional openings and door geometry; not one continuous target |
| D5-TEXT-UL-01 | 33.871 px gap; 11 px corridor; topology off-corridor 0.278, branch columns 0.400 | AMBIGUOUS | dimension/glyph ink supplies a connected path inside the positive envelope |
| D5-TEXT-UL-02 | 22.486 px gap; 15 px corridor; topology off-corridor 0.176, branch columns 0.040 | AMBIGUOUS | dimension/glyph ink supplies a connected path inside the positive envelope |
| D5-TEXT-UL-03 | 23.714 px gap; 17 px corridor; topology off-corridor 0.179, branch columns 0.000 | AMBIGUOUS | dimension/glyph ink is indistinguishable from a low-branch structural continuation by this probe |
| D5-TEXT-UR-01 | 19.973 px gap; 15 px corridor; topology off-corridor 0.407, branch columns 0.364 | AMBIGUOUS | dimension/glyph ink supplies a connected path inside the positive envelope |
| D5-TEXT-UR-02 | 19.963 px gap; 15 px corridor | REJECT | transverse offset/width lies outside the envelope required by the positives |
| Existing no-gap-invention blank | 30 px gap; no connection through an 8 px half-width corridor | REJECT | would require unsupported blank-space traversal |
| Existing no-gap-invention double-rule control | gapped rule at x=70; distinct continuous parallel rule at x=105 | REJECT | blank traversal and conflicting parallel evidence |
| Existing scanned double-rule pair | independent rules at y=150 and y=158 | REJECT | two continuous parallel source components must remain distinct |

The focused controls passed: source-supported thick consolidation still produces one centerline, the blank-gap/parallel-rule fixture still returns three distinct lines, and the scanned double-rule fixture still preserves both rules (`3 passed`). D2-005 also remains one 736 px post-consolidation centerline with a zero-pixel gap and its existing consolidation history.

## Why the guard is not safe

To recover every positive, the observed data require up to 1.427° orientation delta, 1.477 fragment-width-normalized transverse offset, and 6.026 scale-normalized corridor half-width. These are observations, not proposed constants. Four dimension/text controls fall inside that required envelope.

No tested topology metric separates the classes:

| Diagnostic metric | Positives | Dimension/text controls |
|---|---:|---:|
| Corridor half-width / scale | 0.000–6.026 | 3.766–6.026 |
| Off-corridor ink fraction | 0.044–0.960 | 0.176–0.407 |
| Branch-column fraction | 0.000–1.000 | 0.000–0.400 |
| Maximum transverse ink | 12–25 px | 12–21 px |

The overlap is structural: genuine positives intentionally pass through circular nodes and junctions, while dimension chains contain inline circles, numerals, and short junction-like strokes. A semantic label can reject the known text controls, but no operational semantic guard exists at the detector-to-consolidation handoff tested here. Calling those cases `REJECT` based only on manual labels would hide the exact uncertainty this feasibility task is meant to expose.

Therefore the candidate cannot be implemented safely without a separately validated semantic/topological discriminator. The rule must not be weakened into a generic endpoint bridge.

FRAGMENT_CONSOLIDATION_FEASIBILITY:
FAIL

POSITIVE CASES ACCEPTED:
7 / 7

NEGATIVE CONTROLS REJECTED:
7 / 11

DIMENSION-TEXT FALSE MERGES:
0

DOUBLE-RULE FALSE MERGES:
0

UNSUPPORTED-BLANK FALSE MERGES:
0

D2-005:
unchanged

D2-006:
MERGE counterfactually through actual supported continuation; unsafe to generalize

CROSS_SOURCE_SUPPORT:
YES

SAFE GUARD FOUND:
NO

NEXT PRODUCTION CHANGE CANDIDATE:
NONE

READY_TO_IMPLEMENT:
NO

PRODUCTION_SEMANTIC_DELTA:
NONE

VALIDATION:
NO

LOCKED_BLIND:
0 / 8

GIT STATUS:
diagnostic changes only
