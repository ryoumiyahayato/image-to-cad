# Issue #59: attached-end raw ink and retained-object contacts

This is the independent #59 experiment from A result commit
`2010e6da30b4aa9812ec4730d338edf76fca6b2d`. Main remains the 436-object
baseline. No merge, Windows build or CAD GUI exercise is performed here.

The [implementation contract](../../docs/native/ATTACHED_INK_CONTRACT_20261127.md)
was frozen before the first ink gate executed (SHA-256
`f0f44df88b9403d6f186cfe0a55afa1c827b40fc2c715ed64e0c4818b1c5c53f`).
The original A/B results and coordinator's strict replay failure remain history;
the new receipts are plan/adoption/native **v2**, not relabelled v1 evidence.

## What changed

`attached_stroke_ink.py` binds each actual finite guest and host to original
black/white cells, independent arm-width sections, coherent finite round-cap
models and bounded short-continuation counterevidence. It preserves failed
receipts before the complete component's adoption decision. Unknown source,
unsupported direction, incomplete observation and contradictory geometry are
different outcomes. Hidden physical subpixel pen travel remains unidentifiable
under the declared observable CAD endpoint convention.

`attached_stroke_contacts.py` checks every actual retained graphic member,
including block members. A finite point needs the old member's own unchanged
source path and independent current graph ports. Positive native-length overlap
is refused. Curves use their actual finite parameters for conservative bounds;
a related unsupported contact is pending rather than approximated by a chord.
All existing duplicate, source, text, free-end, direction and new/new gates stay.

The ordinary planner retains all complete `candidate_paths` and accumulates
`attachment_responsibility_checks`, `prior_native_contact_check` and all failed
adoption gates. One pending end blocks the joint host/companion component. No
subset of the old four-object drawing is copied into the new formal output.

## Frozen development probes

Every variant rebuilds its source graph and adopted owner. None is a holdout.

| Probe | Adopted objects | New middle-end result | Strict fresh-process replay |
| --- | ---: | --- | --- |
| baseline | 4 | PROVED_TERMINAL | PASS |
| one_pixel_cap | 4 | PROVED_TERMINAL; new pixel ledger/model evidence | PASS |
| three_pixel_cap_row | 4 | PROVED_TERMINAL; new pixel ledger/model evidence | PASS |
| six_pixel_wedge | 0 | Boundary competition and unexplained ink | PASS |
| six_pixel_block | 0 | Boundary competition and unexplained ink | PASS |
| three_pixel_thin_tail | 0 | Existing graph-arm refusal | PASS |
| fifteen_pixel_stub | 0 | Boundary competition and unexplained ink | PASS |
| existing_long_tail_control | 0 | Existing graph-arm refusal | PASS |

The wedge, block and stub have 6/6, 6/6 and 15/15 newly black cells in the
middle-end ledger. Their original terminal has no coherent supported model;
finite source-compatible extension witnesses are recorded, never adopted as
new geometry. The thin/long tails fail before the endpoint stage, so an endpoint
ledger for those cases is **not applicable**, not silently counted as passing.

The first probe-harness run failed before this gate because it incorrectly
treated the graph edge list as a dictionary. Its eight errors are retained;
the repaired harness ran into a new output directory with unchanged inputs.

An additional 10 frozen local controls cover a normal round T, clear extension,
disconnected neighbor, finite-host shortening, a true white hole, strict width
upper bounds and a white cell swallowed by the *union* of two capsules. The
finite L-host-cap control is a geometry-kernel check, not a fabricated ordinary
three-arm adoption. There are 27 retained-member contact tests. Together with
existing graph/save/edit/source-replay checks and six new receipt-tampering
checks, the affected suite has **86 passing tests**.

## Actual source: stage result before ordinary output

The original source and all 436 prior bindings were used to discover and fit the
component afresh. Old A proposed paths were not imported. Four complete native
geometry candidates remain, but **zero are adopted by the new joint gate**.

| Stroke | Actual responsibility state |
| --- | --- |
| Left slant, including its real lower free tail | Both original free-end checks pass; complete candidate remains pending with its joint component. It is not truncated at the appendix. |
| Middle slant | Guest has two independent width sections; the finite host has none meeting the frozen exclusivity/white-boundary conditions. Source responsibility pending; all six disputed black cells are retained. |
| Right slant | Independent guest/host widths exist, but the two-stroke model leaves connected residuals and cannot close the observation before its resource boundary. This is a model-scope limitation, not proof of a missing tail. |
| Near-horizontal appendix | Its actual short first segment is below the existing finite direction minimum, and independent local widths are insufficient. Direction/model scope and source pending. |

The fresh all-prior contact gate checks 436 objects / 520 actual members and
finds three source-authorized owner points, no extra unsourced point, no
positive-length overlap and no relevant unsupported-curve contact. This is
contact evidence for candidates, not permission to override their raw-ink gate.

The first real diagnostic was interrupted. A traced repeat localized excessive
work to extension enumeration after the observation was already unclosed.
The repair preserves pending and raw evidence, marks that search NOT_RUN, and
propagates nested resource limits. It does not change the width/cap thresholds.
The stable fresh run then completed in about 30 seconds with zero OCR calls.

Ordinary saved-DXF generation, strict cold read and exact old-content protection
are recorded in the subsequent execution receipt; this stage result alone does
not claim their completion. Source scans, coordinates, OCR, fonts, models, DXFs
and private report links are deliberately absent from this public directory.

## Reproduction and handoff to #60

With the repository's exact native runtime and separate pytest dependencies:

```bash
python -m pytest cad_photo_to_dxf/tests/test_attached_stroke_graph.py \
  cad_photo_to_dxf/tests/test_attached_stroke_contacts.py \
  cad_photo_to_dxf/tests/test_attached_stroke_ink.py -q
python experiments/issue59_attached_ink/run_probes.py \
  --repo . --output /absolute/new/probe-directory
python experiments/issue59_attached_ink/run_source_stage.py \
  --repo . --source /authorized/source.tiff \
  --prior-plan /authorized/frozen-A-plan.json \
  --output /absolute/new/source-stage-directory
```

`run_source_stage.py` is explicitly a stage diagnostic. The ordinary entry is
still `main.py --headless --mode native-objects`; it must run from the actual
source with its own writable cache and verified raw observations.

The likely #60 integration conflict is `verify_attached_stroke_graph_plan` and
the schema constants in `attached_stroke_audit.py`. This branch leaves comparison
exact: `plan.get(key) == replay_value`. New fields include the two producer hashes,
all candidate endpoint receipts, coherent models, raw pixel ledgers, preserved
width failures and all-prior contact proofs. Original pixels, finite geometry,
source identities and discrete decisions must not be relaxed under a broad
floating tolerance. The coordinator's old official replay FAIL is unchanged.

## Explicit limits

This first model covers constant-width round capsules. Its pixel-cell proof is
a conservative compatibility model, not exact raster reconstruction. Raw
connected-component labels are local to the recorded observation window; they
do not prove global disconnection outside it. Cap/body/join detail labels use the
nearest pixel-center feature; whole-cell guest/host support is the exact finite
distance test. Width exclusion uses this joint candidate component and owner;
it is separate from the all-prior *native contact* gate. Finite extension events
are counterevidence searches, not a complete search over all real-valued lengths.
These limitations remain visible rather than being used to claim four recovered
real objects or to declare A's saved geometry wrong.
