# Issue 61: stable source continuation and joint acceptance

This branch starts at the published Issue 59 result `28718414afa5b1660c400716be5331d631a42104`, with effective main fixed at `a2aec1596e82b3a92c7b76f89e9e46e068029e90`. It integrates the limited numerical contract and independent saved-file audit from Issue 60 without relabelling either historical v2 schema as a joint execution.

The issue authorizes an independent experimental result. The coordinator will integrate this branch with Issue 62 before final main, CAD GUI, Windows EXE and application delivery. This branch does not change the original 20-degree direction gate or 18-degree competition margin, and does not change the Issue 59 ink or contact producers.

## Contracts and responsibility

- [Frozen numerical interface](NUMERICAL_INTERFACE_FROZEN.md): unique joint v3 plan, adoption, native and certificate identities; adopted paths and complete diagnostic candidates stay separate.
- [Source-stage continuation contract](../../docs/native/SOURCE_STAGE_CHECKPOINT_CONTRACT_20261127.md): complete finite upstream state, source identity, producer closure, dependencies and explicit invalidation.
- [Complete source-proof continuation contract](../../docs/native/SOURCE_PROOF_CONTINUATION_CONTRACT_20261127.md): the v2 checkpoint also binds the complete historical saved-source proof, independently verifies current native content and source samples, and preserves the fresh legacy cold result.
- [First ordinary failure](../../docs/native/ISSUE61_FIRST_ORDINARY_FAILURE_20261127.md): the actual v1 run preserved all old objects but failed its fresh source-publication gate. Its output, original failure and execution identity remain separate from subsequent runs.
- `app/native_objects/independent_stage_binding.py`: validates declared stage scope against the actual plan, adoption, worker request, publication and saved sidecar. A declaration selects what to check; it is not proof of source ownership.
- `app/native_objects/independent_saved_geometry_audit.py`: compares complete old objects, including recursive named block contents, and records full-file additions, losses, changed objects and resources separately.
- `experiments/issue60_common_acceptance/run_common_acceptance.py`: the shared, layered machine-readable entry. The directory name retains the imported tool's provenance; the current common report identifies joint v3.

## Ordinary continuation entry

Prepare a source checkpoint from an independently verified completed source run, using its original source, complete evidence, worker request, producer snapshot and recorded environment/resources:

```bash
PYTHONPATH=cad_photo_to_dxf python -m app.native_objects.source_stage_checkpoint create \
  --evidence VERIFIED_OLD_EVIDENCE \
  --request VERIFIED_OLD_REQUEST \
  --previous-source VERIFIED_OLD_APP_SOURCE \
  --environment VERIFIED_OLD_ENVIRONMENT \
  --resources VERIFIED_OLD_RESOURCES \
  --historical-export VERIFIED_OLD_EXPORT_MANIFEST \
  --source ORIGINAL_SCAN \
  --output NEW_CHECKPOINT_DIRECTORY
```

The v2 builder restores the source state after complete short-contact text and before attached-stroke discovery. It also reads the historical saved DXF solely to audit its complete native content and proof provenance; no old DXF entity supplies new geometry. It removes only the old attached stage's declared additions after checking their complete source bindings. It does not choose a checkpoint by a case coordinate, expected object ID, expected count or target answer. The original v1 implementation and failed run retain their literal no-DXF-read identity and are not upgraded in place.

Pass the resulting manifest through the normal application task manager:

```bash
python cad_photo_to_dxf/main.py --headless --mode native-objects \
  --input ORIGINAL_SCAN --roi X0 Y0 X1 Y1 --dpi INPUT_DPI \
  --jobs-dir NEW_JOB_DIRECTORY --job-id NEW_JOB_ID \
  --output NEW_OUTPUT.dxf \
  --source-stage-checkpoint NEW_CHECKPOINT_DIRECTORY/manifest.json
```

