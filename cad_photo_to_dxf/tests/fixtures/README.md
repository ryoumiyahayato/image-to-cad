# Real-image fixture policy

Synthetic tests prove code-level invariants only. They do not prove that a photographed drawing was reconstructed correctly.

A fixture counts as release acceptance evidence only when its own directory contains:

- a real camera or scanner capture: `source.jpg`, `source.jpeg` or `source.png`;
- `is_real_capture: true`; rendered or generated perspective images do not qualify;
- the source SHA-256, documented ownership/provenance and repository-use licence;
- `ground_truth.dxf` from the original CAD model or an independently reviewed manual trace;
- the ground-truth DXF SHA-256 and reviewer identity;
- `manifest.json` conforming to `manifest.schema.json`;
- one or more declared fixture categories;
- expected paper corners and orientation;
- coordinate mode: `paper_mm` or `model_mm`;
- dimensions used for calibration and different dimensions reserved for verification;
- expected LINE and layer-count ranges;
- explicit endpoint, angle, scale and Hausdorff tolerances;
- a statement on whether open contours are intentional;
- FreeCAD version `0.19.2`, matching the pinned CI import environment.

Required coverage categories:

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

Validate current fixtures without imposing a minimum:

```powershell
python scripts/validate_fixtures.py tests/fixtures --minimum 0
```

A release-quality run requires at least one fully qualifying real-photo fixture:

```powershell
python scripts/validate_fixtures.py tests/fixtures --minimum 1
```

The release workflow runs the second command and stops when no qualifying fixture exists. Do not fabricate ground truth. A fixture with unknown provenance, unknown licence or no original/reviewed CAD remains exploratory and cannot satisfy the release gate.
