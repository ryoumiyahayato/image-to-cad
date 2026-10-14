# IMAGE TO CAD — PRODUCT FIX P3B

**2026-10-07 update:** V2 nomination/UI acceptance **PASS**, 29/30 valid targets (96.67%). A separate 100-target formal seed queue is prepared but **not launched**; no training is authorized. See [V2-ACCEPTANCE-RESULT.md](V2-ACCEPTANCE-RESULT.md) for the final saved-state audit and proposed next batch. The preparation report below is historical.

**Labeling workflow superseded after pilot:** V1's 145 saved labels are `PILOT_V1_UNVERIFIED`, with **zero training authorization**. Do not continue the 769-sample V1 labeling run. See [PILOT-AUDIT.md](PILOT-AUDIT.md) and [LABELING-CONTRACT-V2.md](LABELING-CONTRACT-V2.md). The launcher now opens only the 30-sample, two-stage V2 acceptance review. The original preparation inventory/results below remain historical evidence, not a validated training seed.

2026-10-06, Asia/Taipei. Dataset and benchmark preparation only. P3A remains the closed deterministic baseline. This work stops before model training and production integration.

```text
REAL_DRAWINGS_FOUND: 33 registered source groups; 18 available nonblind drawings; 13 development drawings extracted
PROPOSED_SPLIT: 18 train / 7 validation / 8 blind groups; established source-family boundaries retained
REAL_PATCH_CANDIDATES: 769 from 13 development drawings / 17 pages; all real labels null
SYNTHETIC_GENERATOR: READY
LABEL_SCHEMA: p3b-v1; four classes plus null for not yet labeled
LABEL_UI: READY
BASELINE_DEFINED: YES
PRIMARY_SAFETY_METRIC: FALSE_MERGE_RATE
MODEL_INPUT_PROPOSAL: 3 x 256 x 256 local raster channels + 18 compact features
ACTIVE_LEARNING_PLAN: entropy + class/source diversity + exact/perceptual/spatial duplicate suppression
COLAB_RESUME_PLAN: local scratch; atomic epoch checkpoints; optional periodic durable sync
PRODUCTION_CODE_CHANGED: NO
P1/P2B/P3A_REGRESSIONS: NOT_APPLICABLE / unchanged (before/after SHA256 verified)
READY_TO_BEGIN_HUMAN_LABELING: NO for V1; only 30-sample V2 UI acceptance is prepared
BLOCKERS: none for seed labeling; real metrics/training need human labels and held-out validation candidates
NEXT_STEP: human seed labeling
STOP: no production model trained; no DXF output altered; no OCR work
```

## Evidence inventory

[inventory.json](inventory.json) identifies canonical paths, source hashes, origins, availability, source families, existing CAD references, retained observation sidecars and raster aliases. [split-manifest.json](split-manifest.json) pins the earlier authoritative corpus split. Blind metadata comes only from the existing registry/acquisition manifest: no blind source file was opened, hashed, rendered, OCRed, mined or labeled. Validation files were checked for existence; their contents were also left unopened in this preparation pass.

