# Source stroke hypothesis and competition coverage V1

Base checkpoint: `d405e77e7da4f8f4c871bb9abe12ff925ce36c59`. The requested worktree, branch, HEAD, and clean status matched before edits. This is DEV-only evidence production. FinalStructure, production consolidation, pair admission, the V1 eligible set of 122, and the paused source-gap review were not changed.

## Producer and interpretation

`app/source_stroke_competition_v1.py` creates `SourceStrokeHypothesis` records from all preserved raw detector observations intersecting the entire proposed corridor. Each record retains observation and group IDs, actual intervals and endpoints, lateral trajectory, provenance, and ambiguity. It reuses `SourceStrokeObservation`, `SourceStrokeRegistry`, and `CoincidentStrokeGroup`; grouping retains every member. A shared explicit filled-band, ridge-duplicate, continuity, or preserved-instance evidence token can group observations into one hypothesis. Equal geometry, proximity, angle, and overlap alone cannot. Every hypothesis remains unconfirmed as a physical instance.

`SourceStrokeCompetitionCoverage` records contained and partial overlaps, competing endpoints, near-coincident trajectories, gap intervals, source-boundary changes, orthogonal-contact diagnostics, and a piecewise hypothesis-count profile across the full proposed span. Counts describe retained detector hypotheses, not proven physical stroke counts. Internal competitor endpoints backed by independent junction evidence can reject a single-stroke interpretation. Uncorroborated raw overlap remains ambiguous. Crossings alone do not supply stroke identity. The raw corridor is complete for the selected unit files, while physical identity remains unresolved.

The bounded runner reads the existing frozen pair records and matching ignored raw-primitive audits. It reuses frozen local endpoint evaluation, raw member span integrity, and the current axis, span, straight-validity, and text/glyph gate statuses as read-only snapshots. Orthogonal raw endpoint contacts are reported as diagnostics and do not automatically become identity evidence. No raw geometry, candidate, gate threshold, or semantic label is changed.

## Bounded real audit

Nine existing cases were replayed; the cap was 12. In the table, `A` means `AMBIGUOUS`, `S` means `SUPPORTED`, and `R` means `REJECTED`. Competition `A` means raw competitors are present without enough independent evidence to confirm distinct physical strokes. All nine multiplicity statuses are `MULTIPLICITY_AMBIGUOUS`.

| Case | Local endpoint | Full-extent single stroke | Competition | Whole pair | Raw observations / competitors |
| --- | --- | --- | --- | --- | ---: |
| CASE15 | R | A | A | R | 6 / 4 |
| CASE16 | S | A | A | A | 12 / 10 |
| Known valid control | S | A | A | A | 4 / 2 |
| Nested/coincident extents | S | A | A | A | 4 / 2 |
| Hollow/double edge | S | A | A | A | 4 / 2 |
| Piecewise offset | R | A | A | R | 3 / 1 |
| Source-boundary switch | A | A | A | A | 3 / 1 |
| Legitimate crossing | S | A | A | A | 5 / 3 |
| Legitimate damaged continuation | S | A | A | A | 3 / 1 |

CASE15's whole-pair rejection comes from the existing local topology result; its full-extent raw competitors alone do not prove distinct physical instances. CASE16 remains locally supported only for gap-endpoint compatibility. The full proposed 1969–2108 span has ten competing raw observations, four contained extents, six partial overlaps, nine near-coincident competitors, and internal competing starts and ends. Its hypothesis-count profile changes across the span, with counts from two to seven. Four orthogonal raw endpoint contacts occur at the ends of a much longer observation, outside the proposed pair; they do not independently validate the internal terminations. These observations explain why a single-stroke interpretation is unsafe to confirm, but they do not prove the human-invalid whole primitive. The authoritative human `INVALID_PRIMITIVE_FOR_GAP_REVIEW` observation remains separate; the generic full-extent result is `AMBIGUOUS`.

The known-valid pair, legitimate crossing, and legitimate damaged continuation controls received no full-extent rejection. False full-extent rejections: **0**. No real pair received confirmed physical-instance IDs. The real audit therefore establishes conservative coverage and a recoverability limit, not reliable production rejection for every invalid primitive.

## Synthetic acceptance

All **12/12** focused cases passed: isolated line; one thick filled-band stroke with three detector observations; exact distinct extents; exact long/medium/short with profile `1→2→3→2→1`; 1, 2, and 3 px offset versions; nested rectangles with exact and near-coincident sides; hollow rectangle edges; damaged single stroke; and a legitimate crossing. Exact equal-geometry observations without positive equivalence remain separate ambiguous hypotheses. Explicit independently backed internal endpoints support a generic rejection, while true thick-stroke equivalence retains one hypothesis with all original members. The synthetic junction/equivalence tokens are supplied evidence in the test fixtures; they are not claimed to have been recovered from a raster.

Focused verification: `16 passed` in `tests/test_source_stroke_hypothesis_competition_v1.py`; the runner generated the four required JSON artifacts in both requested locations. The only pytest warning was inability to write its optional cache. No broad suite, model run, new candidate mining, source-gap package, validation, or locked blind inspection occurred.

## Next target

Calibrate independent internal endpoint evidence from preserved source raster topology and orthogonal attachment structure against the same frozen valid controls, then decide whether any full-extent rejection rule is reliable enough for a later admission revision. Keep pair admission unchanged until that evidence is established.
