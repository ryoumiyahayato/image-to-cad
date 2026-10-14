# User-Supplied Source Admission V2 Local-B

## Scope and governance

- Task: `USER-SUPPLIED-SOURCE-ADMISSION-V2-LOCAL-B`
- Worktree: `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03`
- Base checkpoint: `db74a722b711f42f0d90b942d5b5c3530e146fbd`
- Source directory: `C:\Users\agcrf\Desktop\新建文件夹`
- Source origin: `USER_SUPPLIED_LOCAL`
- Local analysis permission: `YES`
- Public domain: `NOT_ASSUMED`
- Public redistribution: `NOT_AUTHORIZED`
- Training permission: `TRAINING_PERMISSION_NOT_CONFIRMED`
- Source directory remained read-only. No source file was renamed, moved, overwritten, deleted, modified, uploaded, redistributed, or Git-added.

The Local-A inventory, duplicate hashes, and three-sample DWG feasibility evidence were reused as authoritative inputs. The four tracked outputs in this directory are compact family/admission metadata; they do not duplicate the 198-file inventory.

## Admission result

The collection supports 14 coherent source families. Four are administrative, schedule, or addendum families and are retained in the registry but excluded from the representative engineering pool. Ten families are frozen for later DEV page triage, with 16 representative documents.

The three large CAD trees are not split by discipline: the repeated project/package, directory, title/revision, and generation evidence indicates one family each for Haiyang 2022, HUIHONG 2019, and the 2020 as-built installation package. The 76 stamped XDF PDFs are likewise one review-package family. Root PDFs were grouped only where a shared project title or package role was visible:

| Family | Membership | Discipline | V2 value | Representative |
|---|---|---|---|---|
| F01 Haiyang 2021–2022 | 14 root DWGs covering workshop, warehouse, gatehouse, HVAC, electrical, plumbing, structural | MULTIDISCIPLINE | HIGH_VALUE | Yes |
| F02 HUIHONG 2019 | `b34518.../` tree: 50 DWG, 3 JPG, 11 other/sidecar files | MULTIDISCIPLINE | HIGH_VALUE | Yes |
| F03 As-built installation 2020 | 29 DWG plus 2 sidecars under the as-built tree | MULTIDISCIPLINE | HIGH_VALUE | Yes |
| F04 XDF stamped review package | 76 PDFs under one named fire-renovation review tree | MULTIDISCIPLINE | HIGH_VALUE | Yes |
| F05 `dennkisetubi.pdf` | One Japanese electrical plan PDF | ELECTRICAL_INSTALLATION | HIGH_VALUE | Yes |
| F06 Ontake visitor center | `20210416zumen.pdf` + `2026dennkisetsubi.pdf`; same visible project title, different sheet roles | ELECTRICAL_INSTALLATION | HIGH_VALUE | Yes |
| F07 Seya cultural center | `32581.pdf` + `0026_20260601.pdf`; same visible electrical-drawing title, different exports/page sets | ELECTRICAL_INSTALLATION | HIGH_VALUE | Yes |
| F08 Yangzijiang warehouse | One named comprehensive-warehouse electrical PDF | ELECTRICAL_INSTALLATION | HIGH_VALUE | Yes |
| F09 Jiulong street-house | One named fire/electrical modification PDF | ELECTRICAL_INSTALLATION | HIGH_VALUE | Yes |
| F10 Environmental bureau | One raster engineering-document PDF | UNKNOWN | USEFUL | Yes |
| F11 FEMS Engine House No. 14 | One English government addendum with a drawing revision list | MULTIDISCIPLINE | LOW_VALUE | No |
| F12 Jichuan pharma | One construction schedule/Gantt PDF | OTHER_ENGINEERING | LOW_VALUE | No |
| F13 Sakado school demolition | Two meeting/explanatory PDFs for one project | OTHER_ENGINEERING | LOW_VALUE | No |
| F14 52725 | One municipal building-committee agenda | UNKNOWN | LOW_VALUE | No |

