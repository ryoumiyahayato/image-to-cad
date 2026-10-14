# User-Supplied DWG/PDF Ingest V2 Local-A

## Scope and governance

- Task: `USER-SUPPLIED-DWG-PDF-INGEST-V2-LOCAL-A`
- Worktree: `C:\Users\agcrf\Desktop\image-to-cad\instrumented-e03`
- Base checkpoint: `f00e8c32a75a79b9d236f2674459190cecf50733`
- Source origin: `USER_SUPPLIED_LOCAL`
- Authorized this task: `LOCAL INGEST / CONVERSION / FEASIBILITY TESTING`
- Public domain: `NOT_ASSUMED`
- Redistribution: `NOT_AUTHORIZED`
- Public release: `NO`
- Source role: `DEV_CANDIDATE_SOURCE_MATERIAL`; not validation and not locked blind

The source directory was inspected read-only. No source file was renamed, moved, overwritten, deleted, modified, uploaded, redistributed, or Git-added. Wave-1/B3A validation artifacts were not changed.

## Inventory

The source inventory is recorded in `source-inventory.json`, including relative path, extension, stem, byte size, UTC modification time, SHA-256, duplicate groups, and selected-sample metadata.

- Total files: 198
- DWG: 93
- DXF: 0
- PDF: 89
- Raster (PNG/JPG/JPEG/TIFF): 3 (all JPG)
- Other: 13 (`.bak`, `.dwl`, `.dwl2`, `.emjsx`, `.tmp`, `.xlsx`)
- Exact duplicate hash groups: 3
- Exact duplicate file participants: 6 (3 extra duplicate copies)
- Distinct source-family estimate: `UNKNOWN`; metadata shows many likely families across four top-level buckets, but does not prove independent provenance.

## Current implementation findings

Before this task’s helper was added:

- Direct production DWG input: `NO`. `cad_photo_to_dxf/app/image_loader.py` accepts `.jpg`, `.jpeg`, `.png`, and `.pdf`; the active picker in `gui_state_guard.py:MainWindow.import_image` accepts `.jpg`, `.jpeg`, `.png`, and `.pdf` only.
- Existing DWG→DXF: `NO`.
- Existing DXF→DWG: `YES`, via `dwg_converter.py:convert_dxf_to_dwg` and the existing `_run_converter` ODA integration.
- Existing DWG→PDF or DWG raster-preview path: `NO`.
- Existing DXF vector rendering: `YES`, via `debug_bundle.py:_render_dxf_svg` using ezdxf `Frontend`, `RenderContext`, and SVG backend; it renders modelspace diagnostically.
- `ProductionProcessingService.process_page` consumes a raster `numpy.ndarray` and builds the existing `FinalStructure`; no direct DXF/DWG input or semantic change was introduced.

Added in this task:

- `dwg_converter.py:convert_dwg_to_dxf`, reusing the existing ODA discovery/command path with explicit DXF output, destination suffix normalization, source protection, timeout handling, captured failure output, and non-zero-output validation.
- Bounded unit tests in `tests/test_dwg_converter_selection.py` for source extension rejection, destination normalization/source preservation, unavailable converter, output failure details, version mapping, and DXF command selection.

## ODA and selected sample test

ODA was found through the current worktree discovery logic:

`C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe`

No software was installed and no system installation was modified.

Three DWGs were selected by differing source trees, disciplines, names, and sizes; two PDFs were selected by differing source trees and engineering-document metadata. The hard limit of 3 DWGs and 2 PDFs was respected.

All three DWG→DXF attempts succeeded with ODA exit status 0. All three generated DXFs were non-zero and opened successfully with ezdxf; modelspace enumeration and layout enumeration succeeded for all three. Two normalized samples received bounded 2400×1800 SVG diagnostic previews through the existing ezdxf vector frontend.

