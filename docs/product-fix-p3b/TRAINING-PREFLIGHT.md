# P3B final data freeze and Colab training pre-flight

The final human re-review and exact current truth were recovered and verified.
The data/input-contract freeze passes. Infrastructure pre-flight stops at the
official Colab MCP client compatibility requirement. No labeling, real training,
Colab cell, Drive mount or checkpoint smoke test was launched.

```text
VALIDATION_REREVIEW_RECOVERED: YES
TOTAL_REVIEWED: 8
EXACT_AGREEMENT: 6
CHANGED_DECISIONS: 2
VALIDATION_REREVIEW_AGREEMENT: 6/8
CURRENT_VALIDATION_TRUTH_FROZEN: YES
ORIGINAL_HISTORICAL_ANSWERS_PRESERVED: YES
TRAINING_DATA_FREEZE: PASS
TRAIN_VALIDATION_LEAKAGE: NONE
BLIND_TOUCHED: NO
FIRST_MODEL_CLASS_POLICY: 3_CLASS_PLUS_ABSTENTION
AMBIGUOUS_TRAIN_SAMPLES_USED_AS_HARD_LABELS: 0
AMBIGUOUS_VALIDATION_ROLE: ABSTENTION_EVALUATION
COLAB_MCP_INSTALLED: YES
MCP_CLIENT_COMPATIBLE: NO
MCP_SERVER_INITIALIZATION: PASS
GOOGLE_LOGIN_COMPLETED: USER_ACTION_REQUIRED
COLAB_SESSION_CONNECTED: NO
COLAB_BROWSER_SESSION_CONNECTED: NO
CELL_EXECUTION_PASS: NOT_RUN
DRIVE_MOUNT: NOT_RUN
CHECKPOINT_WRITE: NOT_RUN
CHECKPOINT_READBACK: NOT_RUN
RESUME: NOT_RUN
IDENTITY_GUARDS: NOT_RUN
LOGISTIC_BASELINE_READY: NO
CNN_TRAINED: NO
MODEL_TRAINED: NO
PRODUCTION_CODE_CHANGED: NO
BACKGROUND_TASKS_CREATED: NO
NEXT_STEP: resolve official MCP dynamic-tool client compatibility
STOP
```

`IDENTITY_GUARDS: NOT_RUN` refers to the requested remote checkpoint-resume
identity test. Local data/split/state/normalization identity checks passed.
`LOGISTIC_BASELINE_READY: NO` means an end-to-end runtime and executable baseline
are not yet ready; the exact input, class policy and benchmark configuration are
prepared. Existing historical four-class runners were not used or trained.

## Recovered validation adjudication

The complete saved state is schema-valid and history/undo replay agrees with
`VALIDATION-SUSPECT-REVIEW-FINAL.json`. Its comparison and current adjudicated
50-record view match both historical answer sets and the immutable snapshots.
The original 50-sample state, original 100-sample state and both independent
re-review states were not changed. No UI was reopened and no finalizer rerun.

| Rank | Sample ID | Original answer | Re-review/current answer | Review reason |
|---:|---|---|---|---|
| 17 | val-v2-0ef668e8d4a1ddc737649a25 | V / AMBIGUOUS | V / TRUE_PARALLEL_STRUCTURE | HUMAN_AMBIGUOUS_VALID_LABEL: confirm or retain 4 with context; uncertainty is valid and no class is forced |
| 33 | val-v2-19fa87d80bb54ff6794f6a51 | V / AMBIGUOUS | V / TRUE_PARALLEL_STRUCTURE | HUMAN_AMBIGUOUS_VALID_LABEL: confirm or retain 4 with context; uncertainty is valid and no class is forced |

Both changed decisions were explicitly adjudicated under the user's authorized
rule. Rank 6 remains V/AMBIGUOUS. These are human judgments with preserved
provenance, not a claim of infallible semantic truth.

## Exact final data freeze

The **one final pre-flight manifest** is
`FINAL-TRAINING-DATA-FREEZE.json`. The earlier `TRAINING-DATA-FREEZE.json` and its
bound completion report remain immutable historical artifacts; the final
manifest references their exact hashes instead of rewriting them or copying
the whole dataset. It references the existing current-truth snapshots.

| Population | Samples included | Single | True parallel | Other | Ambiguous | Excluded | Drawings | Source families |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TRAIN | 94 | 38 | 20 | 36 | 0 | 6 | 13 | 12 |
| VALIDATION | 50 | 22 | 20 | 7 | 1 | 0 | 5 | 5 |

```text
TRAIN_SAMPLE_COUNT: 94
TRAIN_SINGLE: 38
TRAIN_TRUE_PARALLEL: 20
TRAIN_OTHER: 36
TRAIN_AMBIGUOUS: 0
TRAIN_EXCLUDED: 6
VALIDATION_SAMPLE_COUNT: 50
VALIDATION_SINGLE: 22
VALIDATION_TRUE_PARALLEL: 20
VALIDATION_OTHER: 7
VALIDATION_AMBIGUOUS: 1
VALIDATION_EXCLUDED: 0
TRAIN_DRAWINGS: 13
TRAIN_SOURCE_FAMILIES: 12
VALIDATION_DRAWINGS: 5
VALIDATION_SOURCE_FAMILIES: 5
```

