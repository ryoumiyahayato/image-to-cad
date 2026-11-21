"""Exercise the actual default native CLI using a generated controlled source.

This is an entry/serialization smoke check, not an engineering-accuracy fixture
or the frozen real-drawing acceptance test. No expected words are fed to OCR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(work: Path) -> dict:
    import ezdxf
    from PIL import Image, ImageDraw, ImageFont

    work = work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    source = work / "controlled-source.png"
    image = Image.new("L", (640, 480), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 560, 400), outline=0, width=3)
    draw.line((100, 280, 400, 280), fill=0, width=3)
    font = ImageFont.truetype("DejaVuSans.ttf", 24)
    draw.text((120, 130), "ROOM 17", font=font, fill=0)
    image.save(source, dpi=(200, 200))
    before = digest(source)
    target = work / "controlled-result.dxf"
    command = [
        sys.executable,
        str(ROOT / "cad_photo_to_dxf/main.py"),
        "--headless",
        "--input",
        str(source),
        "--roi",
        "0",
        "0",
        "640",
        "480",
        "--dpi",
        "200",
        "--output",
        str(target),
        "--jobs-dir",
        str(work / "jobs"),
        "--cpu-seconds",
        "240",
        "--wall-seconds",
        "300",
        "--verbose",
    ]
    environment = dict(os.environ)
    environment.pop("I2CAD_RAW_OBSERVATION_CACHE", None)
    environment.pop("PYTHONPATH", None)
    environment.update(
        OMP_NUM_THREADS="1",
        OMP_THREAD_LIMIT="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        PYTHONNOUSERSITE="1",
    )
    with (
        (work / "stdout.txt").open("x", encoding="utf-8") as stdout,
        (work / "stderr.txt").open("x", encoding="utf-8") as stderr,
    ):
        completed = subprocess.run(
            command,
            cwd=work,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            timeout=330,
            check=False,
        )
    if completed.returncode:
        raise RuntimeError(
            f"Actual native CLI failed ({completed.returncode}); inspect {work / 'stderr.txt'}"
        )
    document = ezdxf.readfile(target)
    audit = document.audit()
    if audit.errors or audit.fixes:
        raise AssertionError(
            "Generated result did not survive an unchanged DXF cold read"
        )
    formal = [
        entity for entity in document.modelspace() if entity.dxf.layer != "REVIEW"
    ]
    if not formal or any(entity.dxftype() in {"HATCH", "IMAGE"} for entity in formal):
        raise AssertionError(
            "Controlled source did not produce real native candidate geometry"
        )
    if document.units != 4 or digest(source) != before:
        raise AssertionError(
            "Source changed or paper-millimetre unit contract was lost"
        )
    companion = target.with_suffix(".native")
    entry = json.loads(
        (companion / "result.entry_trace.json").read_text(encoding="utf-8")
    )
    if (
        entry["mode"] != "native-objects"
        or entry["legacy_processing_called"]
        or entry["legacy_export_called"]
        or entry["source_sha256"] != before
    ):
        raise AssertionError(
            "Default CLI did not enter the source-bound native pipeline"
        )
    states = list((work / "jobs").glob("*/state.json"))
    if len(states) != 1:
        raise AssertionError(
            "Controlled CLI did not create exactly one independent task"
        )
    state = json.loads(states[0].read_text(encoding="utf-8"))
    if (
        state["raw_observation_cache"]["selection"] != "new_task_local_cache"
        or state["raw_observation_cache"]["entry_count"] != 0
    ):
        raise AssertionError(
            "Fresh controlled entry unexpectedly inherited prior raw observations"
        )
    tesseract = os.environ.get("I2CAD_TESSERACT") or shutil.which("tesseract")
    observed = subprocess.run(
        [str(tesseract), "--version"],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    report = {
        "status": "PASS",
        "scope": "actual managed default CLI / controlled generated source / cold DXF",
        "source_sha256": before,
        "dxf_sha256": digest(target),
        "formal_entities": len(formal),
        "formal_types": sorted({entity.dxftype() for entity in formal}),
        "task_status": state["status"],
        "algorithm": state["algorithm"],
        "tesseract_version_observed": (observed.stdout or observed.stderr).splitlines()[
            0
        ],
        "native_mode_was_default": "--mode" not in command,
        "initial_raw_observations": state["raw_observation_cache"]["entry_count"],
        "expected_transcription_supplied_to_recognizer": False,
        "controlled_fixture_only_not_frozen_region_acceptance": True,
        "product_GO": False,
    }
    (work / "smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir", type=Path, required=True, help="A new private/output directory"
    )
    args = parser.parse_args()
    print(json.dumps(run(args.work_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
