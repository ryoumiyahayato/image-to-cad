# IMAGE TO CAD — PRODUCT FIX P2C REPORT

P2C remains **incomplete**. The new local development validator is **Bentley
View**; no installed copy or official installer was found on this machine.
Actual comparison and real-drawing load tests are **NOT_RUN**, not PASS or FAIL.
The requested comparison-plus-one-large-drawing stop point has not been reached.
The missing prerequisite is acquiring/installing Bentley View, not an
architecture or font incompatibility finding.

## Updated validator roles

```text
PRIMARY_TARGET: AutoCAD Desktop
PRIMARY_LOCAL_DEVELOPMENT_VALIDATOR: Bentley View
BENTLEY_VIEW_STATUS: NOT_INSTALLED
BENTLEY_COMPARISON: NOT_RUN
BENTLEY_REAL_DRAWING_LOAD: NOT_RUN
BENTLEY_LOCAL_VALIDATOR_SUITABILITY: UNDETERMINED
AUTOCAD_DESKTOP_RC_ACCEPTANCE: MANDATORY_NOT_RUN
TRUEVIEW_STATUS: ABANDONED_INSTALLATION_BLOCKER
AUTODESK_VIEWER_ROLE: SMALL_FILE_AUTODESK_CLOUD_SANITY_CHECK
AUTODESK_VIEWER_DXF_TRANSLATION: PASS
AUTODESK_VIEWER_UNICODE_VISIBILITY: PASS
AUTODESK_VIEWER_FONT_LOADED: FAIL
AUTODESK_VIEWER_FONT_SUBSTITUTION: YES
AUTODESK_VIEWER_FONT_FIDELITY: NOT_VALIDATED
VARIABLE_WEIGHT_INFERENCE_FROM_VIEWER: NONE
LARGE_DRAWING_CLOUD_ACCEPTANCE: NONE
PRODUCTION_FONT_STRATEGY: UNCHANGED
ARCHITECTURE_REOPEN_REQUIRED: NO
P1_REGRESSION: PASS
P2B_REGRESSION: PASS
FOCUSED_TESTS: 32 passed
FULL_TESTS: 562 passed
WORKTREE: CLEAN after the preparation/evidence commit
NEXT_PREREQUISITE: BENTLEY_VIEW_ACQUISITION_AND_INSTALLATION
```

Viewer results above come from the user's manual warning: “Missing fonts ...
were substituted”, including Noto Sans SC. All ten TEXT objects of the earlier
comparison use P2C_NOTO_SC_CANDIDATE/NotoSansSC[wght].ttf. Unicode visibility and
successful DXF translation therefore do not prove that the requested font was
loaded. No weight inference is drawn from the substituted appearance.
**Autodesk Viewer and AutoCAD Web are different products**; no AutoCAD Web font
result is claimed. The old Web handoff is superseded as a primary test.
No TrueView install/debug work was resumed and no large file was sent to a cloud.

## License-reviewed A/B preparation