94 train samples qualify for three-class supervision. 49 validation samples
qualify for ordinary classification metrics; the remaining one qualifies for
separate abstention evaluation and remains part of the 50-sample frozen truth.
The six excluded train nominations remain identified in the manifest with
their X/U reasons; they are not training targets.

| Included population | Effective 110 DPI | Effective 240 DPI | Unknown physical DPI |
|---|---:|---:|---:|
| Train | 78 | 4 | 12 |
| Validation | 37 | 0 | 13 |
| Combined | 115 | 4 | 25 |

Known PDF/render DPI is not asserted to be scan acquisition DPI. Unknown native
scan/photo DPI is not invented. This validation set does not establish broad
known multi-DPI robustness. Whole drawing/family splits are unchanged. Sample
ID, drawing, source family, source SHA and exact crop intersections are empty.
No blind file was opened, rendered, hashed, staged or uploaded.

Final manifest SHA256:
`4a4faa39a2a56811f6723fa0ccfa2322320080023c59c35a2179f40f08942795`.

The final manifest binds all train/validation and re-review manifest hashes,
all original/re-review label-state hashes, adjudication hashes, the split hash,
current snapshots, included/excluded sample IDs, family/drawing identities,
effective DPI, input assets, provenance and normalization/configuration hashes.

## Human reliability and AMBIGUOUS policy

`final-human-reliability-provenance.jsonl` contains derived metadata for all 150
original nominations; it never rewrites human answers. Primary provenance is
129 DIRECT_HUMAN, 18 CONFIRMED_BY_REREVIEW and 3 ADJUDICATED_CHANGED. The latter
includes the previously changed/excluded train rank 40 and validation ranks 17
and 33. Additional tags identify five EXCLUDED_BAD_NOMINATION X records and one
HUMAN_AMBIGUOUS record. The U record remains excluded with UNCLEAR_TARGET, not
misrepresented as a bad nomination. No numeric probability of human correctness
is invented or used as a training weight.

The first model is **SINGLE / TRUE_PARALLEL / OTHER plus abstention**. Human
AMBIGUOUS truth is retained as ABSTENTION_EVALUATION, never assigned to those
three classes or used as a hard fourth-class training label. A future abstention
policy may use calibrated low confidence, model disagreement, unsupported/OOD
input or deterministic geometry conflict. Confidence alone does not guarantee
recognition of human uncertainty. One ambiguous validation case is insufficient
to establish robust abstention performance; report it as one observed case.

No calibrated fourth probability may be fabricated from a three-class model.
Future geometry behavior for abstention is no automatic change, and deterministic
P3A safety vetoes remain authoritative. There is no production integration here.

## Frozen v1 input and benchmark preparation

`model-input-v1-frozen.json` freezes the existing implementation without changing
feature definitions or preprocessing:

- Image: float32 **3 × 256 × 256**, in order darkness `1-gray/255`, candidate
  edges `/255`, nominal candidate centerline `/255`.
- Native pixels and existing white padding; no resize, deskew, autocontrast,
  whole-page input or added protection/node/context channels.
- 18 float32 raw features in the exact existing `features.py` order:
  separation_256, angle_delta_180, overlap_256, dpi_600, dpi_known, mean_gray,
  std_gray, dark_fraction, gradient_x, gradient_y, width_px_16, width_known,
  stable_fraction, dark_core_fraction, center_offset_16, profile_samples_19,
  contrast_separated_fraction, pair_present.
- Existing zero defaults and DPI/width availability indicators retained.
  Missing source profiles and zero protection masks are not evidence of safety.
- Training-only StandardScaler population statistics (ddof=0), fitted on the
  exact 94 supervised train IDs. Constant columns use scale 1. The saved mean,
  variance and scale are bound to the contract; validation never fits scaling.
  Any future neural feature input must retain float32 after standardization.
- Seed **314159**, RNG-state persistence, fixed whole drawing/family splits and
  dataset version `p3b-final-three-class-abstention-v1`.

All 144 included samples passed crop SHA, image shape/type/range and finite
18-feature checks. No concrete integrity defect required a contract change.
Raw train statistics were computed; no classifier, optimizer or neural model
was fitted.

`first-baseline-configuration.json` defines the later 18-feature standardized
Logistic Regression benchmark (balanced class weighting, C=1, max_iter=1000,
seed 314159) and the requested metrics: per-class precision/recall, confusion
matrix, balanced accuracy, macro F1, SINGLE action coverage, abstention coverage
and selective accuracy at fixed reporting thresholds.

