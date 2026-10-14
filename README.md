# Image to CAD — development preview

Image to CAD converts scans, drawing photographs and PDF pages into editable CAD objects. The current version is **0.3.0-dev**, defined in `cad_photo_to_dxf/app/version.py`.

当前产品输出原生 `LINE`、轮廓 `LWPOLYLINE`、可信 OCR `TEXT`，以及有完整源证据的 PDF `ARC`。签名与部分图形使用独立 IMAGE；扫描底图可选，正常预览直接来自保存的 DXF。DWG 依赖用户安装的 ODA File Converter。

This is a development preview, not recovery of the original DWG or unknown design dimensions. Source pixels, ownership, endpoints and protected objects constrain every replacement. Uncertain content keeps its existing representation.

## Current product state — 2026-10-14

- P1–P7: verified fixes for specific line, ownership, text-layout and scan-performance defects. These are scoped results, not complete acceptance of every drawing.
- P8: same physical ink does not authorize merging whole CAD objects with unresolved endpoints or nodes.
- P9: native ARC representation, atomic replacement, cache/save/reopen, DXF export and preview are implemented. Tiny House p9 has a verified fullpage replacement. Round caps and tracked integer-canvas mapping errors are supported; Tasmanian p3 still has no safe real replacement because source visibility/cap sharing fails. P9 is in maintenance.
- P10-A: implemented. USDA p4 replaces two complete isolated scan contours with native LINE objects. The final normal 240-DPI/OCR run took 160.64 seconds. Other scan sources have not established a positive generalization result.
- P3B: maintenance only. No training or new labeling is started.

See [current project status](docs/project/PROJECT_STATUS.md), [decisions](docs/project/DECISIONS.md) and the append-only [engineering evidence index](docs/project/ENGINEERING_EVIDENCE_INDEX.jsonl). The [application guide](cad_photo_to_dxf/README.md) describes normal operation. Historical July UAT and architecture records remain evidence, not the current task queue.

## Run

Python 3.11 is the verified environment. The application uses Qt, OpenCV, PDFium, ezdxf and RapidOCR/ONNX Runtime.

```powershell
Set-Location .\cad_photo_to_dxf
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py --version
python main.py
```

PDF pages load through the normal PDF loader. The GUI can process the current page or processed pages and export per-page results. Images also use the normal raster route. Coordinate modes are paper millimetres, independently calibrated model millimetres, or uncalibrated pixels; no automatic design-scale recovery is claimed.

For editable CJK TEXT, the repository retains the existing licensed `wqy-unicode.lff` and its license. No additional font binary is required by this sync. Deliver IMAGE sidecars with the DXF when signatures or graphics are present.

## Development and verification

Run only checks relevant to the change. For example:

```powershell
python -m pip install -r requirements-test.txt
python -m pytest -q tests/test_native_arc_pipeline.py tests/test_scan_line_regularization.py
python scripts/check_repository_hygiene.py --repository-root ..
```

The retained DXF evidence inventory is [repository-hygiene/inventory.json](cad_photo_to_dxf/validation/repository-hygiene/inventory.json). It contains 93 historical DXF records and recovery references; generated DXF outputs are not new source fixtures. Historical source files remain recoverable from Git history and the sync backup branch. Existing legitimate runtime fonts and test inputs are retained under the repository policy.

Raw material libraries, `local-artifacts/`, model weights, virtual environments, personal settings and generated run caches are local. A fresh clone does not contain every historical real-page run. Tests using tracked small region fixtures are portable; external real-PDF studies require the user's source materials. GUI acceptance and full drawing-set acceptance remain separate from programmatic DXF checks.

No release is published by this synchronization. P10-A is complete for the documented two strokes. Further geometry work requires a new task.
