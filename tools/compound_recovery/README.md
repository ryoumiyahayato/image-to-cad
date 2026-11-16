# Registered-source compound parts experiment

This is an **opt-in experimental partial representation**, not general compound
symbol recovery and not a product acceptance result. The baseline is commit
`d5c05642de7150b254ccccafb8716bf7dfbab503`. Default processing, OCR identity gates,
and `observed_open_strokes.py` are unchanged.

**Current continuation:** automatic compound retirement now also requires
preservation of every observed native black/white pixel center under all tested
caps, for every registered contract. See
[`compound_native_center_policy.md`](../../docs/research/compound_native_center_policy.md).
The earlier A2 positive described below is historical and fails this stronger
condition; it receives no exception. Native-grid research passed its fixed
controls but recovered zero parts in the complete motivating real cohort, and
has not been registered in the production entry.

## Representation and permission

The normal production service accepts `--experimental-compound-strokes`. It
requires the existing registered bitonal original scan. A source parent is
eligible only when all its working foreground remains current, visible,
unclaimed, and outside the existing text, line, logo, and signature masks.
Clipped/crop-edge parents and unbounded resources are retained. A skeleton
proposes exclusive members; no junction clustering, branch pruning, semantic
classification, or electrical connection inference grants permission.

The independent short straight contract is in
`docs/research/short_straight_contract.json`; its immutable SHA256 is
`b2678b460fcf5bb73d1d26df1a3a281d555db23c5f458a5a5db8c4f6ed10ebfc`.
It uses at least 12 distinct original-grid cross sections, at least 2 mm of
collar-excluded interior, interior aspect ratio at least 8, unchanged working
boundary and pen quantization limits, and at most one original pixel of
bidirectional pen boundary error. Only straight parts qualify. The old 10 mm
complete isolated-stroke contract remains intact.

An accepted parent emits native LINE members on `NATIVE_COMPOUND_PART`, exact
remaining original pixel-cell HATCH on `COMPOUND_SOURCE_RESIDUAL`, and off,
frozen, locked full original source backups on `SOURCE_COMPOUND_OUTLINE`.
Each candidate's fit support is partitioned into actually retired pixels and
retained cut interfaces. Every original source pixel belongs to exactly one
retired member or the unresolved residue. The interfaces remain in the residue.
Editing one native member does not move the whole source object or its residue.

All coordinates retain the original center phase:
`native = (work + 0.5) * ratio - 0.5`, with an explicit crop and local tile origin.
The standard paper pen requires an isotropic source-DPI paper scale. Unsupported
coordinate transforms are rejected before DXF mutation.

## Additional adoption gates from independent review

The frozen numeric thresholds have not been relaxed. Real counterexamples led
to additional rejection checks before source retirement:

1. Continuous source-cell/pen contact and topology must survive round, butt, and
   square caps. A retained source interface cannot be replaced by an artificial
   gap caused by standard lineweight quantization.
2. The actual same-grid native rendering must preserve foreground 8-neighbor
   and background 4-neighbor regions, with bidirectional region correspondence.
   Total component/hole counts alone cannot hide one lost hole and one new hole.
3. Native foreign ink and the full working-grid forbidden/protection cells must
   remain untouched. Independently adopted parents' pen envelopes cannot touch.
4. The exporter recomputes geometry and ownership proofs before writing any DXF
   objects. A wrapper preflight must pass before retiring the working parent.

A2 is an exposed development page. HABS and ENV are previously exposed
regression sources, not blind validation. The 24 short-slash compounds that
motivated this research are **not recovered** by this contract. The initial
HABS positive failed an independent original-hole check and must remain a
failed diagnostic; it is not an accepted output or a second-source success.

## Offline whole-page reproduction

Use the ordinary application dependencies and registered input pair. The Linux
research runner disables ONNX telemetry before importing the runtime and applies
a process-local seccomp filter that rejects network socket creation/connection
and send operations. It refuses to continue if the guard cannot be installed.
This is a restriction on the experiment, not a change to the image or OCR result.