Full family membership, evidence axes, and family-level opportunity tags are in `source-family-registry.json`.

Meaningful independence axes supported by the collection are project/package provenance, discipline spread, CAD/PDF generation workflow, revision/review stage, language/typography, title-block/layout convention, and scan/degradation lineage. Author/organization is left `UNKNOWN` unless visible in a title block or document metadata; local possession is not treated as ownership.

## DWG/PDF cross-format identity

No confirmed or likely DWG/PDF cross-format pairs were found. There were no exact DWG/PDF filename-stem matches. The two `dennkisetubi`-named PDFs were bounded-rendered and are different projects/sheets, not one DWG/PDF drawing. The two same-project PDF groups have no DWG counterpart with matching title, number, or revision evidence. Details and negative evidence are in `cross-format-pairs.json`.

Where a future pair is established, the DWG should be the vector-origin authority and the PDF may be retained as a plot/scan representation. No such pair is counted here, so no PDF is labeled `PAIRED_RENDERED_REPRESENTATION`.

## Duplicate and revision accounting

- Exact duplicates: 3 SHA-256 groups, 6 participating files, 3 duplicate extras; all are inside the HUIHONG tree and are not counted as diversity.
- Likely near-duplicates: 2 groups. One is the XDF duplicated directory-sheet PDF whose bounded renders have identical SHA-256; the other is the HUIHONG underground-HVAC DWG/BAK recovery lineage.
- Revision groups: 7, covering HUIHONG t3/recovery naming, the as-built package, Haiyang review/date suffixes, XDF review-response suffixes, the Ontake alternate sheet set, and the Seya alternate PDF set.
- The `dennkisetubi`/`2026dennkisetsubi` lexical similarity is not a duplicate signal after visual inspection.

The exact and likely groups, plus the revision-group definitions, are in `duplicate-groups.json`. No source file was discarded.

## Inspection budget and evidence

- Files deeply inspected: 22 accounted for (17 newly inspected in Local-B plus 5 Local-A content samples reused without reinspection).
- New DWG conversions: 3, one each from Haiyang HVAC, HUIHONG HVAC, and as-built HVAC. All three converted successfully through the already demonstrated ODA -> DXF path and opened with ezdxf.
- New previews: 14 bounded first-page PDF renders. No full-package render, contact sheet, model run, candidate mining, or semantic case labeling occurred.
- New DWG observations included populated modelspace, entity counts, dimensions, leaders, text, layers, layouts, and proxy entities. No production DWG input path was added.

Observed representative evidence includes:

- Haiyang HVAC: AC1032, 1,502 modelspace entities, 25 dimensions, 558 text entities, 26 layers including HVAC/equipment layers.
- HUIHONG HVAC: AC1032, 34,296 modelspace entities, 480 dimensions, 26 leaders, 1,213 text-like entities, 63 layers.
- As-built HVAC: AC1032, 3,540 modelspace entities, 81 dimensions, 455 text entities, and five proxy entities.
- Japanese PDF families: clean plotted electrical plans/specifications with formal title blocks, legends, schedules, dimensions, and Japanese typography; alternate export/scan differences were preserved as family evidence.
- Chinese PDF families: formal title blocks, drawing directories, project numbers, discipline fields, signatures, revision fields, and dense engineering notes.
- The environmental-bureau PDF supplies raster/scan diversity; the four excluded families do not show meaningful drawing geometry in the inspected first pages.

## Representative freeze

The frozen 16-document pool is recorded in `representative-document-set.json`. It contains native DWGs for the three CAD-origin families, two documents for the XDF package, distinct plan/spec or alternate representations for the Ontake and Seya families, and one document each for the remaining selected PDF families. Duplicate copies and low-value administrative material are excluded.

