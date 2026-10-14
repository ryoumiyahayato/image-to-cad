# PERCEPTION-V2-B3A — Wave-1 prediction-blind page triage

## Outcome

Wave-1 is frozen at 18 pages: six representatives from each of the three admitted source families. The set is prediction-blind, source-diverse, and within the preferred 15–18 page range. Selection used document structure, engineering content, page object statistics, technical-illustration presence, drawing density, and intended annotation/glyph hard-negative coverage. No model, candidate miner, case labeler, or production path was run.

All three families are `PAGE_SET_FROZEN`. The set is ready for the separate B3B diagnostic candidate-proposal task, but B3B was not started.

## Fail-closed and source checks

- Worktree: `C:/Users/agcrf/Desktop/image-to-cad/instrumented-e03`
- Branch: `codex/source-support-lifecycle-instrumentation`
- Base HEAD: `c88badf4b821d34dbc0554196aee3a180fb78e13`
- Initial status: clean
- Production baseline: `3ad0ec4 fix: protect credible structure from artifact propagation`
- Source binary integrity: `PASS`; all three SHA-256 values exactly match the B2/B2A registries.
- Rights continuity: `PASS`; no newly visible page-level third-party ownership or reproduction notice affected a selected page.
- The admitted SF-V2-08 source is `19810002593.bits.pdf` with the expected hash. The separate `19810002593.pdf` is an unadmitted incomplete transport artifact and was not used.

## Triage evidence

Nine low-resolution contact sheets were created under:

`C:/Users/agcrf/Desktop/image-to-cad/instrumented-e03/local-artifacts/draftsman/perception-v2/wave1/B3A/`

There are two deterministic sparse-overview sheets and one page-triage review sheet per family. No full-resolution browsing cache was created and no preview was staged.

The selected page records and cluster definitions are in:

- `page-selection.json`
- `page-clusters.json`

## Frozen page set

### SF-V2-01 — FAA AC 43.13-1B with Change 1

Document: `FAA-AC-43.13-1B-CHANGE-1`; 646 source pages; mixed text/vector and raster technical illustrations.

| PDF page | Printed identifier | Page structure | Cluster | Selection basis |
|---:|---|---|---|---|
| 53 | Page 1-20; Par 1-46 | Wood spar splice repair plate, Figure 1-8 | `SF-V2-01-C01-WOOD-SPAR-SPLICE` | Section views, parallel spar/flange edges, dimensions, and callouts. |
| 126 | Page 3-10; Par 3-10 | Sandwich/core repair figures, Figure 3-10 | `SF-V2-01-C02-COMPOSITE-CORE-REPAIR` | Layered skin/core/cavity geometry and multiple repair variants. |
| 183 | Page 4-42; Par 4-62 | Metal crack/rib-intersection plate, Figure 4-21 | `SF-V2-01-C03-METAL-RIB-INTERSECTION-REPAIR` | Multiple connected repair geometries, leaders, and detail boundaries. |
| 204 | Page 4-64; Par 4-91 | Finger-patch repair plate, Figure 4-34 | `SF-V2-01-C04-METAL-FINGER-PATCH` | Repeated close parallel patch geometry and callout marks. |
| 214 | Page 4-74; Par 4-102 | Dimensioned tube splice with table, Figure 4-42 | `SF-V2-01-C05-TUBE-SPLICE-DIMENSIONED` | Tube/sleeve edges, dimension chains, table rules, and numeric glyphs. |
| 429 | Par 9-10; Page 9-9 | Multi-figure bolt/rod-end/torque-tube inspection page | `SF-V2-01-C06-BOLT-ROD-END-INSPECTION-FIGURES` | Small mechanical figures, localized edges, and leader/annotation density. |

### SF-V2-03 — FAA AC 150/5340-30J

Document: `FAA-AC-150-5340-30J`; 396 source pages; predominantly vector technical drawings.

| PDF page | Printed identifier | Page structure | Cluster | Selection basis |
|---:|---|---|---|---|
| 192 | A-6 | Normal runway with taxiway, Figure A-6 | `SF-V2-03-C01-RUNWAY-TAXIWAY-LAYOUT` | Broad placement/layout geometry, repeated fixtures, and legend-linked symbols. |
| 238 | A-52 | In-pavement RGL/stop-bar beam orientation, Figure A-52 | `SF-V2-03-C02-LIGHT-BEAM-ORIENTATION` | Angular beam lines, runway/taxiway geometry, and aligned annotations. |
| 250 | A-64 | Wireway installation details, Figure A-64 | `SF-V2-03-C03-WIREWAY-INSTALLATION` | Conduit/cable/pavement cross-sections and dimension/detail marks. |
| 273 | A-87 | Frangible MALS installation details, Figure A-87 | `SF-V2-03-C04-MALS-STRUCTURE-INSTALLATION` | Multi-view supports, foundations, conduit routing, and dense notes. |
| 341 | E-25; Figure E-24 | REIL power/control standard detail | `SF-V2-03-C05-REIL-POWER-CONTROL-DETAIL` | Profile views, L-867 base, foundation, conduit, cables, and callouts. |
| 386 | H-10; Figure H-9 | Legacy runway/stopway lighting layout | `SF-V2-03-C06-LEGACY-RUNWAY-STOPWAY` | Distinct legacy sheet format with repeated fixtures and layout rules. |

