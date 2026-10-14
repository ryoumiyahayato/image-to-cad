# Structural stroke label expansion D13A

Twelve existing, previously unreviewed D11 review pairs were inspected. The
selection used source-group coverage only. No encoder, model score, prediction,
PDF, page rerender, proposal regeneration, VALIDATION data, or LOCKED_BLIND data
was inspected. Review stopped early because all fillable source-group coverage
gaps were resolved.

## Updated human-label matrix

| SOURCE_GROUP | STRUCTURAL_CONTINUATION | ANNOTATION_OR_GLYPH | AMBIGUOUS | INVALID_FOR_TASK |
|---|---:|---:|---:|---:|
| G0R2-15EE2398726E8037 | 1 | 2 | 0 | 0 |
| G0R2-3B970FD759C6026F | 2 | 2 | 0 | 0 |
| G0R2-4A34D1B8D93B1B06 | 3 | 1 | 0 | 0 |
| G0R2-6C9464FA73A2A027 | 6 | 1 | 0 | 1 |
| G0R2-7E30C7F445081F40 | 2 | 1 | 0 | 0 |
| G0R2-B441E5911528F402 | 0 | 0 | 1 | 6 |
| G0R2-C2D095E069663C17 | 4 | 3 | 0 | 0 |
| **Total** | **18** | **10** | **1** | **7** |

The matrix records all confident semantic labels. Independence is tracked
separately: four new structural cases and two new hard negatives are independent;
two otherwise valid structural labels are excluded from independent-case counts
as repeated-pattern near-duplicates.

## Coverage decision

- `G0R2-6C9464FA73A2A027`: hard-negative gap filled by a drawing-layout/table-boundary case.
- `G0R2-B441E5911528F402`: one candidate from each of its four stored pages was sampled; all were embedded-figure borders and invalid for this task, so no clear supervised label was found.
- `G0R2-C2D095E069663C17`: gained independent cases from both supervised classes.
- Six source groups now have structural cases, six have hard negatives, and six have both.
- Further existing D11 labeling is not needed before the D13B stability retest.

Production semantic delta: none.

VALIDATION: no.

LOCKED_BLIND: 0 / 8.