| Inventory field | Observed evidence |
| --- | --- |
| DRAWINGS_AVAILABLE | 18 nonblind source groups: 13 train, 5 validation. Two validation and five train registry groups are unmaterialized. Eight blind groups are recorded-only. |
| SOURCE_FORMATS | 15 available PDFs, 2 original JPEG/JPG files, 1 original TIFF. Three retained native DXF conversion packages are supplementary CAD references, not three additional independent drawings. Original DWG provenance is in the conversion audit. |
| PAGE_COUNT | 722 available nonblind pages: 576 train, 146 validation. Blind registry records 130 additional pages; that count was not reverified by reading blind PDFs. |
| RASTER_COUNT | 3 original available raster files; 10 UAT/P1/P2B/P3A source-raster paths represent 6 unique rasters. Thus 9 unique original/derived raster images in the explicit inventory scope. CAD previews/screenshots and repeated DPI renders do not increase independent drawing counts. |
| VECTOR_GROUND_TRUTH_AVAILABLE | Warehouse vector PDF and three native CAD conversions exist. Their raster-to-entity/stroke correspondence is **not qualified real ground truth**. Production DXF is an output reference, never a correct label by assumption. Synthetic truth is explicit physical CAD primitive metadata. |
| POTENTIAL_POSITIVE_PATCHES | 239 pair + 225 single-rule + 3 retained W03 rule ROI nominations = 467 potential target patches. These can also be true-parallel negatives, OTHER or AMBIGUOUS after review. Qualified real positives: 0 pending humans. |
| POTENTIAL_NEGATIVE_PATCHES | 264 untyped ink + 32 retained text + 6 source-owned graphic controls = 302 potential OTHER/hard-negative controls, plus any of the 467 target nominations humans identify as true-parallel. Qualified real negatives: 0 pending humans. |

The inventory covers P1/P2B real pages E01/E03/E04/W01/W02/W03 through their two original PDFs and retained source rasters; P3A W03 through its 110-DPI source, source-unit native DXF, acceptance record and stroke replay; ten materialized historical/current DEV corpus sources; the retained perspective regression photo; and the storage-cleanup source-to-history mapping. Older D8/D9 continuation/glyph labels address a different target and are **not imported** as P3B labels. Synthetic historical auxiliary/hatch fixtures and CAD screenshots are not counted as real drawings.

| Requested family | Candidate evidence and qualification boundary |
| --- | --- |
| Single thin rules | W03 thin-table ROI; native rules on warehouse sheets and historical source plans. A measured width alone does not supply a label. |
| Single thick rules | W03 thick-frame ROI retains two native edges; P3A source measurement and isolated thick-stroke control. Human source review still determines real truth. |
| True double walls | W03 P1 wall rails and true-double-wall ROI. |
| Shafts/enclosures | W03 source enclosure context and P1/P3A preservation controls; additional real nominations need human confirmation. |
| Table/frame rules | Warehouse title frames, tables and W03 border; public corpus schedules may contain more but are not declared labeled. |
| Door openings | W03 double-wall source/context view and P1 fixture. |
| Junction-connected parallels | W03 native endpoint map and enclosure/table context; topology records are incomplete outside captured native geometry. |
| Filled regions/hatching | W03 grey column fills/hatching recorded as unresolved in P3A; scan/corpus ink nominations are available but not semantically certified. |
| Text strokes | Retained text observation boxes nominate OTHER controls. Text controls cannot be assigned either structural class by the UI/validator. |
| Graphic-object strokes | W03 native IMAGE placements locate north arrow, logo and signature source crops. These stay OTHER/AMBIGUOUS controls. P2B E01/W02 object evidence remains referenced. |
| Scan noise/artifacts | A2-SG-009 damaged archival scan and the environment scan; untyped connected-ink nominations need human review. |

Representative crops and candidate overlays are in [representative-samples.png](representative-samples.png). They are review aids, not preassigned labels. The right column is bounded expanded context. The native y mapping was checked against the exporter: `source_y = image_height - CAD_y`.

## Proposed whole-drawing split

Every page, crop, DPI render, augmentation and related source sheet stays with its drawing and source family. The two user engineering PDFs and retained CAD packages are conservatively grouped into one train origin, `user-project-haiyang`; they are not independent train/validation evidence. The photo is a separate train origin. Existing corpus allocations remain authoritative; none of the already examined DEV sources becomes a claimed blind test.

TRAIN_DRAWINGS (18 registered, 13 available):