The detailed per-sample structural results, hashes, entity counts, headers, extents, layout state, font references, proxy/custom entity indicators, and preview paths are in `dwg-feasibility.json`. Generated DXFs, SVG previews, and audit JSON remain under the ignored `local-artifacts\draftsman\user-supplied-ingest\` directory.

Observed sample characteristics:

- All three samples had populated modelspace.
- All named paperspace layouts in the selected samples were enumerated but empty; no selected sample demonstrated a populated intended print layout.
- Sample 01 had 207,609 modelspace entities, 29 IMAGE entities, 10 SHX font references, and very large modelspace extents.
- Sample 02 had 20,572 modelspace entities, 108 `ACAD_PROXY_ENTITY` records, repeated ezdxf `DIMASSOC` copy-process warnings during inspection, 15 SHX font references, and `INSUNITS=0`.
- Sample 03 had 3,374 modelspace entities, 474 `ACAD_PROXY_ENTITY` records, several SHX references including a non-ASCII-looking font name, and `INSUNITS=0`.

Fidelity is not proven exact. Overall risk is `MAJOR_FIDELITY_RISK`, driven by proxy/custom entities, SHX/missing-font availability, DIMASSOC warnings, and unresolved unit/extent/viewport scaling. No conversion was forced past a failed validation condition.

## PDF sample test

The two selected PDFs both rendered successfully through the current `image_loader` on their first page. The first sample had 14 pages and a raster first page; the second had 1 page and a mixed/vector-heavy first page. Both appear useful as future DEV engineering-drawing material, subject to the same source governance. Details are in `local-artifacts\draftsman\user-supplied-ingest\pdf-audit.json`.

## Decision

For the selected material, PDF is not required as the default intermediate. The preferred path is:

`DWG -> ODA File Converter -> DXF -> ezdxf structural inspection / bounded deterministic vector render -> raster evidence only when required downstream`

This is conditional for future files whose intended drawing is in a populated paperspace/plot layout or whose proxy/font fidelity cannot be resolved through DXF. Production DWG ingest remains `CONDITIONAL`, not approved by this task. No `.dwg` GUI input was added, and no `FinalStructure`, `ProductionProcessingService`, OCR, symbol, or export semantics were changed.

## Verification and tracked changes

- Helper test suite: 9 bounded tests pass.
- Ruff check on modified Python files: pass.
- `git diff --check`: pass.
- Generated binaries and previews are Git-ignored and not tracked.
- Modified code files: `cad_photo_to_dxf/app/dwg_converter.py`, `cad_photo_to_dxf/tests/test_dwg_converter_selection.py`.
- Required tracked artifacts: this report, `source-inventory.json`, and `dwg-feasibility.json`.
- Model run: `NO`.
- Candidate mining: `NO`.
- Human semantic labeling: `NO`.
- Validation: `NO`.
- Locked blind: `0 / 8`.
- Production semantic delta: `NONE`.

USER_SUPPLIED_DWG_INGEST_V2_LOCAL_A:
COMPLETE

BASE CHECKPOINT:
f00e8c32a75a79b9d236f2674459190cecf50733

DIAGNOSTIC CHECKPOINT:
b9a29ff

PRODUCTION_SEMANTIC_DELTA:
NONE

USER SOURCE DIRECTORY:
C:\Users\agcrf\Desktop\新建文件夹

TOTAL FILES:
198

DWG FILES:
93

DXF FILES:
0

PDF FILES:
89

RASTER FILES:
3

OTHER FILES:
13

EXACT DUPLICATE FILES:
6 participating files across 3 hash groups

ESTIMATED DISTINCT SOURCE FAMILIES:
UNKNOWN

CURRENT PRODUCTION DWG INPUT:
NO

CURRENT DWG -> DXF SUPPORT:
YES (diagnostic helper added; baseline before task was NO)

CURRENT DXF -> DWG SUPPORT:
YES

CURRENT DWG -> PDF SUPPORT:
NO

ODA FILE CONVERTER FOUND:
YES

DWG SAMPLES SELECTED:
3

DWG SAMPLES CONVERSION ATTEMPTED:
3

DWG -> DXF SUCCESS:
3/3

DXF OPEN SUCCESS:
3/3

DXF MODELSPACE READ SUCCESS:
3/3

DXF LAYOUT ENUMERATION SUCCESS:
3/3

DWG PREVIEW RENDERS:
2

DWG PREVIEW RENDER SUCCESS:
2/2

MAJOR FIDELITY RISKS:
Proxy/custom entities, SHX or missing fonts, DIMASSOC warnings, and unit/extent/viewport scaling; exact fidelity not established.

PDF SAMPLES SELECTED:
2

PDF RENDER SUCCESS:
2/2

USER-SUPPLIED MATERIAL APPEARS USEFUL FOR FUTURE V2:
PARTIAL

PRODUCTION DWG INGEST FEASIBLE:
CONDITIONAL

DWG -> PDF REQUIRED:
NO

RECOMMENDED NORMALIZATION PATH:
DWG -> existing ODA File Converter -> DXF -> ezdxf structural inspection and bounded deterministic vector render; use raster evidence only when needed.

DWG HELPER ADDED:
YES

SOURCE FILES MODIFIED:
NO

SOURCE FILES GIT-TRACKED:
NO

GENERATED BINARIES GIT-TRACKED:
NO

REFERENCE BASELINE V1 RUN:
NO

MODEL RUN:
NO

CANDIDATE MINING:
NO

HUMAN SEMANTIC LABELING:
NO

VALIDATION:
NO

LOCKED_BLIND:
0 / 8

READY FOR USER-SUPPLIED SOURCE ADMISSION TASK:
YES

READY FOR PRODUCTION DWG INPUT INTEGRATION:
NO

GIT STATUS:
clean

STOP.