Before creating B, the exact OFL and embedded copyright/license metadata were
checked and the derivation policy recorded in `OFL-DERIVATION-REVIEW.md`.
Declared RFN is **Source**. B is identified as a Modified Version with an
independent family **ITC CAD SC**, retains original copyright/license, and ships
with byte-identical OFL.txt and a FONTLOG. No production font bundling occurred.
See the [official OFL modification guidance](https://openfontlicense.org/how-to-modify-ofl-fonts/)
and the exact source license in this directory.

| Candidate | File | Family | Variant | Metadata weight | Renderer weight |
| --- | --- | --- | --- | --- | --- |
| A | NotoSansSC[wght].ttf | Noto Sans SC; legacy Noto Sans SC Thin | VARIABLE | default 100; named Regular 400 | NOT_TESTED |
| B | ITCCADSC-Regular.ttf | ITC CAD SC / Regular | STATIC | 400 | NOT_TESTED |

A is the unmodified pinned official Google Fonts resource:
`a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da`.
B was instantiated at wght=400 with FontTools 4.63.0, then consistently renamed:
`5ae93fa926c7941d9d333d86aad1db8f61ad289b660714537fd1cfface214632`.
B has glyf TrueType outlines, no fvar/gvar, OS/2 weight 400, and the same cmap as
A. The original copyrights and license fields remain intact. Both files cover
the specified Chinese, Latin, digits, punctuation and registered symbol.
The source/version definition remains only in `font-candidate.json`.

A and B are installed via the Windows **current-user Fonts registry** and
`AddFontResourceExW(flags=0)`, followed by a font-change notification. GDI loaded
18 resources for A and 2 for B. Installed file hashes match the prepared files;
no prior registry values or different files were overwritten. The existing
system NotoSansSC-VF.ttf has a different hash and remains untouched. These are
**OS registration results**, not CAD FONT_FOUND or substitution acceptance.
Actual Bentley discovery must be confirmed; a renderer requiring system-wide
rather than current-user fonts may need that deployment mode tested separately.
Evidence is in `os-test-font-installation.json`.

`bentley-matrix-and-load-results.json` records all requested fields per A/B:
FONT_FILE/FAMILY/WEIGHT, VARIABLE_OR_STATIC, FONT_FOUND, FONT_SUBSTITUTION,
CHINESE, LATIN, DIGITS, REGISTERED_SYMBOL, FILLED_APPEARANCE, TEXT_WIDTH,
TEXT_HEIGHT and DXF_NATIVE_TEXT_PRESERVED. Renderer values are NOT_TESTED/null.
Both comparison-A.dxf and comparison-B.dxf contain ten native TEXT objects,
height=5 mm, width factor=1; DXF audit passes. A CAD TEXT height parameter is not
asserted as the renderer's visible glyph height. No outline/raster text was made.

## Complete real drawing packages

| Order | Drawing | DXF bytes | Entities | IMAGE assets | Actual open test |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | W03 | 3748617 | 6072 | 8 | NOT_RUN |
| 2 | E01 | 5721036 | 5571 | 2 | NOT_RUN |
| 3 | W01 | 1109085 | 1326 | 1 | NOT_RUN |

The closed-P2B DXFs and every relative IMAGE asset were copied **byte for byte**.
Source and copied DXF hashes match, assets exist, and audits pass. No structural
geometry, logo/signature representation, printed name, OCR content, or final
preview was changed. These load baselines retain the existing LFF STYLE, so
any substitution there must be recorded; they do not demonstrate A/B real-page
text sizing. The prepared data records OPEN_TIME, PEAK_MEMORY_IF_AVAILABLE,
PAN_ZOOM_RESPONSIVENESS, TEXT_VISIBLE, IMAGE_ASSETS_VISIBLE,
STRUCTURAL_GEOMETRY_VISIBLE, MISSING_REFERENCES, FONT_SUBSTITUTION and
CRASH_OR_HANG as unmeasured, rather than inventing runtime evidence.

Large runtime files are under `local-artifacts/product-fix-p2c/bentley-view/`:
comparison-A.dxf, comparison-B.dxf, fonts/, W03/, E01/, W01/ and result JSON.
Reproduce preparation using the existing Python from the healthy checkout root:

```text
python docs/product-fix-p2c/prepare_bentley_matrix.py --output local-artifacts/product-fix-p2c
```

Once an operational Bentley View is available, test A/B first and capture actual
font resolution, rendering and text extents. If comparison passes, open the
complete W03 package and record its load/interaction/IMAGE/structure behavior.
Stop once comparison plus that real drawing determines local-validator
suitability; E01 and W01 are ready if more evidence is needed. Only actual results
can justify a static-B preference. Bentley PASS still does not equal AutoCAD
PASS: desktop AutoCAD RC acceptance remains mandatory.

## Acquisition prerequisite and checks

No Bentley entry was found in installed-software registries, app inventory,
Start Menu, usual program directory or existing download locations. The
[official free download](https://softwaredownloads.bentley.com/en/FreeProductDetails/2793)
was located. Bentley's [current release instructions](https://bentleysystems.service-now.com/csp?id=community_blog&sys_id=8c4eb280875bcf10c0fa43f6cebb35b6)
require signing into Software Downloads. Browser navigation timed out twice;
no installer was downloaded, no account information was submitted, and no
third-party executable was obtained. The user was asked for an existing EXE
path or an official installer downloaded via their Bentley account.

The focused checks cover real A/B font metadata, retained licensing, consistent
rename, native TEXT, exact real package bytes, P2B objects/IMAGE/preview behavior
and P1 grid protection. The full suite protects the current product and does
not certify Bentley rendering. Large TTF/PNG/DXF/NPZ files remain outside Git.
P1 and P2B stay closed. No architecture was reopened.

Execution is currently blocked before local visual testing; the requested
suitability stop point remains pending. Resume with the Bentley EXE/installer
path rather than treating preparation or OS registration as renderer acceptance.