```text
A2-SG-009, A2-SG-010, A2-SG-022,
G0R2-15EE2398726E8037, G0R2-3560D9BEBEAA3543,
G0R2-3B970FD759C6026F, G0R2-4A34D1B8D93B1B06,
G0R2-53C88494D6CE893C, G0R2-6C9464FA73A2A027,
G0R2-7E30C7F445081F40, G0R2-AFE53C2A00EB7D8F,
G0R2-B441E5911528F402, G0R2-C2D095E069663C17, SGC-008, SGC-024,
warehouse-electrical (all 7 sheets), environment-building (all 14 sheets), sample-plan-photo
```

VALIDATION_DRAWINGS (7 registered, 5 available, unopened here):

```text
A2-SG-008, G0R2-22E85E2DB7746A00, G0R2-2E9BDFFDD8C89AE7,
G0R2-4DC97797ABE2CB18, G0R2-99D5B85436EBB965,
G0R2-F519B357241CAC3A, SGC-007
```

BLIND_TEST_DRAWINGS (8; registry metadata only):

```text
G0R2-12366099AAD5F10E, G0R2-2279F661AA38A9F4,
G0R2-345AA483FD068A11, G0R2-420BF9693D881A41,
G0R2-4CF3C6EBEFDD1EBE, G0R2-5FB6FE7CB6D476E1,
G0R2-6DFEC5FDC69FC0CD, G0R2-AEA044C8E75CB3AB
```

All preparation development entry points reject or omit blind data. The extractor currently materializes train only. A subsequent validation preparation pass must use the frozen extraction/labeling policy, not select cases based on model errors. Freeze development, calibration, thresholds, checkpoint and benchmark manifest before a separately authorized single blind evaluation. Blind class coverage is unknown; a source-group registry does not guarantee enough true-parallel examples for a safety claim. Synthetic CAD designs are separately partitioned by truth ID before degradation; variants of one design never cross splits, and synthetic data never belongs to real blind test.

## Label rubric and provenance

The target is the highlighted candidate, not everything inside its crop. Without an overlay, review the central nominated ink; skip or expand context when that target is unclear.

| Label | Exact rule |
| --- | --- |
| SINGLE_PHYSICAL_STROKE | One intended document/CAD structural or rule stroke. Two raster boundaries or a continuous filled narrow run describe that one stroke. Thin/thick rules and table/frame members can qualify. Two already separate source entities do not become one merely because they are close. |
| TRUE_PARALLEL_STRUCTURE | Two distinct source-supported geometric boundaries intended to remain separate editable entities, such as walls, shafts, enclosures or separate frame rails. Continuation, separate source runs, opening and structural context may establish distinct identity. |
| OTHER | The nominated content is not meaningfully either target: broad fill, hatch elements, glyph/text, graphic-object strokes, artifact or noise. Text glyphs are never structural-line positives, even when straight or parallel. |
| AMBIGUOUS | A human cannot reliably determine stroke identity from the available source and bounded context, including damaged, clipped, overlapping or conflicting evidence. This is a valid human class, not the same thing as model abstention. |

`null` means unlabeled; it is never automatically AMBIGUOUS. P3A rejects, protection flags, lineweights, candidate spacing, source vector status and older labels cannot assign real ground truth. Real labels come from source review and retain reviewer, UTC timestamp, sample digest, rubric version and label revision. Optional future adjudication should double-label every potentially actionable SINGLE case and every disagreement; retain both opinions, mark unresolved disagreement AMBIGUOUS. Synthetic labels come only from primitive identity/role metadata. Severe degradation does not fabricate human AMBIGUOUS labels; synthetic truth may be visually unrecoverable and is evaluated separately.

The manifest contract is [sample.schema.json](sample.schema.json). Every sample retains the requested ID/drawing/page/bbox/geometry IDs/DPI/P3A measurement/decision/label/provenance/split/source SHA256. Additional fields distinguish offline nominations from native entity IDs, missing full protection, exact source patch hash and split version. Source SHA256 is the original real PDF/image hash, or the saved full synthetic scene PNG hash. A synthetic `truth_id` separately hashes CAD generation metadata. W03 retained raster bytes are checked against the frozen P3A raster digest. Uncalibrated photos/archive rasters have **null physical DPI**; PDF render DPI is known but is not a claimed scanner acquisition DPI.

