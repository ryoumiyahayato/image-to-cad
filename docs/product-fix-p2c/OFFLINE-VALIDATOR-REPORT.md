# P2C — ODA Drawings Explorer validation, 2026-10-06

ODA Drawings Explorer 27.9.0 was installed from the official Windows x64 MSI
and tested locally. **Do not adopt it as the complete local development
validator yet:** the unchanged W03 package opens and displays geometry and all
eight images, but its Chinese native TEXT renders as question marks.
The small A/B comparisons display correctly; exact font-file resolution and
variable-font weight remain unverified. No additional viewer was installed.

This result supersedes the Bentley acquisition prerequisite in the earlier
`REPORT.md`. The historical filename of this report is retained. Offline
operation is **not** a requirement: Internet remained available, and no firewall,
proxy, network blocking, account, sign-in or SDK trial was used.

## Requested result fields

```text
PRIMARY_TARGET: AutoCAD Desktop
LOCAL_VALIDATOR: ODA Drawings Explorer (tested candidate; not adopted)
VERSION: 27.9.0 (executable 27.9.0.0)
LOGIN_REQUIRED: NO
ACCOUNT_REQUIRED: NO
LOCAL_DXF_OPEN: PASS
LOCAL_DWG_OPEN: NOT_TESTED
CLOUD_DEPENDENCY: NONE required in the tested local-open workflow
FONT_FOUND: NO (exact CAD resolver discovery not confirmed; local installation YES)
FONT_SUBSTITUTION: A/B none reported, exact resolver unverified; W03 missing LFF font renders Chinese as question marks
CHINESE_RENDER: PASS (small comparison); FAIL (unchanged W03)
LATIN_RENDER: PASS (small comparison)
DIGITS_RENDER: PASS (small comparison)
FILLED_TEXT: PASS (small comparison)
W03_OPEN: PASS
W03_PAN_ZOOM: FAIL (combined validation incomplete: zoom PASS, pan displacement not confirmed)
W03_IMAGES: PASS
W03_STRUCTURE: PASS
SUITABLE_AS_LOCAL_DEVELOPMENT_VALIDATOR: NO
FINAL_AUTOCAD_RC_STILL_REQUIRED: YES
PRODUCT_CODE_CHANGED: NO
```

`FONT_FOUND: NO` is a conservative failure to establish the **exact renderer
font discovery** criterion, not a claim that the TTF is absent from Windows.
Chinese visibility alone is not proof of which font file ODA resolved.
W03's text failure independently prevents provisional adoption. Local DXF
opening itself passes the mandatory login/account/local-rendering gate.

## Installer gate and installation

The installer metadata below was recorded before execution in
`local-artifacts/product-fix-p2c/offline-validator/oda-installer-provenance.json`.

| Field | Recorded value |
| --- | --- |
| SOURCE_URL | https://www.opendesign.com/guestfiles/get?filename=ODADrawingsExplorer_QT6_vc16_amd64dll.msi |
| Official redirect object | https://oda-qt.s3.eu-central-1.amazonaws.com/ODADrawingsExplorer_QT6_vc16_amd64dll_27.9.msi |
| FILENAME | ODADrawingsExplorer_QT6_vc16_amd64dll_27.9.msi |
| FILE_SIZE | 75,572,224 bytes |
| SHA256 | 0E97F39FB151A209E58ADEAE6161D0705B84FD4EE4F3C8C245701F4E6AF19FEC |
| DIGITAL_SIGNATURE | Authenticode Valid; Signature verified |
| Signer | CN=OPEN DESIGN ALLIANCE, O=OPEN DESIGN ALLIANCE, L=Scottsdale, S=Arizona, C=US |
| APPLICATION_NAME | ODA Drawings Explorer |
| VERSION | 27.9.0.0 |
| EXECUTABLE_PATH | C:\Users\agcrf\AppData\Local\Programs\ODA\ODADrawingsExplorer 27.9.0\ODADrawingsExplorer.exe |
| INSTALL_SIZE | 228,619,897 bytes, 179 files (installed directory; excludes installer cache) |
| Installation | Current user; MSI exit code 0; no restart |
| CLOUD_UPLOAD_REQUIRED | NO |

