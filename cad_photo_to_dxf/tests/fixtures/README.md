# Real-image fixture policy

Synthetic tests prove code-level invariants only. They do not prove that a photographed drawing was reconstructed correctly.

Every fixture must contain a real camera or scanner capture, its SHA-256, documented ownership/provenance, a repository-use licence, a reviewer identity, one or more declared categories, and a `manifest.json` conforming to `manifest.schema.json`.

There are two accepted outcomes.

## Vectorized drawing fixture

Set `expected_outcome` to `vectorized_dxf`. The fixture must also include:

- `ground_truth.dxf` from the original CAD model or an independently reviewed manual trace;
- the ground-truth DXF SHA-256;
- expected paper corners, corner tolerance and orientation;
- coordinate mode: `paper_mm` or `model_mm`;
- for `model_mm`, an explicit pixel-to-model calibration reference;
- dimensions used for calibration and different dimensions reserved for verification;
- expected LINE and layer-count ranges;
- explicit endpoint, angle, scale and Hausdorff tolerances;
- a statement on whether open contours are intentional;
- FreeCAD version `0.19.2`, matching the pinned CI import environment.

The benchmark runs the full strict pipeline, exports a candidate DXF and compares it with the ground truth. Corner, entity, layer, endpoint, angle, scale and sampled-geometry errors must all remain within the declared tolerances.

## Non-paper rejection fixture

Set `expected_outcome` to `paper_rejected`, include category `non_paper_negative`, and set `expected_rejection` to `paper_detection`.

This fixture does not require a ground-truth DXF. It passes only when strict paper detection rejects the image with `PaperDetectionError`. Being accepted as a drawing, failing later for an unrelated reason, or producing an empty DXF is a failure.

## Required release coverage

A release-quality fixture set must collectively cover all categories:

1. `flat_scan`;
2. `mild_perspective`;
3. `severe_perspective`;
4. `blur_shadow_fold`;
5. `hidden_paper_edge`;
6. `non_paper_negative`;
7. `multi_resolution`;
8. `portrait_landscape`;
9. `mixed_geometry`;
10. `original_cad_dimensions`.

Validate current manifests without imposing a release minimum:

```powershell
python scripts/validate_fixtures.py tests/fixtures --minimum 0
```

Run the release qualification and ground-truth benchmarks:

```powershell
python scripts/validate_fixtures.py tests/fixtures --minimum 1
```

The release workflow runs the second command and stops when no qualifying fixture exists, any required category is absent, or any benchmark exceeds tolerance. Do not fabricate ground truth. Unknown provenance, unknown licence, generated images presented as camera captures, or unreviewed CAD cannot satisfy the release gate.
