# CAD Photo / Scan PDF to CAD v1.3.0

An auxiliary DXF/DWG conversion tool that converts photos of paper drawings, scanned images, and image-based multi-page PDFs into **scan-faithful underlays + editable structural linework**.

Multi-page PDFs are loaded as a single document and exported together. Each page is assigned a `PAGE-###` layout, while all pages are also arranged vertically in model space. A separate scanned underlay is preserved for each page. Manual review is performed directly on the drawing by selecting regions, changing layers, and deleting incorrectly detected line segments.

> This project is currently an internal preview. The scanned underlay is used to preserve the original visual content; automatically generated vector linework is only an auxiliary result. It should not be treated as a recovery of the original DWG, nor does the project claim a 95% or 98% full-vector reconstruction rate.

The project source code and full documentation are available at [`cad_photo_to_dxf/`](https://github.com/ryoumiyahayato/image-to-cad/blob/main/cad_photo_to_dxf/README.md).

```powershell
Set-Location .\cad_photo_to_dxf
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Supported coordinate modes:

* `paper_mm`: millimeters on the PDF or printed sheet;
* `model_mm`: model coordinates independently calibrated using a known real-world dimension;
* `pixel`: uncalibrated image coordinates.

For the status of historical audit remediation, see [`docs/AUDIT_REMEDIATION.md`](https://github.com/ryoumiyahayato/image-to-cad/blob/main/docs/AUDIT_REMEDIATION.md).
