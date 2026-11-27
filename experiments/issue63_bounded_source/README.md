# Issue 63 bounded-source experiments

These are separate local experiments. They do not replace the ordinary
drawing, merge the experiment into `main`, or establish GUI / Windows
acceptance. The original Issue 62 runners and their results remain unchanged.

The [interrupted checkpoint](../../docs/native/ISSUE63_INTERRUPTED_CHECKPOINT_20261127.md)
is historical. The restored implementation now has executable junction and
saved-context controls. The junction minimum save checkpoint is described in
the [A amendment](../../docs/native/ISSUE63_JUNCTION_CHECKPOINT_A_AMENDMENT_20261127.md).
The source-stage and original-eight-probe adapters have been repaired and
statically checked. Their full new runs still require the coordinator's
single frozen source tree and serial execution; small controls do not supply
real-source adoption counts.

## Small saved-context controls

```bash
python experiments/issue63_bounded_source/run_source_stage.py \
  --sidecar-smoke --output /tmp/issue63-context-controls-NEW
```

This creates authored tiny drawings, actually saves them, and starts a
different Python reader for every control. It checks a normal bound copy,
a changed non-target font resource with a newly generated sidecar, an old
sidecar after a saved endpoint change, an incorrect source-array binding,
one pending drawing sent through the independent v2 source reader, and a
pending drawing that must retain both an old prior and a new adopted host as
context. The latter is a construction control: its supplied host label does
not establish source adoption.

The six controls passed in the local development check on 2026-11-27. The
pending source reader completed and refused source acceptance; the receipt
preserves that negative decision separately from valid file binding. The
first attempt that exposed ezdxf metadata differences was retained. Neither
the real quarter nor the eight probes was run by this binding check.

## Local source stage

```bash
python experiments/issue63_bounded_source/run_source_stage.py \
  --source /private/unchanged-source.tif \
  --prior-plan /private/frozen-prior-plan.json \
  --baseline-dxf /private/unchanged-baseline.dxf \
  --circle-source-object /private/complete-circle-source.json \
  --font-bindings-json /private/font-byte-bindings.json \
  --output /tmp/issue63-source-NEW
```

`--circle-source-object` may be repeated. Font bindings are the independent
reader's byte-bound resource dictionary; they are not font-name guesses.
The prior plan supplies the original ROI, source crop identity and full prior
object bindings. Old candidate geometry and old PASS values are not producer
inputs. The source image, prior plan, baseline DXF and circle files remain
read-only. A fresh graph and `complete_attached_strokes` v4 plan are required.

Every actual output drawing has an `.objects.json` containing the actual
saved DXF hash, original source file and decoded-array hashes, ROI and DPI,
all actual saved IDs, supplied source objects, complete prior/circle
bindings, fonts and persisted entity/resource records. Historical baseline
objects with no supplied source binding are explicitly listed; the script
does not invent one. Source-pixel diagnostics are labelled as pixels and
make no paper-coordinate source-acceptance claim.

Pending paper drawings retain the actual saved current context, including
new adopted neighbors. Their sidecars carry the full context bindings, not
just candidate IDs. A separate process reopens these files and calls
`audit_saved_source_component(..., source_model="v2")` with both expected
file hashes. A completed refusal is valid pending evidence. Every file
presented as locally adopted additionally requires independent source
acceptance. The original baseline is never overwritten.

## Original eight development probes

```bash
python experiments/issue63_bounded_source/run_probes.py \
  --output /tmp/issue63-eight-probes-NEW
```

All eight original source-array hashes and authored input pixels are fixed.
Every case rebuilds its graph, owner, plan, saved drawing and independent
reader result. The historical expectation text and whether it was satisfied
remain visible. A wedge or block label does not decide whether the new model
passes. The baseline must still produce four actual adopted objects and
three proved attachments; zero adoption fails that positive control.

### Separate completed checkpoints

The default invocation still executes all eight cases in their original
order. For serial execution with a completed artifact checkpoint between
cases, first execute the baseline and then select another original name:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B experiments/issue63_bounded_source/run_probes.py \
  --case baseline --output /tmp/issue63-baseline-NEW

PYTHONDONTWRITEBYTECODE=1 python -B experiments/issue63_bounded_source/run_probes.py \
  --case one_pixel_cap --baseline-reference /tmp/issue63-baseline-NEW \
  --output /tmp/issue63-one-pixel-cap-NEW
```

Every invocation constructs and verifies all eight original source arrays
before selecting its execution case. `FROZEN_VARIANTS.json` retains all
eight authored variants and hashes, and explicitly records the selected
`execution_variants`. A single-case `SUMMARY.json` reports original count 8,
planned count 1 and exactly one result; it does not claim an eight-case pass.

A non-baseline case requires a completed single-baseline reference from the
same clean commit/tree, complete source file hashes and producer maps. Its
root and nested manifests, exact baseline input, four adopted objects,
three proved attachments and successful independent saved/source replay
are checked before the new graph starts. Missing, modified, incomplete or
different-tree references are refused. All reference files, including its
root manifest, are bound before and after the new case.

The reference supplies only the original comparison expressions for the
baseline skeleton, graph, candidate representations and component proof
hashes. Every selected case still constructs its own graph, owner, plan,
saved output and independent source audit. Reference geometry or PASS values
are never supplied as source, owner or adoption evidence. Preserve each
completed case and its writer-exit/readback receipts before starting the
next; neither a partial case nor a progress file is a completion receipt.

`FRESH_BRANCH_RESPONSIBILITY.json` records actual new external-arm source
chains, their four-or-more-port junction, independent free terminal, and
saved native owners. Thin/long arm controls must have this fresh graph
evidence. If a component containing such an arm is adopted, the arm requires
one native owner and independent actual-saved source acceptance. Otherwise
it remains explicitly pending; a width field cannot silently absorb it.

## Exact saved protection and execution identity

Protection compares the real persisted baseline with the real saved result.
It retains every prior native entity, REVIEW entity, unmarked modelspace
entity, block/member, style/font, layer, linetype, dictionary and other live
resource, including handles and owners. It uses complete `TagCollector`
records rather than a rounded geometry summary. New diagnostic layers are
the only declared resource additions.

Header values come directly from actual DXF HEADER tags. ezdxf 1.4.5 changes
`$TDCREATE` in memory when reading; the copy writer restores the actual
original value before normal serialization, and the cold comparison checks
it exactly. Save bookkeeping `$TDUPDATE`, `$TDUUPDATE`, `$VERSIONGUID` and
`$HANDSEED` is recorded separately. Only the timestamp substring in the
same named `EZDXF_META/WRITTEN_BY_EZDXF` DICTIONARYVAR code 1 is separately
reported. Its version, key, handle, owner and every other tag remain exact.
No entire dictionary or non-target resource category is exempted.

The producer replay compares every actual saved plan field, including new
fields; it does not reuse the old numeric compatibility whitelist. A
producer replay is recorded separately from independent physical source
acceptance. Both the original `width` and `bounded_width_field` receipts,
including whether each field exists, are retained in `MODEL_RECEIPTS.json`.

Each run writes entrypoint copies, input/source identities, before/after
source-array/prior/circle memory checks, file checks, resource snapshots and
final manifests. New output directories are mandatory. Runtime caches and
child-process logs are outside the verified directory; log paths and hashes
are in the receipts. Failures and partial outputs are preserved. No ordinary
whole-region, CAD GUI, Windows or engineering-time claim follows from these
local checks.