## Bounded classifier input

First image experiment: `[3,256,256]` float32 plus 18 float32 features. Source-native square crops are 256 pixels; page-edge crops are clamped, smaller inputs are white-padded. No resizing, deskewing, per-patch autocontrast or orientation canonicalization is applied to real inputs in v1. Width and antialias information therefore remain in native pixels. Source bbox records the inverse mapping: `(patch_x,patch_y) -> (left+patch_x,top+patch_y)` for valid pixels. Synthetic transforms and mm-to-pixel scale are retained separately.

Channels are ink darkness `1-gray/255`, candidate edges `/255`, and a nominal pair centerline `/255`. The centerline is context only and never geometry authority. Five preparation channels are saved: the above plus protection and exact-node masks. The latter two are **excluded from the first model** because available real masks/topology are partial. Their zero values never mean “safe to merge.” Add them only in a future ablation with explicit availability indicators and a qualified extraction contract. Door/structural continuation context is shown as a separate source crop up to 512 pixels for humans; it is not a whole-page model input. A future context branch is conditional on an demonstrated failure of the smaller input.

[features.py](../../tools/p3b/features.py) fixes the 18 inputs: separation/256, angular difference/180, overlap/256, DPI/600, DPI-known bit, grayscale mean/std/dark fraction, mean x/y gradient, measured width/16, width-known bit, stable fraction, dark-core fraction, center offset/16, sampled count/19, separated-contrast fraction, and pair-present bit. Missing numeric measurements are zero plus their availability bit. Classical/NN runners fit a feature standardizer on training only. No IDs, filenames, page position, split, label, provenance, nomination family, deterministic decision or final geometry fate is a model feature. Synthetic primitive metadata supplies labels/context generation but is never an image-model feature vector.

## Extraction and synthetic preparation

[tools/p3b](../../tools/p3b) is separate offline tooling. No production module is edited. The real extractor uses loose label-blind LSD pair nomination (minimum segment 40 px, direction difference ≤3°, separation 0.5–60 px, overlap ≥40 px), single-rule controls and connected-ink controls. These are **dataset proposal limits**, not new P3A merge rules. Source SHA and full drawing split are bound before cropping. Per-page/type quota is 16 for this seed pool; stable content-hash order and 80-pixel center separation reduce repeated cases. Exact source-crop duplicates are suppressed across the pool; cross-split source/family/patch hashes are rejected. W03 uses actual native LINE/contour-edge handles, while other sources retain explicitly named `P3B-LSD-*` proposal IDs. The first corpus page per materialized DEV source and the six UAT pages are sampled; this is a seed, not exhaustive mining of 576 development pages.

Synthetic generator: 98 CAD designs (14 scene types × seven lineweights) and two independently seeded degradations each. Known primitives use millimetres and stable entity IDs. Scenes include isolated/parallel lines, T/cross junctions, corners, door openings, table intersections, frames, shafts/enclosures, fills, hatching, glyphs, graphics and noise. Junction/frame families contain single and true-parallel variants. Widths: 0.13, 0.18, 0.25, 0.35, 0.50, 0.70, 1.00 mm. True-parallel center spacing is independently varied above the line width. Rasterization uses 4× supersampling with BOX/LANCZOS downsampling; DPI varies among 72/96/110/150/240/300/600, rotation ±25°, minor skew ±0.025, Gaussian blur 0–1.25 px, JPEG quality 35–95, paper tone 205–255, ink 0–89, contrast 0.70–1.25, noise sigma 0–6, broken ink up to 0.8%, and exposure 0.70–1.30. Candidate coordinates undergo the same affine transform as the source. Seed, vector primitives and all degradation parameters permit regeneration. No DXF writer is involved.

