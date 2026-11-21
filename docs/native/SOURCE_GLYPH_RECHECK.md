# Source-bound annotation recheck

This optional local continuation consumes an existing native checkpoint and
its original controlled image. It performs no OCR and no regional conversion.
Select an existing annotation group ID; no expected transcription is accepted
as an argument. Keep the original checkpoint and all failed attempts.

Use the native dependencies and resources in [REPRODUCE.md](REPRODUCE.md).
From `cad_photo_to_dxf`, with that environment activated:

```bash
python scripts/resolve_annotation_group.py \
  --checkpoint-dir /controlled/checkpoint/region.native \
  --source-image /controlled/source.tiff \
  --group-id EXISTING_GROUP_ID \
  --out-dir /controlled/new-binding

python scripts/export_annotation_group_checkpoint.py \
  --checkpoint-dir /controlled/checkpoint/region.native \
  --source-image /controlled/source.tiff \
  --updated-text /controlled/new-binding/updated_text.json \
  --group-id EXISTING_GROUP_ID \
  --context X0 Y0 X1 Y1 \
  --out-dir /controlled/new-local-dxf
```

The first command verifies the published checkpoint hashes and original image.
It rechecks saved recognition inputs, exact character conflicts, complete source
domains and reliable same-page references. A calibrated continuous shoulder,
complete isolated context and raw model alternative must all agree. Missing
reference classes and overlapping pixel distances remain explicit limitations.
Raw OCR strings and confidence values are retained. Failure leaves the entire
original group pending and returns exit code 2; it cannot publish partial lines.

The second command requires the accepted receipt and every original line. It
writes one MTEXT with ordered source widths, paragraph offsets, pitch, height
and rotation, while copying saved neighboring entities whole. `before.dxf`,
`restored.dxf`, `moved.dxf` and `deleted.dxf` are separately saved and read by
new processes. The edit files have independent audits. This remains paper
millimetres; an architectural scale requires separate calibration.

Ordinary CAD editing must still be checked in the chosen application. Preserve
its native save without postprocessing, inspect content/layout and entity type,
then exit the application completely and reopen the saved file. A changed file
does not inherit the original source audit. Agent samples do not establish
engineer repair time or complete-region acceptance; product status remains
`LOCAL_NO_GO`.

## Observed LibreCAD limitation

LibreCAD 2.2.1.6 displays the native `\p` paragraph controls, `\W` width controls
and their braces as literal characters. Removing only paragraph controls or
only braces does not fix it. A plain `\P` multiline string displays normally,
but removing the other controls loses the explicit source row widths and left
offsets. Consequently the source-preserving output must not be reported as
passing that application's layout gate merely because its saved MTEXT reads
correctly in ezdxf. Keep the failed consumer evidence and the original output;
any simplified compatibility copy requires its own layout assessment.

For a bounded native-edit diagnostic only, derive plain paragraphs from the
existing saved MTEXT instead of supplying a replacement transcription:

```bash
python scripts/make_plain_mtext_diagnostic.py \
  --source /controlled/new-local-dxf/restored.dxf \
  --target-id EXISTING_GROUP_ID \
  --output /controlled/plain-edit-diagnostic.dxf
```

This deliberately removes per-line width and indent controls and records
`source_layout_preserved=false` and `overall_task=NOT_PASSED`. It does not
replace the source-preserving output. A bounded ordinary LibreCAD edit and move,
save, full exit and reopen retained one MTEXT and the neighboring curve's
geometry, but changed the font and reference width and dropped entity XDATA.
Native editability therefore passes separately from the failed layout gate.

### Bounded native-layout probe for LibreCAD 2.2.1.6

Keep the source decision, original DXF and failed displays unchanged. First
create an ordinary multiline MTEXT in LibreCAD itself, using the same complete
content and source-backed nominal height and spacing, then save it as a separate
template. Read that actual DXF before choosing a compatible expression.

The completed comparison was limited to four constructions:

| Case | Construction and purpose |
| --- | --- |
| A | Unchanged rich MTEXT: retain the known literal-control-code failure. |
| B | GUI-authored ordinary MTEXT: establish this consumer's saved attributes and font selection. |
| C | One plain native MTEXT using B's font selector, source height, pitch, rotation and a shared source-derived left position; preserve the existing neighbor. |
| D | Same as C, changing only the reference width to the source envelope width. |

The following optional script creates **only C and D**, without OCR, an expected
transcription argument or any production-writer change:

```bash
python scripts/probe_librecad_mtext_layout.py \
  --source-restored /controlled/new-local-dxf/restored.dxf \
  --source-layout-receipt /controlled/new-local-dxf/local_edit_check.json \
  --native-template /controlled/cad-authored-template.dxf \
  --out-dir /controlled/new-layout-probes
```

It verifies the source DXF hash, saved MTEXT signature and complete ordered row
ledger. The common left position uses the median of the source row offsets;
the recorded per-row error is an approximation, not preserved individual
indentation. Existing style records and neighbor entities remain unchanged.
Both outputs are `DIAGNOSTIC_NOT_ADOPTED`; the script cannot issue
`NOTE_LAYOUT_PASS`.

| Native property or syntax | Observed behavior in this version |
| --- | --- |
| `\P` | Creates ordinary paragraph lines without visible control characters. |
| Insertion, height, rotation, shared top/left alignment and exact line spacing | Usable native properties. Baseline pitch follows height × spacing factor × 5/3; verify the resulting display rather than only reading these fields. |
| `\pxi...` and `\W...` | No independent row-indent or width-factor support; the controls appear literally. |
| MTEXT style name versus `STYLE.font` | The MTEXT style name selects a LibreCAD LFF/CXF font. The STYLE table's font filename and width field are not proof of equivalent rendering; an unknown selector can fall back to `standard`. |
| Reference width | C and D produced the same native glyph geometry despite different reference-width fields. Ordinary save writes a width based on the displayed rows; this field does not horizontally fit them to the source. |

These consumer-specific findings agree with the versioned
[MTEXT renderer](https://github.com/LibreCAD/LibreCAD/blob/29179cdc09fbec439a1cb0931d92e67f4c0f6622/librecad/src/lib/engine/rs_mtext.cpp)
and [DXF import/export](https://github.com/LibreCAD/LibreCAD/blob/29179cdc09fbec439a1cb0931d92e67f4c0f6622/librecad/src/lib/filters/rs_filterdxfrw.cpp).
They are not a general font-mapping contract for other CAD applications.

Measure the actual LibreCAD native PDF output separately from nominal DXF
attributes. Anchor the page-to-paper transform to the unchanged neighbor, not
to the text being tested. Record each row's native vector bounds, actual ink
bounds, baseline, left/top position, pitch and rotation; retain print stroke
width and raster quantization limits. An ezdxf rendering or a correct
`plain_text()` result cannot substitute for this consumer measurement.

The tested plain expression displayed and retained one editable MTEXT through
ordinary line editing, whole-object movement, save, full application exit and
reopen. Its source-width comparison nevertheless failed: some rows remained
too wide while another remained too narrow. Changing the common height or the
reference-width field does not independently correct those row widths. The
single-MTEXT source-layout gate therefore **remains failed** after the bounded
comparison. Keep the edited file's own audit and `LOCAL_NO_GO`; do not adopt
these diagnostics, add alignment spaces, outline text, or continue an unbounded
font/parameter search.

Private drawings, OCR caches, crops and actual CAD experiments stay outside the
public repository. The tests accompanying this stage use synthetic inputs;
original-source positive and genuinely clipped negative controls belong with
the private execution checkpoint.
