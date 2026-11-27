"""Exercise ordinary image/PDF conversion and reopen actual editable DXF files.

Run against source with --source-main main.py or against the packaged desktop
program with --executable PATH. All generated inputs and outputs stay in --work.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import ezdxf
from ezdxf import bbox
from PIL import Image, ImageDraw, ImageFont
import pymupdf


GEOMETRY = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _text(entity) -> str:
    return entity.plain_text() if entity.dxftype() == "MTEXT" else str(entity.dxf.text)


def _normal(text: str) -> str:
    return "".join(text.upper().split())


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _bundle_resources(executable: Path) -> tuple[Path, dict]:
    candidates = [executable.parent / "_internal/resources", executable.parent / "resources"]
    root = next((path for path in candidates if path.is_dir()), None)
    _require(root is not None, "Packaged resources directory is missing")
    font = root / "fonts/NotoSansCJKsc-Regular.otf"
    _require(font.is_file(), "Packaged Chinese font is missing")
    _require((root / "fonts/OFL-1.1.txt").is_file(), "Chinese font license is missing")
    for filename in ("wqy-unicode.lff", "WQY-LICENSE-Apache-2.0.txt"):
        _require((root / "fonts" / filename).is_file(), f"LibreCAD font resource missing: {filename}")
    model_root = root / "ocr/rapidocr"
    manifest = json.loads((model_root / "models.json").read_text(encoding="utf-8"))
    _require(set(manifest["models"]) == {"det", "cls", "rec"}, "OCR bundle needs three models")
    for item in manifest["models"].values():
        path = model_root / item["filename"]
        _require(path.is_file() and _hash(path) == item["sha256"],
                 f"Bundled OCR model is missing or corrupt: {path.name}")
    return font, {"font": str(font), "rapidocr_version": manifest["rapidocr_version"],
                  "models": {role: item["filename"] for role, item in manifest["models"].items()}}


def _fixtures(directory: Path, font_path: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    basic = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(basic)
    draw.rectangle((100, 140, 760, 650), outline="black", width=5)
    draw.line((100, 400, 1050, 400), fill="black", width=5)
    draw.ellipse((820, 160, 1040, 380), outline="black", width=5)
    basic_path = directory / "basic-scan.png"
    basic.save(basic_path, dpi=(300, 300))

    protected = basic.copy()
    draw = ImageDraw.Draw(protected)
    draw.line([(835, 690), (880, 510), (915, 650), (990, 555), (1030, 690), (1140, 580)],
              fill="black", width=7, joint="curve")
    protected_path = directory / "manual-protected-ink.png"
    protected.save(protected_path, dpi=(300, 300))

    bilingual = Image.new("RGB", (1400, 800), "white")
    draw = ImageDraw.Draw(bilingual)
    font = ImageFont.truetype(str(font_path), 56)
    draw.text((90, 55), "设备平面图", font=font, fill="black")
    draw.text((90, 165), "MAIN PUMP 250", font=font, fill="black")
    draw.rectangle((90, 360, 1000, 700), outline="black", width=5)
    draw.line((90, 520, 1180, 520), fill="black", width=5)
    bilingual_path = directory / "bilingual-scan.png"
    bilingual.save(bilingual_path, dpi=(300, 300))

    pdf_path = directory / "native-two-pages.pdf"
    with pymupdf.open() as document:
        for label in ("PDF PAGE ONE", "PDF PAGE TWO"):
            page = document.new_page(width=600, height=400)
            page.insert_text((55, 60), label, fontsize=22)
            page.draw_rect(pymupdf.Rect(55, 100, 400, 330), color=(0, 0, 0), width=1)
            page.draw_line((55, 220), (540, 220), color=(0, 0, 0), width=1)
            page.draw_circle((470, 150), 35, color=(0, 0, 0), width=1)
        document.save(pdf_path)
    return {"basic": basic_path, "bilingual": bilingual_path, "pdf": pdf_path,
            "protected": protected_path}


def _run(command: list[str], directory: Path, env: dict[str, str], timeout: int,
         expected_returncode: int = 0, log_name: str = "conversion") -> dict:
    started = time.monotonic()
    process = subprocess.run(command, cwd=directory, env=env, capture_output=True,
                             timeout=timeout, text=True, encoding="utf-8", errors="replace")
    (directory / f"{log_name}.stdout.txt").write_text(process.stdout, encoding="utf-8")
    (directory / f"{log_name}.stderr.txt").write_text(process.stderr, encoding="utf-8")
    _require(process.returncode == expected_returncode,
             f"Conversion returned {process.returncode}, expected {expected_returncode}; "
             f"see {directory / (log_name + '.stderr.txt')}")
    return {"returncode": process.returncode, "elapsed_seconds": round(time.monotonic() - started, 3)}


def _inspect(output: Path, expected_text: str | None = None) -> dict:
    _require(output.is_file(), f"DXF missing: {output}")
    document = ezdxf.readfile(output)
    _require(not document.audit().has_errors, f"Invalid DXF: {output}")
    entities = list(document.modelspace())
    counts = Counter(entity.dxftype() for entity in entities)
    _require(any(kind in GEOMETRY for kind in counts), f"No editable geometry: {output}")
    texts = [_text(entity) for entity in entities if entity.dxftype() in {"TEXT", "MTEXT"}]
    if expected_text:
        _require(any(_normal(expected_text) in _normal(text) for text in texts),
                 f"Missing editable phrase {expected_text!r} in {output}: {texts}")
    return {"output": str(output), "counts": dict(counts), "texts": texts,
            "sha256": _hash(output), "bytes": output.stat().st_size}


def _edit_roundtrip(source: Path, output: Path) -> dict:
    document = ezdxf.readfile(source)
    space = document.modelspace()
    target = next(entity for entity in space if entity.dxftype() in {"TEXT", "MTEXT"})
    target_handle = target.dxf.handle
    expected = "EDITED PUMP 300"
    if target.dxftype() == "MTEXT":
        target.text = expected
    else:
        target.dxf.text = expected
    geometry = next(entity for entity in space if entity.dxftype() in GEOMETRY)
    geometry_handle = geometry.dxf.handle
    before_bounds = bbox.extents([geometry], fast=True)
    original_count = len(space)
    geometry.translate(7, 11, 0)
    document.saveas(output)
    reopened = ezdxf.readfile(output)
    _require(len(reopened.modelspace()) == original_count, "Edit changed entity count")
    _require(_text(reopened.entitydb[target_handle]) == expected, "Text edit did not survive save")
    _require(reopened.entitydb[geometry_handle].is_alive, "Moved geometry disappeared")
    moved_bounds = bbox.extents([reopened.entitydb[geometry_handle]], fast=True)
    _require(moved_bounds.extmin.isclose(before_bounds.extmin + (7, 11, 0), abs_tol=1e-6),
             "Geometry translation did not survive save")
    _require(not reopened.audit().has_errors, "Edited DXF failed cold read")
    return {"output": str(output), "text_handle": target_handle,
            "geometry_handle": geometry_handle, "saved_text": expected,
            "entity_count": original_count}


def _protected_image_roundtrip(output: Path) -> dict:
    document = ezdxf.readfile(output)
    images = list(document.modelspace().query("IMAGE"))
    _require(len(images) == 1, "An explicit protected region must produce one independent IMAGE")
    image = images[0]
    handle, original_insert = image.dxf.handle, image.dxf.insert
    count = len(document.modelspace())
    resource = Path(image.image_def.dxf.filename)
    if not resource.is_absolute():
        resource = output.parent / resource
    _require(resource.is_file(), "Protected IMAGE has no companion file")
    with Image.open(resource) as pixels:
        _require(pixels.mode == "RGBA", "Protected image lost its alpha channel")
        alpha_range = pixels.getchannel("A").getextrema()
        _require(alpha_range == (0, 255), "Protected image needs both transparent background and visible ink")
    image.translate(7, 11, 0)
    moved = output.with_name("protected-image-moved.dxf")
    document.saveas(moved)
    reopened = ezdxf.readfile(moved)
    target = reopened.entitydb[handle]
    _require(target.dxf.insert.isclose(original_insert + (7, 11, 0), abs_tol=1e-6),
             "Protected IMAGE movement did not survive save")
    _require(len(reopened.modelspace()) == count, "IMAGE movement changed entity count")
    reopened.modelspace().delete_entity(target)
    deleted = output.with_name("protected-image-deleted.dxf")
    reopened.saveas(deleted)
    final = ezdxf.readfile(deleted)
    _require(not final.modelspace().query("IMAGE") and len(final.modelspace()) == count - 1,
             "Protected IMAGE deletion did not survive save")
    return {"mode": "explicit user region; automatic handwriting recognition is not tested",
            "resource": str(resource), "alpha_range": list(alpha_range),
            "moved": str(moved), "deleted": str(deleted)}


def run(args: argparse.Namespace) -> dict:
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if args.executable:
        executable = args.executable.resolve()
        _require(executable.is_file(), f"Executable not found: {executable}")
        font, resources = _bundle_resources(executable)
        command = [str(executable)]
        mode = "packaged-executable"
    else:
        main = args.source_main.resolve()
        font = main.parent / "resources/fonts/NotoSansCJKsc-Regular.otf"
        _require(font.is_file(), "Run scripts/prepare_cad_fonts.py before the smoke test")
        resources = {"font": str(font)}
        command = [sys.executable, str(main)]
        mode = "source"
    fixtures = _fixtures(work / "inputs", font)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update({"PYTHONUTF8": "1", "QT_QPA_PLATFORM": "offscreen",
                "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9", "NO_PROXY": "",
                "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
                "all_proxy": "http://127.0.0.1:9", "no_proxy": ""})
    result = {"mode": mode, "platform": sys.platform, "resources": resources,
              "network_setup": "unreachable HTTP/HTTPS proxy", "cases": {}}
    for name in ("basic", "bilingual", "pdf", "protected"):
        directory = work / name
        directory.mkdir(exist_ok=True)
        output = directory / "drawing.dxf"
        report_path = directory / "drawing.report.json"
        arguments = command + ["--headless", "--input", str(fixtures[name]),
                               "--output", str(output), "--overwrite", "--report", str(report_path)]
        if name in {"basic", "pdf", "protected"}:
            arguments += ["--no-ocr"]
        if name == "protected":
            arguments += ["--preserve-region", "800", "470", "1180", "750"]
        process = _run(arguments, directory, env, args.timeout)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        _require(report.get("schema") == "image-to-cad-conversion-v1", "Unexpected report schema")
        outputs = report["outputs"]
        _require(len(outputs) == (2 if name == "pdf" else 1), "Wrong page count")
        inspected = []
        for index, page in enumerate(outputs):
            expected = ("PDF PAGE ONE", "PDF PAGE TWO")[index] if name == "pdf" else None
            checked = _inspect(Path(page["output"]), expected)
            if name == "pdf":
                _require(page["route"] == "vector", f"Vector PDF used {page['route']} route")
            preview = Path(page["preview"])
            _require(preview.is_file() and preview.stat().st_size > 0, "Preview missing")
            with Image.open(preview) as preview_image:
                preview_image.verify()
            checked.update({"route": page["route"], "preview": str(preview)})
            inspected.append(checked)
        if name == "bilingual":
            texts = inspected[0]["texts"]
            for phrase in ("设备平面图", "MAIN PUMP 250"):
                _require(any(_normal(phrase) in _normal(text) for text in texts),
                         f"OCR did not preserve a normal editable phrase {phrase!r}: {texts}")
            case_output = Path(outputs[0]["output"])
            font_copies = list(case_output.parent.rglob("NotoSansCJKsc-Regular.otf"))
            _require(bool(font_copies), "No portable CJK font beside the OCR DXF")
            result["edited_dxf"] = _edit_roundtrip(case_output, directory / "edited.dxf")
        if name == "protected":
            result["protected_image"] = _protected_image_roundtrip(Path(outputs[0]["output"]))
        result["cases"][name] = {**process, "outputs": inspected, "report": str(report_path)}
    # The public overwrite guard must preserve an existing output.
    basic_directory = work / "basic"
    existing = basic_directory / "drawing.dxf"
    before = _hash(existing)
    _run(command + ["--headless", "--input", str(fixtures["basic"]), "--output", str(existing),
                    "--no-ocr"], basic_directory, env, args.timeout,
         expected_returncode=2, log_name="overwrite-refusal")
    _require(_hash(existing) == before, "Refused overwrite changed the original output")
    result["overwrite_refusal"] = "passed"
    result["passed"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--source-main", type=Path)
    target.add_argument("--executable", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args)
    except Exception as error:
        result = {"passed": False, "error": str(error), "platform": sys.platform}
        (args.work / "product-smoke.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(str(error), file=sys.stderr)
        return 1
    (args.work / "product-smoke.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