## Human seed and active learning

Run [launch-labeling.ps1](launch-labeling.ps1) locally. It uses the existing shared Python, retained manifest and external patch cache; labels are durably stored in `docs/product-fix-p3b/labels/local-labels.json`, separate from that regenerable cache. No ML terminology or prediction is needed.

Keys: **1** one physical stroke; **2** two real structural lines; **3** other; **4** ambiguous; **SPACE** skip; **BACKSPACE** undo; **C** show/hide context. The UI shows number/progress, source crop and red candidate overlay. Samples alternate between drawings. It never loads model predictions. Each label/undo writes an atomic replacement after flushing and fsync; a crash retains the previous complete label file and loses at most the current action. The label file is bound to the exact manifest hash; changing the dataset requires a new label version. Skip leaves the sample unlabeled and it can be revisited next session. Text/graphic-owned controls reject structural labels without crashing the UI.

Start with roughly 200–300 source-diverse human seed samples, retaining all four classes and sufficient true-parallel/door/junction negatives. This is a planning target, not a sufficiency claim or a class quota that forces uncertain labels. Audit nomination quality and class/source support before further mining. Do not declare a training-ready dataset solely from raw crop counts.

Future loop: labeled seed → train classical baseline → train the small CNN only if warranted → score remaining train pool → select a round of about 64 → human review → new version → retrain. [active_learning.py](../../tools/p3b/active_learning.py) combines normalized entropy, predicted-class balance and drawing diversity, caps each drawing at eight per round, suppresses exact duplicates and source centers within 128 px, and suppresses dHash neighbors at Hamming distance ≤4. Previously labeled/seen samples participate in duplicate suppression. Human labels never see the model score. Class balance is a selection preference, not pseudo-labeling. Review duplicate filters for over-suppression; no near-duplicate count represents a new independent structure.

## Baselines and metrics

A is the **unchanged** P3A source/profile/safety gate, read-only. P3A is a merge/abstain gate, not a four-class probabilistic model. Its merge proposals project to SINGLE; preservation projects to explicit ABSTAIN, not TRUE_PARALLEL or the human AMBIGUOUS class. Real baseline decisions are available for 14 captured W03 native pairs; 755 nominations have no captured decision and stay `NOT_CAPTURED`. A replay of arbitrary cropped LSD proposals is not presented as production evidence. [baseline-prelabel.json](baseline-prelabel.json) consequently reports null real class metrics rather than a fictional zero error rate.

The frozen P3A function was also replayed on complete generated synthetic scenes; returned hypothetical geometry was discarded. Additional generated CAD context builds protection for junction obstacles. [baseline-synthetic.json](baseline-synthetic.json) records 196 labeled synthetic samples: SINGLE=54, TRUE_PARALLEL=72, OTHER=70, human AMBIGUOUS=0. P3A abstained on all 196 degraded scenes, with 0/72 false merges and 0 SINGLE recall. Its one-sided 95% IID upper bound is about 4.08%, before accounting for correlated variants. Zero observed errors with zero action coverage is **not** evidence that learning or a production merge gate is safe. A separate clean control test confirms that the same unchanged P3A gate can propose the expected isolated solid-stroke merge and preserve paper-separated rails.

B is standardized 18-feature logistic regression, balanced classes, fixed seed and one fixed configuration. [classical.py](../../tools/p3b/classical.py) requires all four labeled train classes plus independently sourced validation samples. It is prepared but **not fit**: human labels/validation patches do not yet exist, and sklearn is not installed. Freeze/benchmark A and B before the neural experiment. Tune any further classical hyperparameters with family-grouped CV inside train; do not search against the blind test.