The actual worker request and published continuation receipt explicitly identify `SOURCE_STAGE_CHECKPOINT_CONTINUATION`. New source-graph discovery, attached ink, all-prior-object contacts, joint numerical checks, DXF save, fresh source cold audit, complete source-proof continuation, render and current quality review still run. Independent old-content acceptance is a separate external check and is not falsely reported as having run inside the producer.

V2 saved-source acceptance explicitly uses `SOURCE_CHECKPOINT_PROOF_CONTINUATION`. It checks the complete historical individual source proofs and their closed provenance, all current recursive native content and resources, current original-pixel measurements, every repeated segment and its actual source responsibility, and the new attached stage. The untouched `cold_audit.json` keeps its actual fresh result, including failures. A separate `source_proof_continuation_audit.json` records the effective gate. Worker publication, committed-result recovery and export revalidate that gate against current bytes; an isolated historical or current PASS boolean is insufficient. A v1 manifest cannot select this mode.

Source bytes and decoded pixels, ROI/DPI/page/frame/orientation/units, finite source geometry and responsibility, endpoints/intervals, raw assets, relevant old producer files and original upstream pipeline AST must agree. Current continuation executor files and dependency code bytes are bound from checkpoint creation through capture and execution. Historical CPU/BLAS binary identity was not recorded and is not inferred.

The original uncached entry remains available. Its known old-baseline geometry/ID drift is not fixed by this explicit continuation mechanism and must not be relabelled as an exact uncached reconstruction.

## Independent cold replay and common saved acceptance

Use the actual plan saved by the new ordinary execution, never an independently generated replacement plan:

```bash
python experiments/issue61_joint_contract/replay_numerical_contract.py verify-plan \
  --input ORIGINAL_SCAN --expected-source-sha256 VERIFIED_SOURCE_SHA256 \
  --plan NEW_OUTPUT.native/evidence/attached_strokes/plan.json \
  --expected-plan-sha256 ACTUAL_SAVED_PLAN_SHA256 \
  --execution-request ACTUAL_WORKER_REQUEST \
  --output NEW_COLD_REPLAY.json
```

This starts an independent reconstruction from original pixels with `source_graph=None`. Its result and execution receipt bind the exact source, actual plan bytes and canonical digest, producers and worker algorithm. A numeric PASS cannot authorize a candidate or excuse changed native geometry.

```bash
PYTHONPATH=cad_photo_to_dxf python experiments/issue60_common_acceptance/run_common_acceptance.py \
  --source ORIGINAL_SCAN --baseline VALID_OLD_BASELINE.dxf \
  --dxf NEW_OUTPUT.dxf --metadata NEW_OUTPUT.objects.json \
  --source-roi X0 Y0 X1 Y1 --audit-roi AX0 AY0 AX1 AY1 --dpi INPUT_DPI \
  --execution-request ACTUAL_WORKER_REQUEST \
  --numerical-replay-receipt NEW_COLD_REPLAY.json.execution.json \
  --out NEW_ACCEPTANCE_DIRECTORY
```

The saved stage plan/adoption/publication are discovered beside the actual output or supplied explicitly. Optional `--source-stage-manifest` and `--source-stage-continuation` map relocated evidence without relaxing its recorded SHA binding. The audit ROI is only an independent evidence scope, not a production adoption rule.

`NOT_RUN` for missing stage evidence, `NOT_APPLICABLE_ZERO_ADOPTED` for target editing, `SOURCE_UNRESOLVED` for retained candidates and a complete PASS are distinct. A zero-target stage does not hide unexpected entities. The original Issue 59 failed file must continue to fail complete old-object protection, while historical A440 may pass saved protection without proving full raw source responsibility. Historical edit passes are never inherited by a new drawing.

## Evidence and publication

Private source scans, OCR, fonts/models, source coordinates and drawings are not committed. The result report records execution/publication commit identities, source/output/package hashes, actual failures and the local recovery commands. Test counts, matching renders or CI alone do not establish completion. The final acceptance result is added only after the real ordinary output and its independent cold checks exist.