### SF-V2-08 — NASA-CR-161594

Document: `NASA-CR-161594`; 292 source pages; raster scan with OCR text layer and genuine legacy scan degradation.

| PDF page | Printed identifier | Page structure | Cluster | Selection basis |
|---:|---|---|---|---|
| 27 | Report 2-10; Figure 2-10 | Geoplatform truss/platform figure | `SF-V2-08-C01-GEOPLATFORM-TRUSS` | Isometric truss/joint geometry with weight and leader callouts. |
| 76 | Report 5-1; Figure 5-1 | Baseline low-thrust vehicle concept | `SF-V2-08-C02-BASELINE-VEHICLE-CONCEPT` | Vehicle/tank/engine profile, long edges, dimensions, and subsystem notes. |
| 85 | Report 5-10 | Torus-tank shell and structural assembly concepts | `SF-V2-08-C03-TORUS-TANK-STRUCTURAL-SHELL` | Shell, skin, frame, bulkhead, and assembly line evidence under scan degradation. |
| 91 | Report 5-16; Figures 5-13/5-14 | Tank acquisition/manifold and misalignment figures | `SF-V2-08-C04-TANK-ACQUISITION-MANIFOLD` | Circular/radial channels, connected ducts, and callout geometry. |
| 100 | Report 5-25; Figure 5-21 | LH2 tank screen/branch-channel detail | `SF-V2-08-C05-LH2-TANK-ACQUISITION` | Tank wall, perforated plate, screened channels, dimensions, and weak strokes. |
| 136 | Report 5-61; Figure 5-49 | Deployment/envelope geometry | `SF-V2-08-C06-DEPLOYMENT-ENVELOPE` | Long-axis envelope, pivot/axis lines, payload interfaces, and scan artifacts. |

No row above asserts a case-level semantic label. The expected evidence fields in `page-selection.json` describe only page-level visual situations for later work.

## Governance status

- Production semantic delta: `NONE`
- `detect_lines`, Hough/LSD, consolidation, ownership, fallback, artifact suppression, SourceSupportLifecycle, FinalStructure, CAD, and GUI: unchanged
- H1/H2: preserved reference holdouts; not inspected or rerun
- C1: eligible for later development adaptation; no change here
- Validation: `NO`
- Locked blind: `0 / 8`; no manual locked-blind inspection
- Model bake-off: `NO`
- Production integration: `NO`
- Source binaries: not tracked
- Rendered previews: not tracked

## Final status

PERCEPTION_V2_B3A:
COMPLETE

BASE CHECKPOINT:
c88badf4b821d34dbc0554196aee3a180fb78e13

DIAGNOSTIC CHECKPOINT:
RECORDED_IN_TASK_HANDOFF

PRODUCTION_SEMANTIC_DELTA:
NONE

SF-V2-01:
PAGE_SET_FROZEN

SF-V2-01 SOURCE PAGES:
646

SF-V2-01 SELECTED PAGES:
6

SF-V2-01 PAGE CLUSTERS:
6

SF-V2-03:
PAGE_SET_FROZEN

SF-V2-03 SOURCE PAGES:
396

SF-V2-03 SELECTED PAGES:
6

SF-V2-03 PAGE CLUSTERS:
6

SF-V2-08:
PAGE_SET_FROZEN

SF-V2-08 SOURCE PAGES:
292

SF-V2-08 SELECTED PAGES:
6

SF-V2-08 PAGE CLUSTERS:
6

TOTAL SOURCE PAGES:
1334

TOTAL SELECTED PAGES:
18

OVERVIEW CONTACT SHEETS:
9

SOURCE BINARY INTEGRITY:
PASS

RIGHTS STATUS:
PASS

REFERENCE BASELINE V1 RUN:
NO

MODEL RUN:
NO

CANDIDATE MINING:
NO

HUMAN LABELING:
NO

H1/H2 HOLDOUT CONTAMINATION:
NO

READY FOR PERCEPTION-V2-B3B:
YES

READY FOR MODEL BAKE-OFF:
NO

READY FOR PRODUCTION INTEGRATION:
NO

VALIDATION:
NO

LOCKED_BLIND:
0 / 8

GIT STATUS:
clean

STOP.
