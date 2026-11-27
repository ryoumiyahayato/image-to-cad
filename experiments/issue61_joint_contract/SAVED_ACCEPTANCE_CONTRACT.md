# Joint saved acceptance contract

The common entry is `experiments/issue60_common_acceptance/run_common_acceptance.py`.
Its output schema is `joint-common-independent-acceptance-v3`. It accepts current
joint receipts and explicitly identified historical receipts without relabeling
historical files as a current conversion.

## Four different sets

1. The baseline consists of every formal object, including the complete named
   block dependency graph reachable from an INSERT. The original top-level
   entity comparison remains separately reported. A changed nested door member
   is a changed complete door even when its top-level INSERT is unchanged.
2. Stage targets come from the supplied adoption receipt. The plan's adopted
   paths, adoption objects, decisions, object evidence and actual saved sidecar
   must agree exactly. Actual saved geometry is then checked independently.
   A declaration chooses what to inspect; it does not prove source ownership.
3. Complete `components[].candidate_paths` remain candidates. They never enter
   the saved target set merely to satisfy a numerical or geometry interface.
4. Every unexpected new ID, missing baseline ID and changed complete baseline
   object is retained separately. An empty adopted target set cannot suppress
   these differences. A candidate present as an undeclared new saved entity is
   an error, not successful adoption.

Missing plan, adoption, publication or execution request produces `NOT_RUN`.
Current joint receipts additionally require an explicit `stage_execution` bound
to the same producer modules, adopted count and complete candidate count.
Supported historical A v1, ink v2 and numerical v2 scopes remain historical.
The two historical v2 forms are distinguished by their actual dependency and
contract fields; a shared schema string is insufficient.

## Preserved drawing content

`independent-saved-native-geometry-audit-v2` compares persisted binary64 values,
stable object identity, geometry, text and transforms exactly. The complete
object snapshot recursively includes all referenced named block definitions.
Block references use case-insensitive symbol resolution while preserving exact
stored INSERT names and definition tags. Missing and cyclic dependencies fail.

REVIEW is a multiplicity-preserving multiset. All named blocks, styles, layers,
linetypes and listed unit/coordinate headers are checked independently. Entity
and owner database handles, timestamps, GUIDs and handseed are explicitly
excluded database metadata, not claimed to be preserved file bytes. Refer to
the saved geometry contract for the exact fields.

Target type dispatch precedes type-specific attribute access. Unsupported
declared types, including an INSERT claimed as an attached line/path, produce a
structured rejection. They cannot raise an unsupported `thickness` read before
the already completed baseline result is saved.

## Binding actual published execution

The checker binds the original raster file, external ROI/DPI, unchanged original
crop bytes, saved DXF, sidecar, worker request, algorithm file map, published
evidence and current producer dependencies. No DXF is created or repaired by
this binding check. Actual inputs are hashed again after inspection.

For a source-stage continuation, the request must contain a captured manifest
identity. The checker verifies the actual manifest and every member's byte
count and SHA, the complete member set, upstream state's canonical identity,
its complete prior geometry/responsibility relationship to the new plan, the
current reused producer and continuation executor bytes, and the published
continuation receipt. Source, parameters, dependency identity and reuse
boundary must agree. The three current attached/contact/numerical execution
records must bind the actual published plan/adoption and saved file. Actual
saved cold-read and quality receipts are read and hashed too.

This checker binds the manifest's runtime/resource identity; it does not claim
to independently recreate that runtime validation. The checkpoint validator and
separate execution-environment audit retain that responsibility. A recorded
pipeline source-gate result is preserved as a result, never promoted to an
independent source-ownership decision. The producer's independent-old-content
check remains `NOT_RUN`; this common checker supplies a separate result without
modifying the producer receipt.

`--source-stage-manifest` and `--source-stage-continuation` allow relocated files
from an evidence package. Their actual SHA must still match the original
request/publication; relocation is not a way to replace evidence.

The later v2 checkpoint contract is an explicit additional mode. Its historical
DXF is read as immutable proof evidence; the new output is still constructed
from complete source objects. The independent checker reads the five-file
historical capsule, published provenance, complete proof projection, current
recursive native contents, restored source assets, current direct samples and
the complete fresh-check inventory. It rebinds retrace witnesses to actual
current owner handles and exact native segment indices and rechecks their
original source pixels. Unknown/missing checks, failed detailed checks, stale
mode selection or use of a v1 capture for the v2 gate fail closed.

