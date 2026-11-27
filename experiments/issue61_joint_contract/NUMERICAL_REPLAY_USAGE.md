# Joint v3 numerical replay interface

## Responsibility

`replay_numerical_contract.py` provides four explicit operations. All outputs
are newly created files. Existing output or execution-receipt paths are
rejected. The operations never invoke OCR, modify original inputs, or generate
a DXF. They retain exact original plan schemas and execution identities.

| Operation | Input and actual work | Meaning of success |
| --- | --- | --- |
| `legacy-compatibility` | Frozen saved and replayed historical v1 plans, original strict-failure receipt, explicit frozen producer SHA | The original strict failure remains `FAIL`; only explicit bounded diagnostic compatibility passes |
| `inspect-candidates` | Exact plan bytes with an explicit expected file SHA; diagnostics read their original candidate locations | Diagnostics are readable in the recorded historical or joint scope; no graph reconstruction or adoption occurs |
| `generate-plan` | Original raster SHA, recorded ROI and prior object bindings | A newly executed joint v3 source plan exists; prior bindings are inputs, and generation is not an independent verification or ordinary conversion |
| `verify-plan` | Exact joint plan bytes, original raster SHA, optional actual worker request | The production verifier independently rebuilds the graph from the original pixels and compares the joint plan under the narrow numerical contract |

Formal targets remain `plan.paths`. `components[].candidate_paths` retains
complete failed or adopted candidate records, including their raw source,
contact, competing-direction and finite-geometry evidence. Numerical
certification never turns one of those candidate records into a formal target.
`candidate_path_count` includes a retained candidate copy of an adopted path.

Historical v1 and the two historical v2 meanings are not new joint executions.
The production verifier rejects them with
`HISTORICAL_OR_UNKNOWN_PLAN_IS_NOT_JOINT_EXECUTION`. The historical diagnostic
entry points exist to preserve and explain that history explicitly.

## Commands

Run from a checkout with the application's ordinary dependencies. Each command
accepts `--repo` before or after its subcommand. The shell variables below are
operator-supplied paths and independently recorded SHA anchors; they must not
be filled from an untrusted receipt's success flag.

```sh
python experiments/issue61_joint_contract/replay_numerical_contract.py \
  --repo . legacy-compatibility \
  --saved-plan "$TASK_FROZEN_PLAN" \
  --replayed-plan "$TASK_FROZEN_REPLAY" \
  --strict-failure "$TASK_ORIGINAL_STRICT_FAILURE" \
  --expected-producer-sha256 "$TASK_FROZEN_PRODUCER_SHA" \
  --output "$TASK_LEGACY_OUTPUT"

python experiments/issue61_joint_contract/replay_numerical_contract.py \
  --repo . inspect-candidates \
  --plan "$TASK_PLAN" --expected-plan-sha256 "$TASK_PLAN_SHA" \
  --output "$TASK_DIAGNOSTIC_OUTPUT"

python experiments/issue61_joint_contract/replay_numerical_contract.py \
  --repo . generate-plan \
  --prior-plan "$TASK_PRIOR_PLAN" \
  --input "$TASK_ORIGINAL_RASTER" --expected-source-sha256 "$TASK_SOURCE_SHA" \
  --output "$TASK_NEW_PLAN"

python experiments/issue61_joint_contract/replay_numerical_contract.py \
  --repo . verify-plan \
  --plan "$TASK_ACTUAL_STAGE_PLAN" --expected-plan-sha256 "$TASK_STAGE_PLAN_SHA" \
  --input "$TASK_ORIGINAL_RASTER" --expected-source-sha256 "$TASK_SOURCE_SHA" \
  --execution-request "$TASK_ACTUAL_WORKER_REQUEST" \
  --output "$TASK_COLD_REPORT"
```

The normal joint acceptance path uses the actual new ordinary stage plan in the
last command. `generate-plan` is a source-only diagnostic operation and does
not substitute for that ordinary output. A fresh operating-system process
must execute `verify-plan`; its implementation always passes
`source_graph=None`.

## Exact output binding

`--output OUT.json` creates `OUT.json` and `OUT.json.execution.json`. Exit status
is 0 for a successful operation and 1 for a rejected or unresolved operation.
Required-input errors, explicit SHA mismatches, missing referenced candidates
and wrong producer identities return machine-readable failure evidence.

