# V2-LOCAL-D-FINAL

Bounded prediction-blind continuation proposal mining over the 16 Local-C candidate-eligible units. The three Local-C fidelity-blocked modelspace units were excluded before rendering and proposal generation.

## Method

D11 canonical horizontal/vertical fragment extraction and crop geometry were reused. PDF pages were rendered with bounded Poppler output. Eligible DWG modelspace views reused the three existing Local-A/Local-B DXF normalizations and were rendered deterministically for diagnostic evidence only. No source files, production code, geometry, ownership, fallback, or semantic labels were changed.

Raw proposals were capped at 30 per unit and 480 overall. Deterministic geometry filtering removed 96 proposals; 225 deduplication clusters produced 225 post-dedup records. The frozen set contains 24 candidates with one local and one context crop per candidate.

## Coverage

10 source families are represented in the frozen set. Qualified proposals were found for 10 of 10 eligible families. Selection used source-family, selected-unit, orientation, gap-length, context-density, vector/raster, and annotation-opportunity diversity; it did not use model scores.

Opportunity-context counts in the frozen records:

- dimension_extension_witness_line: 21
- dimension_chain: 21
- leader_marker: 19
- drawing_layout_rule: 24
- aligned_text_glyph_stroke: 22
- table_legend_revision_title_rule: 24

## Governance

Training permission is CONFIRMED for internal development/training/evaluation, while public redistribution remains NOT_AUTHORIZED. The set is unlabeled and ready for later prediction-blind human labeling only; it is not ready for model training until labeling, dataset freeze, and split/governance verification are complete.

No model run, reference baseline run, human semantic labeling, validation, candidate promotion, B3A modification, H1/H2 inspection, or production semantic change occurred.

USER_SUPPLIED_CANDIDATE_MINING_V2_LOCAL_D: COMPLETE

BASE CHECKPOINT: 1754e2a112531b914332f9181eb2ca616e8c443a

DIAGNOSTIC CHECKPOINT: 3cf332bd51df934d028baeb224518646c58010a9

AUTHORIZATION LINEAGE: PASS

PRODUCTION_SEMANTIC_DELTA: NONE

TOTAL DIAGNOSTIC LOCAL-C UNITS: 19
FIDELITY_BLOCKED UNITS: 3
CANDIDATE-ELIGIBLE INPUT UNITS: 16
ELIGIBLE SOURCE FAMILIES: 10
HIGH_VALUE ELIGIBLE FAMILIES: 9
UNITS ACTUALLY MINED: 16
SOURCE FAMILIES WITH QUALIFIED PROPOSALS: 10/10
RAW PROPOSALS: 480
FILTERED PROPOSALS: 96
DEDUP CLUSTERS: 225
FROZEN CANDIDATES: 24
LOCAL CROPS: 24
CONTEXT CROPS: 24
FAMILIES REPRESENTED IN FROZEN SET: 10
HIGH_VALUE FAMILIES REPRESENTED IN FROZEN SET: 9
DIMENSION_EXTENSION_WITNESS CONTEXT: 21
DIMENSION_CHAIN CONTEXT: 21
LEADER_MARKER CONTEXT: 19
DRAWING_LAYOUT_RULE CONTEXT: 24
ALIGNED_TEXT_GLYPH CONTEXT: 22
TABLE_LEGEND_REVISION_TITLE CONTEXT: 24
TRAINING_PERMISSION: CONFIRMED
PUBLIC_REDISTRIBUTION: NOT_AUTHORIZED
REFERENCE BASELINE V1 RUN: NO
MODEL RUN: NO
HUMAN SEMANTIC LABELING: NO
WAVE-1 B3A MODIFIED: NO
H1/H2 HOLDOUT CONTAMINATION: NO
READY FOR USER-SUPPLIED HUMAN LABELING: YES
READY FOR MODEL TRAINING: NO
READY FOR MODEL BAKE-OFF: NO
READY FOR PRODUCTION INTEGRATION: NO
VALIDATION: NO
LOCKED_BLIND: 0 / 8
SOURCE BINARIES GIT-TRACKED: NO
GIT STATUS: clean
STOP.