The pool is an additional DEV source pool only. Wave-1 (`SF-V2-01`, `SF-V2-03`, `SF-V2-08`), B3A's 18-page frozen set, and H1/H2 holdouts were not modified or inspected. This task does not assign DEV/train/holdout roles beyond freezing the source-family pool.

## Required gates

- Production semantic delta: `NONE`.
- `detect_lines`, Hough/LSD behavior, consolidation, ownership, fallback, artifact suppression, SourceSupportLifecycle, FinalStructure, OCR, symbol handling, GUI production input, and CAD export semantics were not modified.
- Reference Baseline V1: `NO`.
- Model run: `NO`.
- Candidate mining: `NO`.
- Human case labeling: `NO`.
- H1/H2 holdout contamination: `NO`.
- Validation: `NO`.
- Locked blind: `0 / 8`.
- Ready for user-supplied page triage: `YES`.
- Ready for user-supplied candidate mining: `NO`.
- Ready for model bake-off: `NO`.
- Ready for production DWG input integration: `NO`.

USER_SUPPLIED_SOURCE_ADMISSION_V2_LOCAL_B:
COMPLETE

BASE CHECKPOINT:
db74a722b711f42f0d90b942d5b5c3530e146fbd

DIAGNOSTIC CHECKPOINT:
774d266f45036d4fe07e25251ed7b0f77be3dc99

PRODUCTION_SEMANTIC_DELTA:
NONE

USER SOURCE DIRECTORY:
C:\Users\agcrf\Desktop\新建文件夹

TOTAL SOURCE FILES:
198

DWG FILES:
93

PDF FILES:
89

EXACT DUPLICATE FILES:
6

EXACT DUPLICATE GROUPS:
3

LIKELY NEAR-DUPLICATE GROUPS:
2

CROSS-FORMAT DWG/PDF PAIRS:
0

REVISION GROUPS:
7

FILES DEEPLY INSPECTED:
22 (17 new in Local-B; 5 Local-A evidence files reused)

NEW DWG CONVERSIONS:
3

NEW PREVIEWS GENERATED:
14

PLAUSIBLE SOURCE FAMILIES:
14

HIGH-VALUE FAMILIES:
9

USEFUL FAMILIES:
1

LOW-VALUE / NOT-SUITABLE FAMILIES:
4

UNKNOWN FAMILIES:
0

MECHANICAL FAMILIES:
0

ELECTRICAL_INSTALLATION FAMILIES:
5

ELECTRICAL_SCHEMATIC FAMILIES:
0

ARCHITECTURAL FAMILIES:
0

CIVIL_SITE_PROFILE FAMILIES:
0

PID_PROCESS_INSTRUMENTATION FAMILIES:
0

STRUCTURAL FAMILIES:
0

OTHER / UNKNOWN DISCIPLINE FAMILIES:
4

MULTIDISCIPLINE FAMILIES:
5

REPRESENTATIVE FAMILIES FROZEN:
10

REPRESENTATIVE DOCUMENTS FROZEN:
16

TRAINING PERMISSION STATUS:
NOT_CONFIRMED

USER-SUPPLIED MATERIAL V2 VALUE:
HIGH

WAVE-1 B3A FREEZE MODIFIED:
NO

REFERENCE BASELINE V1 RUN:
NO

MODEL RUN:
NO

CANDIDATE MINING:
NO

HUMAN CASE LABELING:
NO

H1/H2 HOLDOUT CONTAMINATION:
NO

READY FOR USER-SUPPLIED PAGE TRIAGE:
YES

READY FOR USER-SUPPLIED CANDIDATE MINING:
NO

READY FOR MODEL BAKE-OFF:
NO

READY FOR PRODUCTION DWG INPUT INTEGRATION:
NO

VALIDATION:
NO

LOCKED_BLIND:
0 / 8

SOURCE FILES MODIFIED:
NO

SOURCE BINARIES GIT-TRACKED:
NO

GIT STATUS:
clean

STOP.
