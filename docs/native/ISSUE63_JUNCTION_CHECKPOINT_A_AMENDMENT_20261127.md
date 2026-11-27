# Issue 63 A: host references and an actual saved junction checkpoint

This amendment applies to the resumed implementation after issue comment
7218448576. It supplements `ISSUE63_JUNCTION_CONTRACT.md`; the original WIP
contract, interrupted checkpoint and historical issue 62 results stay intact.

## Explicit reference consistency

An omitted `host_path_id` may use a valid index. An omitted `host_path_index`
may use a valid name. A supplied invalid value, including null, empty or unknown
name, boolean, noninteger or out-of-range index, is a refusal. When both fields
exist, they must resolve to the same actual candidate object. The lookup table
must equal the unique identities of the actual candidate sequence. The terminal
must belong to the actual guest. Self-reference and a different declared host
source-edge binding are refusals. No field silently overrides a failed field.

The constructor accepts only new candidates. Supplied `body_role`, `role` and
`path_role` must be absent/null or explicitly `COMPLETE_TARGET_STROKE` /
`COMPLETE_ATTACHED_GRAPH_STROKE`. Any other role, including every
`NECESSARY_PRIOR_*` role, is refused. Presence of `prior_source_binding`,
`prior_binding`, `full_saved_geometry` or `parent_object_id` also refuses the
input, even beside a target-looking role. This preflight covers every input
before any contact observation or insertion is queued. The original rows are
returned unchanged after every refused construction.

## Two separate local proofs

The source domain grants pointwise permission inside an unpadded finite locator,
using original black cells, all three original arms, complete competing pairs,
raw adjacency, complete source chains, and hole/end checks. Before insertion its
finite-host predicate is a strict interior projection, including an already
explicit internal vertex. The separate exact original-chord intersection and
derived binary64 rounding certificate authorize an insertion with representation
error. A global host endpoint is never authorized through a repeated internal
vertex. Neither proof grants ink coverage to the whole locator.

After saving, source coordinates are recovered as exact rational values from
the actual saved binary64 paper coordinates and the declared ordinary frame.
Those exact coordinates are passed to a freshly rebuilt pointwise source proof.
Separately, saved contact must be an exactly equal internal host vertex and lie
on a finite saved segment. There is no fixed small-is-zero tolerance.

## Runnable local interface and stopping boundary

`experiments/issue63_bounded_source/run_junction_checkpoint.py --output DIR`
authors two 80-by-96 rasters, constructs the complete finite candidate rows,
saves DXFs in a writer process, waits for that process to exit, and starts an
independent reader process. The reader uses an independent Fraction cross-product
and finite-bound incidence predicate. It rebuilds source observations from PNG;
it does not consume the construction PASS. It checks every original vertex in
order, both original endpoints, a short guest first segment, actual host/guest
bends, a finite terminal tail, all shared contacts, and a one-ULP saved endpoint
corruption. Source controls preserve failures for explicit unknown/mismatched/
self references, missing guest source, a finite-host truncation, an old formal
host, incorrect rounding, an original white hole, a fourth arm and a white gap.

New local reader schema: `independent-authored-junction-cold-reader-v1`.
Checkpoint schema: `issue63-authored-junction-save-checkpoint-v1`.
The existing production planner/reader schemas and callable signatures are
recorded as observed, with full source-stage readiness explicitly uncertified.
A successful local checkpoint does not claim the unintegrated v4 stage runs.

Output includes the original PNGs, input rows, construction/domain receipts,
before/after/tampered DXFs, SVG/PNG overlays rendered from actual cold-read geometry,
process IDs, source/module/output hashes and a manifest. Process logs are outside
the verified directory. Every rerun uses a new directory; no failed artifact is
overwritten. This is a small authored development result, not unseen evaluation,
real drawing adoption, whole-source responsibility, old-436 protection or GUI
acceptance. Those remain separate downstream gates.