The one image-model candidate is a small CNN trained from scratch: 3 convolutions (16/32/64 channels), global pooling, 18-feature fusion, a 64-unit head, and four logits. No foundation model or pretrained large encoder. This is a proposed research model; no model was trained. Raw research softmax/logistic probabilities are not production-calibrated confidence. Temperature calibration, threshold selection, uncertainty/OOD behavior and class-cost analysis need independent validation sources. False merges dominate model/threshold selection; an all-abstain baseline must be compared on both safety and useful SINGLE coverage.

[benchmark.py](../../tools/p3b/benchmark.py) reports per-class precision/recall/support, 4×5 confusion including explicit abstention, `FALSE_MERGE_RATE = predicted SINGLE among truth TRUE_PARALLEL / all truth TRUE_PARALLEL`, error numerator/support and a one-sided binomial confidence bound, human/predicted AMBIGUOUS coverage, abstention, selective accuracy/coverage at 0.50/0.80/0.90/0.95/0.99/0.995, and results by drawing, source family, effective DPI (including unknown), and synthetic/real domain. Threshold reports include both all-parallel and accepted-parallel denominators. Absent support yields null. Deterministic gates do not get invented confidence probabilities; probability thresholds do not apply to their outputs. Correlated patches require independent physical-structure grouping and drawing-cluster risk assessment before any certification; the IID bound is explicitly insufficient. The benchmark code is preparation, not a completed real-world model comparison.

## Conservative future production entry gate — specification only

No gate below is implemented in production. Initial proposal:

1. Qualified real train/validation/blind truth, frozen input/checkpoint/calibration, independent drawing/origin separation and no source/structure/patch leakage.
2. Zero false merges in adjudicated real blind structural negatives, and a conservative one-sided risk bound below 0.1%. An IID zero-error bound needs at least about 2,995 **independent** negatives; overlapping patches or degradation variants cannot supply that independence. Cover multiple projects (initial target ≥20), door/shaft/junction/enclosure families and DPI regimes; require per-source audits and drawing-cluster analysis. Current data does not establish this gate.
3. Demonstrated gain over P3A and classical B at the same safety constraint, with useful action coverage. Confidence calibration, OOD tests and all abstention/AMBIGUOUS behavior must be assessed on real source groups.
4. For any future action: calibrated `P(SINGLE) ≥ 0.995`, `P(TRUE_PARALLEL) ≤ 0.001`, `P(AMBIGUOUS) ≤ 0.001`, within validated source/DPI/input support **AND** existing P3A source evidence **AND** fully available/unhit protection mask **AND** no shared protected topology **AND** no door/opening veto **AND** no structural-context veto.
5. Missing evidence or conflict means preserve geometry/review. Learned probabilities never override a deterministic veto. The model emits only probabilities and provenance; a later deterministic authority would own any CAD decision. Closed P1/P2B/P3A invariants and product acceptance must then be rerun in a separate integration task.

## Local/Colab interruption and storage plan

[train_small.py](../../tools/p3b/train_small.py) prepares an epoch-resumable research runner. Atomic checkpoints preserve model, optimizer, completed epoch, dataset/label versions, entire split manifest, seed, metric history, configuration, fitted train feature normalization and Python/NumPy/CPU/CUDA RNG state. Resume rejects a changed dataset/labels/split/configuration. Interruption during an epoch restarts that epoch from the previous complete checkpoint, including optimizer/RNG state. Optional `--sync-dir` atomically copies the latest checkpoint after each completed epoch. It never depends on an always-running cloud VM. Batch size, seed and package versions are fixed within a run; cross-device bit identity is not promised.

For later Colab: stage only approved nonblind train/validation files into `/content/p3b` scratch, use POSIX paths/`--patch-root`, install optional pinned research dependencies, keep manifests/labels/checkpoints durably outside scratch, sync periodically, restore the last complete checkpoint into scratch after disconnection and pass `--resume`. Cache sync is separate from compute; cloud storage is not mounted as the hot dataset cache. P3B makes no cloud connection/upload. Dataset authorizations and redistribution states remain in inventory. PyTorch/sklearn are absent locally, so training/checkpoint runtime is **not verified**; syntax and configuration guards are prepared, and no neural training was used to test them. Freeze exact future training dependencies and compare interrupted/uninterrupted research runs before relying on resume.