```bash
ORT_DISABLE_TELEMETRY=1 QT_QPA_PLATFORM=offscreen \
python tools/compound_recovery/run_observed_cli.py \
  --repo /absolute/repository --capture /absolute/evidence/candidate \
  -- --headless --ocr --source-dpi 100 \
  --input /absolute/input.png --original-scan /absolute/original.tiff \
  --experimental-compound-strokes \
  --output /absolute/evidence/candidate/page.dxf \
  --preview /absolute/evidence/candidate/preview.png \
  --report /absolute/evidence/candidate/report.json
```

Run the baseline at the stated commit with the same inputs and options, omitting
only the experimental flag. The runner observes and returns the original stage
results without overriding masks, coordinates, text answers, or source pixels.
It records a launch source inventory and checks that it is unchanged on exit.
`compound_stage.npz` is produced only if the experimental stage is called.
Private input rasters, actual CAD outputs, and extensive audit evidence belong
in the private experiment delivery, not the public source repository.

The runner is Linux-only; the application feature itself does not depend on
seccomp. The delivered DXF can be opened directly for the minimal target-CAD
review without rerunning OCR. CAD GUI behavior, DWG interchange, and actual
human time saved must be reported separately from automated DXF checks.

## Earlier cloud checkpoint (2026-11-16; historical bounded-fit evidence)

The final related test selection passed **177 tests**; the independent frozen
short-part controls passed 19 cases. All three baseline/candidate page pairs
completed through the ordinary CLI, with source inventories unchanged during
each run. Each of the six saved DXFs has zero audit errors and zero required
fixes, and its save/read representation is preserved.

| Page | Adopted compound LINEs | Model entities, baseline to candidate | Native TEXT, unchanged |
| --- | ---: | ---: | ---: |
| A2 | 1 | 36,558 to 36,564 | 199 |
| ENV | 0 | 3,693 to 3,693 | 99 |
| HABS | 0 | 3,553 to 3,553 | 40 |

A2 retires exactly seven old target contours, all inside the actual accepted
source footprint. It emits one LINE, four visible residual HATCH, three hidden
full-native HATCH and five hidden working-boundary backups. All non-target
entities, 48 old open-stroke/frame source members, fonts, blocks and image/source
dependencies are preserved. The only allowed old binding metadata change is
the global structure revision reference, enumerated separately from geometry.

The source ledger is 1,360 native pixels = 42 retired + 1,318 retained. Three ink
components and five paper holes retain their identities in continuous geometry
and on the original grid, for every tested cap. This is bounded fitting: 13 old
black pixel centers are uncovered and one new center is covered. Exact source
accounting must not be described as pixel-identical rendered geometry.

HABS's failed diagnostic parent is protected earlier in the real full-page
pipeline. The native-hole rejection is proved separately by local diagnostic
replay; neither observation is a second-source positive. The 24 motivating
short-slash compounds remain unrecovered. Target-CAD editing and cold reopen,
DWG roundtrip, blind generalization, and human net time savings remain untested.

## Explicit export contract dispatch (continuation, 2026-11-16)

The exporter now rejects missing or unknown contract versions and hashes before
any DXF mutation. An unrecognized short/proposal record must not silently enter
the older 10 mm long-part branch. The previously unversioned long emitter
fixtures use the explicitly frozen `native-compound-long-export-v1` contract
(canonical JSON SHA256
`854460e1c9fd1f9baad07e9de386c1d453e583a2490e3b5440d52aad7a57b3df`).
The existing short contract and its numeric geometry gates are unchanged.

New proposal declarations require their own explicit registration. The current
dispatcher accepts neither unknown proposals nor the early working-grid
research schema as a long-export alias. This tightening does not certify any
new native-grid algorithm. The related regression selection passes 193 tests,
including pre-write rejection of long members carrying incomplete or unknown
contracts, and the previous actual A2 record still passes validation.