Historical proof bodies use an explicit complete schema, including raw/reference
replay records and nonempty detailed check maps. A bare `pass: true` body does
not satisfy that schema. The current saved writer ledger must match actual
entity handles, kinds, types and complete immediate block members, and retain
the old upstream payload except for database handles. Portable font and license
files are read from beside the actual DXF and compared to the original export
SHA. Sidecar font identity (excluding its provenance source path), repair
regions, native schema and serialization records remain exact too. These
checks accompany the recursive saved-object comparison; they do not replace it.

The worker publication, pipeline report and export must all explicitly select
`SOURCE_CHECKPOINT_PROOF_CONTINUATION` and bind the same saved gate file. Its
effective audit is a separate exact composition with a canonical core digest;
the original fresh audit remains unchanged. Common acceptance separately
reports `fresh_legacy_source_replay: FAIL_RETAINED` when applicable. It does not
rename that failure to a fresh PASS, and continued upstream evidence does not
authorize new attached candidates. The v2 original-pixel binding currently
supports one raster frame with orientation zero and no explicit page/frame
selector; other selections return an explicit unsupported result.

## Independent numerical execution bridge

Pass the independently executed `verify-plan` CLI's `OUT.execution.json` as
`--numerical-replay-receipt`. The common checker reads the actual original `OUT`
and verifies its SHA. `--numerical-replay-result` only relocates that exact file.

The receipt and original result must agree on the joint schema, original source,
file and canonical plan hashes, current producer dependencies, worker request
and complete algorithm identity. Both must record the actual source graph
rebuild, and the original result must contain `pass: true`,
`reason: ATTACHED_GRAPH_JOINT_V3_SOURCE_REPLAY` and the exact canonical saved plan
hash. Historical inspection, missing receipts or an early failed verifier do
not become a current source rebuild. The common entry records that it binds an
external independently executed receipt; it does not falsely claim to have run
that numerical source rebuild itself.

## Three verdict layers and zero adoption

Identity/numerical replay, saved geometry/protection/editing, and complete
original-pixel responsibility are separate. None can cancel another's failure.

With zero adopted objects, saved-target raw review and real new-object
delete/move are `NOT_APPLICABLE_ZERO_ADOPTED`. Complete unadopted candidates still
have their own `SOURCE_UNRESOLVED` result. Successful protection and current
replay can yield `PASS_ZERO_ADOPTED_PRESERVED_BASELINE`; this is explicitly not
complete source approval, candidate adoption or four recovered strokes.

The current independent pixel reviewer still reports its real limited-context
and finite-boundary limitations. The separate complete-model review is
`NOT_RUN_PENDING_PARTNER_CONTRACT`. No producer boolean or hard-coded source
authorization is substituted for that future evidence.

For nonempty verified targets, `--edit-copies` creates independent programmatic
delete/move copies. A writing process completes its normal save and exits; a
new process cold-reads and exactly compares the complete non-target contents.
These are saved-file checks, not CAD GUI tests. Old edit results are never
inherited by a new drawing.

## Command and failure artifacts

```bash
PYTHONPATH="$REPO/cad_photo_to_dxf" "$PYTHON" \
  "$REPO/experiments/issue60_common_acceptance/run_common_acceptance.py" \
  --source "$SOURCE" --baseline "$BASELINE" \
  --dxf "$ACTUAL_DXF" --metadata "$ACTUAL_METADATA" \
  --source-roi "$X0" "$Y0" "$X1" "$Y1" \
  --audit-roi "$AX0" "$AY0" "$AX1" "$AY1" --dpi "$DPI" \
  --execution-request "$ACTUAL_WORKER_REQUEST" \
  --numerical-replay-receipt "$ACTUAL_NUMERICAL_EXECUTION_RECEIPT" \
  --out "$NEW_OUTPUT_DIRECTORY"
```

The baseline protection receipt is written before target-type inspection.
Normal failed checks and malformed supplied receipts produce
`SAVED_GEOMETRY_AND_EDITS.json` and `COMMON_ACCEPTANCE.json`, with explicit
failure reasons and child exit codes. They are not reduced to a Python
traceback. An output directory must be new so existing frozen receipts are
never overwritten.

The local regression fixtures are synthetic contract counterexamples; they do
not count as real ordinary conversion, real original-image numerical replay or
real CAD editing evidence. Actual historical and current execution receipts
are delivered separately with their immutable file identities.