The download was obtained through the [official Drawings Explorer page](https://www.opendesign.com/guestfiles/oda_drawings_explorer).
The MSI contains one application feature and a bundled `OdaFileConverter.exe`
helper. No separate converter/product, BIM/RVT extension or activation was
selected. Existing ODA File Converter 27.1.0 was not replaced. Existing Viewer
27.1.0 had a registry/cache entry but no runnable executable was located.
The Explorer application launched normally into a local file-open workflow,
with no mandatory authentication or cloud conversion step.

No genuine local DWG sample was found in the workspace or installed package.
Workspace `.dwg` test fixtures contain only `fake dwg`/`source dwg` bytes; they
were excluded. No comparison DXF was regenerated or converted to manufacture
a DWG result. DWG viewing is therefore NOT_TESTED.

## Existing P2C font comparisons

Used the existing `local-artifacts/product-fix-p2c/bentley-view/comparison-A.dxf`
and `comparison-B.dxf`. Both contain ten native TEXT objects and no outlines or
rasterized text. The existing current-user font files and registry entries
were reused; no new font installation was needed.

| Check | A: NotoSansSC[wght].ttf | B: ITCCADSC-Regular.ttf |
| --- | --- | --- |
| Local font available | YES; installed/prepared SHA256 match | YES; installed/prepared SHA256 match |
| CAD resolved font path | NOT_VERIFIED; not exposed by inspected UI | NOT_VERIFIED; not exposed by inspected UI |
| Font substitution | No warning reported; cannot certify NONE | No warning reported; cannot certify NONE |
| Chinese | PASS: 电施, 图纸目录, 项目编号 | PASS: same strings |
| Latin | PASS: Project Name, Design Institute | PASS: same strings |
| Digits | PASS: 1, 7, 01, 2024.8.15 | PASS: same strings |
| Registered symbol | PASS: ® | PASS: ® |
| Filled appearance | PASS | PASS |
| Text position | PASS visually; selected 电施 reports (10,110,0) | PASS visually; same source insertion coordinates |
| Text height | Native height 5 confirmed in A properties; visually consistent rows | Source height 5; visually consistent rows |
| Text width | Native width factor 1 confirmed in A properties; no visible clipping/overlap | Source width factor 1; no visible clipping/overlap |
| Native text preserved | YES; selected object is Text with original contents | YES; unchanged DXF retains ten TEXT |
| Actual renderer weight | UNKNOWN | Static file metadata 400; exact renderer resolution unverified |

Visible glyph height and pixel width are not asserted to equal the CAD height
parameter or a final AutoCAD text extent. The rows remain aligned and readable
at zoom extents. A and B have similar visible appearance; this does **not** prove
ODA selected variable weight 400. A's metadata remains wght 100..900, default
100, named Regular instance 400.

The legal static Regular 400 control already existed and was reused. Its
independent family is ITC CAD SC, with retained OFL/copyright and FONTLOG;
see `OFL-DERIVATION-REVIEW.md`. No new derivative or production font was made.

## Actual unchanged W03 package

The prepared W03 package is the prior byte-for-byte copy of the closed P2B
final package. DXF SHA256 is
`aa2f2e58fb5f124b5065cf9abaec94bb51025c694a55d005d7ff9420338f43eb`.
It has 6,072 entities: 842 LINE, 5,011 LWPOLYLINE, 13 CIRCLE, 198 TEXT and
8 IMAGE. All eight IMAGEDEF filenames are relative basenames.

| Check | Actual result |
| --- | --- |
| OPEN_TIME | 1.482 s from submitting local open to first rendered screenshot; includes automation/capture overhead, one observation |
| PAN_ZOOM_RESPONSIVENESS | Zoom window PASS, 0.612 s including capture. Two native PAN drags produced command feedback but no observed displacement; pan validation NOT_CONFIRMED, combined gate FAIL |
| TEXT_VISIBLE | Latin/digits visible; Chinese FAIL, many question marks in room labels/title block |
| FONT_SUBSTITUTION | TEXT uses wqy-unicode STYLE, font wqy-unicode.lff; original FONTALT is simplex.shx. Missing-font fallback is indicated by the rendered question marks; exact resolved font path not exposed |
| LOGO_VISIBLE | PASS at title-block zoom |
| SIGNATURE_VISIBLE | PASS, all seven raster signatures visible |
| RELATIVE_IMAGE_RESOLUTION | PASS: eight existing files, rendered directly from the package with no path edits |
| STRUCTURAL_GEOMETRY_VISIBLE | PASS: border/grid/walls/structural lines and symbol geometry visible |
| MISSING_REFERENCES | No missing IMAGE assets observed; wqy-unicode.lff is the unresolved font reference |
| CRASH | NO observed |
| HANG | NO observed; process remained Responding=True |

A bounded diagnostic temporarily set ODA's FONTALT to the existing absolute
local `ITCCADSC-Regular.ttf` path, then ran `regenall` and reopened the same
unchanged W03 DXF. Chinese labels remained question marks. FONTALT was restored
to `simplex.shx` and queried again to confirm restoration. No drawing was saved.
This diagnostic is not a production font replacement or a successful fallback
configuration. The pan observation may reflect the automation gesture; it is
not asserted as a proven general application defect. Zoom, selection and
command feedback remained responsive.

The [official command reference](https://www.opendesign.com/guestfiles/oda_drawings_explorer/reference)
documents local open, zoom, pan, properties and system-variable inspection.
No further viewer, converter or product repair work follows this result.

## License boundary, separate from the technical result

Use is limited here to an external development/test application. No ODA binary
was bundled, redistributed, integrated or added as a product dependency.
Permanent commercial validation use is **not approved by this technical test**.
ODA's [public-tools FAQ](https://www.opendesign.com/faq/question/what-are-oda-viewer-and-oda-file-converter)
explicitly limits its named Viewer/File Converter examples to non-commercial
applications for non-members. That FAQ does not expressly settle Drawings
Explorer's complete license terms; apply the user's conservative public-example
boundary and require a later Explorer-specific license review before claiming
permanent commercial suitability. No account, membership or trial was started.
This separate review did not block the immediate technical test.

## Evidence and preservation

Evidence is under `local-artifacts/product-fix-p2c/offline-validator/`:
installer provenance, MSI inspection/install log, installed metadata,
`ui-test-measurements.json`, input hashes before/after, and these screenshots:

- `comparison-A-native-text.jpg`: readable A glyphs and native TEXT properties.
- `comparison-B-static-400.jpg`: existing static control at zoom extents.
- `W03-original-open.jpg`: initial full drawing with question-mark labels.
- `W03-logo-seven-signatures.jpg`: all eight relative images and text failure.
- `W03-pan-attempt.jpg`: native PAN feedback without confirmed displacement.
- `FONTALT-restored.jpg`: queried original fallback after restoration.

Post-test hashes confirm both comparison DXFs, W03 DXF and all eight W03 image
files are unchanged. Both installed test fonts still match their prepared
hashes. Git was clean before this report was added; no tracked product code
changed. This is an application validation/docs change, so the prior 32/562
test-suite results are historical and were not rerun or represented as CAD
acceptance. AutoCAD Desktop final RC acceptance remains mandatory and NOT_RUN.
