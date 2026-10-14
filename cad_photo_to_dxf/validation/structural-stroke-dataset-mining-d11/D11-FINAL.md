# Structural stroke dataset mining D11 — final feasibility

## Scope and early stop

The conclusion below uses the 24 cases recorded in Batch 1. Batch 2 added zero
reviews because Batch 1 already supports a whole-`SOURCE_GROUP` split and
contains diverse hard negatives. No candidate mining, rendering, PDF inspection,
reconstruction, OCR, model training, VALIDATION access, or LOCKED_BLIND access
was performed in Batch 2.

## Per-source-group label matrix

| SOURCE_GROUP | STRUCTURAL_CONTINUATION | ANNOTATION_OR_GLYPH | AMBIGUOUS | INVALID_FOR_TASK | Hard-negative subtypes |
|---|---:|---:|---:|---:|---|
| G0R2-15EE2398726E8037 | 1 | 2 | 0 | 0 | revision-table rule; title-block rule |
| G0R2-3B970FD759C6026F | 2 | 2 | 0 | 0 | aligned text glyphs; dimension chain |
| G0R2-4A34D1B8D93B1B06 | 3 | 1 | 0 | 0 | legend-table rule |
| G0R2-6C9464FA73A2A027 | 3 | 0 | 0 | 1 | none observed |
| G0R2-7E30C7F445081F40 | 2 | 1 | 0 | 0 | revision-table rule |
| G0R2-B441E5911528F402 | 0 | 0 | 1 | 2 | none qualified |
| G0R2-C2D095E069663C17 | 1 | 2 | 0 | 0 | drawing-layout rule; title-block rule |
| **Total** | **12** | **8** | **1** | **3** | **6 distinct subtypes** |

Six source groups contain structural positives, five contain hard negatives,
and five contain both. The negative evidence is not a repeated single pattern:
it spans aligned text glyphs, a dimension chain, drawing-layout rules,
legend-table rules, revision-table rules, and title-block rules.

## Whole-source-group split simulation

One leakage-free exploratory split is:

- Train: `G0R2-3B970FD759C6026F`, `G0R2-4A34D1B8D93B1B06`,
  `G0R2-6C9464FA73A2A027`, `G0R2-7E30C7F445081F40`
- Held out: `G0R2-15EE2398726E8037`, `G0R2-C2D095E069663C17`
- Ambiguity-only diagnostic reserve: `G0R2-B441E5911528F402`

The train side has 10 structural positives and 4 hard negatives. The held-out
side has 2 structural positives and 4 hard negatives. No source group appears
on both sides. The diagnostic reserve preserves the degraded historical case
without forcing its ambiguous evidence into either supervised class.

## Decision

`SUFFICIENT_FOR_SMALL_PROTOTYPE`.

The evidence supports a small advisory-only prototype because complete-source
holdout is possible and both classes occur in multiple independent source
groups with several genuinely different hard-negative mechanisms. This is a
technical feasibility decision, not permission for commercial training and not
evidence of robust performance on degraded historical drawings. No qualified
leader/marker negative was observed in Batch 1; that is a useful future label
target but does not block the narrowly scoped exploratory prototype.

New PDF acquisition is not justified at this point. Existing DEV proposals can
be revisited later if broader subtype coverage is desired. Source-evidence
provenance and data-rights provenance remain separate, and the restored sources'
rights status must be reviewed before any use beyond this diagnostic study.

Production semantic delta: none.

VALIDATION: no.

LOCKED_BLIND: 0 / 8.