FALSE_MERGE_RATE is truth TRUE_PARALLEL predicted SINGLE divided by **all**
truth TRUE_PARALLEL, including the denominator under abstention. Report family,
drawing, DPI, target-kind and ambiguous-case behavior separately. Do not tune on
blind data or select confidence thresholds to fit these re-review answers.
The two PAIR/SINGLE validation cases and small sample counts constrain any safety
claim. Historical `classical.py`, `benchmark.py` and `train_small.py` still target
the earlier four-class research contract and must not be used as if they already
implement this finalized three-class benchmark.

No CNN was trained or installed. The only future candidate remains Conv16/32/64,
global pooling, 18-feature fusion, a 64-unit head and three logits, conditional
on a later decision after the classical benchmark. No foundation model.

## Official Colab MCP installation and compatibility stop

Only [googlecolab/colab-mcp](https://github.com/googlecolab/colab-mcp) was installed:
package 1.0.1, official commit
`b9ab3899e0f1fa493390b1fd6d54aa2e464ecdf1`. The unmodified source checkout, isolated
Python 3.13.16 environment, dependencies, logs and installation evidence are
outside the project at `C:/Users/agcrf/.codex/mcp-envs/colab-mcp`. The project
Python environment was not modified. sklearn and PyTorch were not installed.

The entry was added to user-level `C:/Users/agcrf/.codex/config.toml` using the
[documented STDIO configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
Unrelated configuration was preserved. It is **disabled** pending compatibility,
so it cannot automatically start an unusable server. Its executable is the
official package's console entry point, with logs outside the repository.

A single bounded foreground MCP protocol test passed initialization and tools
discovery (protocol 2025-11-25). The server advertises listChanged=true and
initially exposes only `open_colab_browser_connection`. That tool was not called;
no Google authorization or browser/session connection was attempted. The test
server exited, and no Colab MCP process was left running.

**Concrete compatibility blocker:** the official upstream requires a local
client that handles `notifications/tools/list_changed` by refreshing its tool
inventory after the browser connection. In the matching installed Codex 0.160.1
[notification handler](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/rmcp-client/src/logging_client_handler.rs),
the tool-list change is only logged; the
[legacy catalog path](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/codex-mcp/src/rmcp_client.rs)
serves its stored catalog. The official
[Colab proxy](https://github.com/googlecolab/colab-mcp/blob/b9ab3899e0f1fa493390b1fd6d54aa2e464ecdf1/src/colab_mcp/session.py)
injects notebook tools after browser connectivity and sends the tool-list change.

The client compatibility decision is **source-based**, not a claim that a live
Colab notebook failed. This active client has no Colab tools available. Static
STDIO initialization alone is insufficient to certify the required dynamic
tool refresh and cell execution. No official Colab plugin was returned by the
available plugin search; no community fork or alternate client was substituted.
The requested stop at phase 6 is therefore honored.

Machine-readable setup/handshake/source evidence is in
`colab-mcp-preflight.json`. Public matching-version source snapshots and full
dependency version inventory remain in the user-level installation directory,
not copied into the active checkout. No Google password, cookie, OAuth token or
Drive secret was stored in the repository.

## Deferred Drive and resume stages

Because client compatibility is blocked, Drive mount, checkpoint write/readback,
interrupted-process resume, remote checkpoint identity rejection and real
Logistic Regression execution are **NOT_RUN**. No uploaded data or Drive folders
were created. No local checkpoint surrogate is reported as a remote PASS.

After a separately resolved compatible local client/build is verified, the
already prepared plan uses normal Colab Drive mount and a dedicated
`MyDrive/Image-to-CAD-ML/` workspace with manifests, labels, checkpoints, metrics,
runs and active-learning. Approved train/validation only stage into
`/content/p3b`; Drive remains durable storage, not the hot training filesystem.
Do not add a Drive MCP or upload blind data.

The future tiny disposable resume test must bind model/optimizer state, completed
epoch, dataset/label versions, split manifest, configuration, feature scaler,
random seed/RNG state and metric history, and reject altered identities. This
contract is prepared in the baseline configuration but the smoke test did not
run. Retain only latest, best and at most two explicit milestone checkpoints;
no indefinite periodic checkpoint accumulation or permanently alive cloud VM.

Git/project storage contains only compact manifests, schemas/contracts, human
truth/provenance, configuration, hashes, reports and reproduction scripts.
Existing raster caches stay outside the checkout and are regenerable from the
bound source/nomination contract. Installation/download caches are user-level,
regenerable and can be discarded after a verified installation when needed;
the environment/source/evidence are kept for this pre-flight. No duplicated
full datasets, new checkpoint arrays, timers, watchers, polling loops, recurring
tasks or background monitors were created.

All 157 production app/test file hashes match the retained snapshot. P1/P2B/P3A,
production geometry, DXF and OCR behavior were not modified or rerun.

**NEXT_STEP:** resolve the official MCP dynamic-tool client compatibility
requirement, then perform interactive login and the outstanding infrastructure
smoke tests in a separate resumed foreground pre-flight. Do not run the real
baseline until those checks pass. STOP.
