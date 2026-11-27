# Joint attached-stroke contract, frozen before integration

Date: 2026-11-27. Task: #61. Implementation base is #59 result
`28718414afa5b1660c400716be5331d631a42104`; the finite reference arithmetic
comes from #60 result `6eaa46c6ae68ec323bc58a8773b5aa93db18a8ce`.

## Exact version boundary

| Artifact | New schema |
| --- | --- |
| Source plan | `source-attached-stroke-joint-plan-v3` |
| Adoption receipt | `source-attached-stroke-joint-adoption-v3` |
| Native source binding | `source-attached-stroke-joint-native-v3` |
| Numerical certificate | `attached-stroke-joint-numerical-certificate-v3` |

`joint_contract.version` is `attached-stroke-joint-evidence-contract-v3`.
The current graph stays `producer_sha256`; `additional_producer_sha256` binds
`attached_stroke_ink.py`, `attached_stroke_contacts.py` and
`attached_stroke_numeric.py`. `numerical_contract` identifies the current module
and its retained #60 finite reference arithmetic lineage. No historical v1 or
either historical v2 is renamed as a joint execution.

## Separate scope and responsibility

`plan.paths` is the formally adopted set only. Each
`components[].candidate_paths` retains complete candidates and all raw-ink,
source, contact, direction and competition receipts even when adoption fails.
The numerical evaluator reads those actual candidate locations directly; it
does not move them into `paths`, including in a temporary adaptation view.

The numerical certificate has `diagnostic_scopes`. Each component records
`candidate_path_ids`, `adopted_path_ids`, the input locations, diagnostic status
and `source_adoption_authorized: false`. Empty, candidate-only, adopted and
numerically pending components remain distinct. Missing candidate geometry or
contact references produce structured invalid-input results, never a leaked
`KeyError`. A valid numerically pending component must have no adopted paths;
its entire negative evidence subtree replays strictly and gains no whitelist.

Only the already justified #60 source-chord angles, finite contact fractions,
core axis points and residual diagnostics receive source-derived enclosures.
The same explicit diagnostic grammar applies when those original fields occur
inside complete candidate records. Raw pixels, masks, native finite geometry,
endpoints, path IDs, ownership, types, decisions, hashes and new ink-model fields
remain exact. This does not change #62 width, white-cell or model-boundary gates.

`complete_attached_strokes` retains its existing callable signature. Its receipt
adds `stage_execution` with `stage: complete_attached_strokes`,
`status: EXECUTED`, `source_graph_input` (`REBUILT_FROM_ORIGINAL` or
`CALLER_SUPPLIED_BOUND_ORIGINAL_GRAPH`), actual `adopted_path_count` and
`candidate_path_count`, graph/additional producer identities, and the joint
contract. Candidate count includes retained candidate copies of adopted paths;
it is a receipt, not an adoption rule. Absence of a receipt cannot mean that the
joint stage executed with zero adoption.

## Predeclared discriminating checks

- The real #59 candidate-only plan is numerically inspectable without moving a
  candidate into the adopted set or relabelling its historical execution.
- A new joint candidate-only plan cold-replays with original graph reconstruction.
- Removing a referenced candidate, changing producer identity, changing one
  native coordinate/ID or widening the numerical certificate cannot pass.
- Ambiguous numerical decisions retain complete pending candidates; malformed
  references produce explicit invalid-input reports.
- The original v1 strict failure remains a failure. Its explicit historical
  diagnostic compatibility remains narrowly bounded and separately reported.
- The original #60 arithmetic controls remain meaningful. Same-name fields in
  unrelated locations and the new raw-ink receipt never inherit its whitelist.
- Saved targets, unexpected IDs and baseline recursive object protection remain
  independent checks owned by the common saved-file interface.

The source-stage checkpoint may restore only the strictly bound preceding
source state. Every joint graph/raw-ink/contact/numerical stage and saved-file
check runs again. Passing diagnostic replay never grants raw-source adoption or
changes the original protection baseline.

## Cold execution receipt and common-audit bridge

The executable interface and exact receipt fields are documented in
`NUMERICAL_REPLAY_USAGE.md`. A new-process `verify-plan` writes the unwrapped
production result and a separate `joint-numeric-execution-v3` receipt. The
receipt binds the checked plan's file SHA and canonical SHA, original source
file SHA, ROI, current producer files, complete algorithm identity, and the
actual ordinary worker request when supplied. It records the output report's
absolute path and file SHA. Only completed original-source reconstruction in
the production verifier can set `independently_rebuilt: true`.

The common saved-file audit must read that referenced report, validate its
bytes, and bridge its plan identity to the actual stage and publication. The
numerical CLI does not inspect DXF bytes, certify a source responsibility
model, or declare an ordinary conversion complete. A plan with no formal
paths cannot claim an adopted component or `new_complete_path_ids`; this is an
explicit `NUMERIC_ADOPTION_DECLARATION_WITHOUT_FORMAL_PATHS` input failure.
