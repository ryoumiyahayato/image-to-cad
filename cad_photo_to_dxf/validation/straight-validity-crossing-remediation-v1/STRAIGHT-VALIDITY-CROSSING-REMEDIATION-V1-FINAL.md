# STRAIGHT VALIDITY CROSSING REMEDIATION V1 — FINAL

## Decision

The two confirmed false rejections share a generic crossing-contamination mechanism. Local multi-directional support at crossings inflated local tangent percentiles and, in one case, created a terminal offset-bin jump; in the other, a crossing-bounded support gap was counted as a sustained gap. The correction is confined to the straight-validity gate.

A crossing window is discounted only when the associated source ridge agrees before and after it. Sustained internal offset abnormality, incompatible pre/post trajectory, non-crossing gaps, and unsafe piecewise jumps remain active rejection evidence.

## Bounded comparison

| role | candidate | pre status | post status | result |
|---|---|---|---|---|
| FALSE_REJECTION | `FRESH1-ACE2F5BAEAFA699A90AC` | STRAIGHT_REJECTED | STRAIGHT_SUPPORTED | FALSE_REJECTION_CORRECTED |
| FALSE_REJECTION | `FRESH1-EAF5141532787D12AFE2` | STRAIGHT_REJECTED | STRAIGHT_UNCERTAIN | FALSE_REJECTION_CORRECTED |
| TRUE_REJECTION_CONTROL | `FRESH1-91191386DC95E23BEDAC` | STRAIGHT_REJECTED | STRAIGHT_REJECTED | TRUE_REJECTION_PRESERVED |
| TRUE_REJECTION_CONTROL | `FRESH1-316D125FE4861584BE02` | STRAIGHT_REJECTED | STRAIGHT_REJECTED | TRUE_REJECTION_PRESERVED |
| TRUE_REJECTION_CONTROL | `FRESH1-4966D4412392002C19C2` | STRAIGHT_REJECTED | STRAIGHT_REJECTED | TRUE_REJECTION_PRESERVED |
| VALID_CROSSING_CONTROL | `FRESH1-AB2943863A535D1044B9` | STRAIGHT_SUPPORTED | STRAIGHT_SUPPORTED | VALID_CROSSING_ACCEPTED |
| VALID_CROSSING_CONTROL | `FRESH1-4497ADEE7DB5D798A893` | STRAIGHT_SUPPORTED | STRAIGHT_SUPPORTED | VALID_CROSSING_ACCEPTED |
| VALID_CROSSING_CONTROL | `FRESH1-012B61A286913239D6AA` | STRAIGHT_SUPPORTED | STRAIGHT_SUPPORTED | VALID_CROSSING_ACCEPTED |

The detailed measurable crossing, offset, tangent, trajectory, support-identity, and window-state evidence is in `straight-validity-crossing-remediation-results.json`.

## Exact 18-case re-evaluation

The authoritative 18 were recovered exactly. After remediation, 16 remain straight-rejected: true 16, false 0, uncertain 0. The two prior false-rejection candidates are no longer straight-rejected; one is supported and one is uncertain at fragment level but aggregate-eligible.

## Frozen-147 replay

The exact frozen 147 was replayed deterministically: supported 83, uncertain 42, rejected 22; final eligible 122; newly ineligible 16.
Only the two known false-rejection IDs left the straight-rejected set: `FRESH1-ACE2F5BAEAFA699A90AC, FRESH1-EAF5141532787D12AFE2`. No new straight rejection was introduced.

## Current source-gap 16

| review index | candidate | human primary | post reason | audit verdict |
|---:|---|---|---|---|
| 10 | `FRESH1-FC529FBBABD1C203BAD8` | PATTERNED_VISIBLE_SEGMENTS | PIECEWISE_OFFSET_COLLAPSE | TRUE_REJECTION |
| 15 | `FRESH1-4966D4412392002C19C2` | VISIBLE_SEPARATE_SEGMENTS | INSUFFICIENT_STRAIGHT_TRAJECTORY_SUPPORT | TRUE_REJECTION |
| 16 | `FRESH1-91191386DC95E23BEDAC` |  | CURVED_CONTOUR_STRAIGHT_FIT | TRUE_REJECTION |

## Scope and safety

- No span, axis, text/glyph, source-continuity, endpoint, or admissibility guard was changed.
- No candidate-specific exception, source-family rule, coordinate rule, source acquisition, candidate mining, model run, review-package rebuild, VALIDATION, LOCKED_BLIND, or H1/H2 activity occurred.
- Frozen valid controls: old direct 1 / 1; old annotation 6 / 6; fresh direct 9 / 9; fresh direct annotation 6 / 6; bounded valid crossing 3 / 3.
- Representative true rejections preserved: 3 / 3.

## Recommendation

`STRAIGHT_VALIDITY_GATE_SHOULD_FREEZE: YES`