`OUT.json` for successful `verify-plan` is the original production return
value. It has no wrapper `status` field:

```json
{
  "pass": true,
  "reason": "ATTACHED_GRAPH_JOINT_V3_SOURCE_REPLAY",
  "source_graph_rebuilt_from_original": true,
  "saved_plan_sha256": "<canonical digest of the exact checked plan>",
  "numerical_comparison": {
    "pass": true,
    "reason": "PASS_NARROW_NUMERICAL_CONTRACT"
  }
}
```

Additional fields retain the replayed finite paths and full comparison. The
execution file uses schema `joint-numeric-execution-v3` and these exact keys:

| Key | Meaning and required comparison |
| --- | --- |
| `command` | Must be `verify-plan` for a cold verification claim |
| `status` | `PASS_JOINT_V3_SOURCE_PLAN_REPLAY` on successful production replay |
| `pass` | Boolean execution result; insufficient on its own |
| `plan_schema` / `input_plan_schema` | Actual input schema, unchanged by the CLI |
| `checked_plan_file_sha256` | SHA-256 of the actual stage plan file bytes |
| `checked_plan_canonical_sha256` | The production plan's canonical JSON digest; must equal the referenced report's `saved_plan_sha256` |
| `expected_source_sha256` / `actual_source_sha256` | Explicit anchor and independently computed original raster file SHA |
| `roi_xyxy_px` | ROI recorded by the checked plan |
| `source_graph_argument` | `null` only after the source invocation is reached; preflight failures record `NOT_RUN` |
| `independently_rebuilt` | True only when the original production result reports completed original-source reconstruction |
| `current_joint_producer_sha256` | Exact file names and hashes for graph, ink, contacts and numeric modules |
| `algorithm_identity` / `algorithm_identity_after` | The ordinary program's algorithm fingerprint before and after execution |
| `algorithm_identity_unchanged` | Equality of the complete fingerprint SHA before and after execution |
| `execution_request_binding` | If supplied: actual request path, file SHA, algorithm/source/ROI checks and their aggregate result |
| `input_sha256_before` / `input_sha256_after` | Exact input and source-module files watched by the invocation |
| `original_inputs_and_source_modules_unchanged` | Inputs and watched producer bytes did not change during execution |
| `output_path` / `output_sha256` | Absolute path and exact file SHA of the referenced unwrapped production result |
| `checkout` / `process_pid` / `wall_seconds` | Actual checkout state, process and elapsed execution details |

The algorithm identity includes the broader ordinary implementation; it is
different from a graph producer SHA. When a worker request is supplied, the CLI
requires its algorithm/source/ROI binding and fails if the complete algorithm
changes during the cold run. The common interface additionally binds the
worker's full source frame, saved DXF and publication to the actual stage plan.
The numerical CLI makes no independent DXF, drawing-unit or saved-object claim.

## Narrow arithmetic and invalid scopes

The original #60 reference arithmetic and explicit diagnostic grammar remain
bounded to source-chord angles, finite contact fractions, core axis points and
residual diagnostics. The actual historical discrepancy consists of 87
derived values: 61 angles, 7 fractions, 13 point coordinates and 6 residuals.
All other plan values remain strict, including original pixels, thresholds,
native coordinates, endpoint IDs, decisions, ownership and new raw-ink model
fields. The reference arithmetic is a declared finite calculation model; it
does not claim a universal error bound for every math-library implementation.

Every component receives a separate diagnostic scope. Missing candidate
geometry or referenced finite paths, inconsistent adoption declarations,
duplicate IDs and changed producer contracts are explicit failures. A valid
numerically pending component has no formal paths and retains a strictly
replayed failure subtree without any newly granted numerical whitelist. An
empty component records `NOT_APPLICABLE_NO_DIAGNOSTIC_INPUT`.

The shared saved-file acceptance must resolve `output_path`, validate its
`output_sha256`, inspect the production result, compare exact plan file and
canonical identities to the ordinary stage, compare all producer and worker
identities, and independently audit the saved DXF. Reading a `PASS` string is
not that validation.
