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

Private drawings, OCR caches, crops and actual CAD experiments stay outside the
public repository. The tests accompanying this stage use synthetic inputs;
original-source positive and genuinely clipped negative controls belong with
the private execution checkpoint.