Large generated files live in the explicitly regenerable sibling directory `C:/Users/agcrf/Desktop/image-to-cad-p3b-cache/{real-v1,synthetic-v1}`. The prepared cache is about 83.74 MB, and retained P3B docs/manifests are about 3.67 MB. It contains PNG patches/context and synthetic truth metadata, no huge duplicate page arrays or NPZ dumps. Manifests, summaries, benchmark outputs, source/tool hashes and representative views stay here in docs. Human labels and future checkpoints must not be stored under that regenerable cache. Source PDFs/images/native CAD remain in their existing locations. `.gitignore`/`.ignore` are unchanged; production search/storage policy remains intact. [verification.json](verification.json) records final byte sizes and dataset hashes.

`finalize.py --prune-stale-patches` removes only obsolete tool-owned `real-/synthetic-<24 hex>` patch folders under this exact designated cache, after path/reparse/name/file-allowlist checks. It refuses unknown contents, and cannot remove labels/checkpoints or source files. Future large expansion should use a versioned external cache with a stated disk budget, remove closed regenerable versions after retaining their reproduction records, and never accumulate duplicate arrays inside the checkout.

## Reproduction and verification

From `C:/Users/agcrf/Desktop/image-to-cad/instrumented-e03`:

```powershell
& ../.venv/Scripts/python.exe -B tools/p3b/inventory.py
& ../.venv/Scripts/python.exe -B tools/p3b/extract.py --out C:/Users/agcrf/Desktop/image-to-cad-p3b-cache/real-v1 --per-kind 16
& ../.venv/Scripts/python.exe -B tools/p3b/synthetic.py --out C:/Users/agcrf/Desktop/image-to-cad-p3b-cache/synthetic-v1 --variants 2
& ../.venv/Scripts/python.exe -B tools/p3b/benchmark.py --manifest C:/Users/agcrf/Desktop/image-to-cad-p3b-cache/real-v1/samples.jsonl --out docs/product-fix-p3b/baseline-prelabel.json
& ../.venv/Scripts/python.exe -B tools/p3b/benchmark.py --manifest C:/Users/agcrf/Desktop/image-to-cad-p3b-cache/synthetic-v1/samples.jsonl --out docs/product-fix-p3b/baseline-synthetic.json
& ../.venv/Scripts/python.exe -B tools/p3b/test_preparation.py
& ../.venv/Scripts/python.exe -B -m ruff check tools/p3b
& ../.venv/Scripts/python.exe -B tools/p3b/finalize.py --cache C:/Users/agcrf/Desktop/image-to-cad-p3b-cache --prune-stale-patches
& ./docs/product-fix-p3b/launch-labeling.ps1
```

Preparation checks cover drawing/family/hash leakage, forbidden synthetic blind and structural text labels, safety/confusion/selective metrics with absent-support nulls, fixed channel coordinates/features, synthetic truth/splits, atomic labels under interrupted replacement, undo/resume/manifest binding, active selection caps, hidden Tk initialization/buttons/context/skip/undo and the frozen P3A clean positive/parallel control. [preparation-tests.txt](preparation-tests.txt) records the result. Source crops/overlays were visually inspected. [production-before.json](production-before.json) and final verification prove unchanged hashes for all 157 existing app/test Python/JSON files, including the already uncommitted P3A work. No old production file was reformatted or committed. Existing outer-repository index corruption was not repaired; the active `instrumented-e03` checkout remains the task root.

Human labeling is ready. Training adequacy, real benchmark performance, complete topology/mask capture and future resume runtime remain deliberately unclaimed. Next step is the human seed, then a separate decision based on its class/source coverage. STOP.
