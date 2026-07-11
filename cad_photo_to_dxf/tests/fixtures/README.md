# Real-image fixture policy

The automated synthetic tests prove code-level invariants only. They do not prove that a photographed drawing was reconstructed correctly.

A fixture may be counted as production acceptance evidence only when its directory contains:

- `source.jpg` or `source.png` and its SHA-256;
- documented source and redistribution licence;
- `ground_truth.dxf` from the original CAD model or a reviewed manual trace;
- `manifest.json` conforming to `manifest.schema.json`;
- expected paper corners and orientation;
- coordinate mode: `paper_mm` or `model_mm`;
- known dimensions used for calibration and separate dimensions used only for verification;
- expected entity and layer ranges;
- explicit endpoint, angle, scale and Hausdorff tolerances;
- a statement on whether open contours are intentional;
- the fixed FreeCAD version used for import validation.

Required fixture categories:

1. flat scan;
2. mild perspective;
3. severe perspective;
4. blur, shadow and fold;
5. hidden paper edge with a visible internal title frame;
6. non-paper negative examples, including circles;
7. multiple source resolutions of the same sheet;
8. portrait and landscape sheets;
9. thick and thin strokes, diagonals, arcs, text and hatch;
10. photographs with an original CAD model and known design dimensions.

Do not fabricate ground truth. A fixture with unknown provenance or no original CAD remains an exploratory sample and must not be included in release accuracy claims.
