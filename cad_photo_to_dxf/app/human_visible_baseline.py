from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

import cv2
import numpy as np


class BaselineEntry:
    def __init__(
        self,
        source_group_id: str,
        verdict: str,
        issue_tags: tuple[str, ...],
        primary_observation: str,
        run_directory: Path,
    ) -> None:
        self.source_group_id = source_group_id
        self.verdict = verdict
        self.issue_tags = issue_tags
        self.primary_observation = primary_observation
        self.run_directory = run_directory


def _fit_panel(image: np.ndarray, width: int, height: int) -> np.ndarray:
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(
        image,
        (
            max(1, int(round(image.shape[1] * scale))),
            max(1, int(round(image.shape[0] * scale))),
        ),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
    )
    panel: np.ndarray = np.full((height, width, 3), 248, dtype=np.uint8)
    x = (width - resized.shape[1]) // 2
    y = (height - resized.shape[0]) // 2
    panel[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return panel


def build_baseline_contact_sheet(
    entries: Sequence[BaselineEntry],
    output_path: Path,
) -> Path:
    if len(entries) < 5:
        raise ValueError("Human-visible DEV baseline requires at least five entries")
    panel_width, panel_height = 720, 430
    header_height = 64
    row_height = header_height + panel_height
    sheet: np.ndarray = np.full(
        (72 + row_height * len(entries), panel_width * 3, 3),
        255,
        dtype=np.uint8,
    )
    cv2.putText(
        sheet,
        "HUMAN VISIBLE DEV BASELINE     ORIGINAL | FINAL RECONSTRUCTION | OVERLAY",
        (24, 46),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    for index, entry in enumerate(entries):
        row_y = 72 + index * row_height
        title = (
            f"{entry.source_group_id}   {entry.verdict}   "
            f"issues={','.join(entry.issue_tags) or 'NONE'}   "
            f"{entry.primary_observation}"
        )
        cv2.putText(
            sheet,
            title[:205],
            (24, row_y + 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (35, 35, 35),
            1,
            cv2.LINE_AA,
        )
        for column, filename in enumerate(
            ("original.png", "reconstructed.png", "overlay.png")
        ):
            image = cv2.imread(
                str(entry.run_directory / filename),
                cv2.IMREAD_COLOR,
            )
            if image is None:
                raise OSError(
                    f"Missing visual acceptance image: {entry.run_directory / filename}"
                )
            panel = _fit_panel(image, panel_width, panel_height)
            x = column * panel_width
            sheet[
                row_y + header_height : row_y + row_height,
                x : x + panel_width,
            ] = panel
        cv2.line(
            sheet,
            (0, row_y + row_height - 1),
            (sheet.shape[1] - 1, row_y + row_height - 1),
            (190, 190, 190),
            1,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", sheet)
    if not ok:
        raise OSError("Could not encode DEV baseline contact sheet")
    output_path.write_bytes(encoded.tobytes())
    return output_path


def load_baseline_manifest(path: Path) -> tuple[BaselineEntry, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "human-visible-dev-baseline-v1":
        raise ValueError("Unsupported human-visible DEV baseline manifest")
    entries = tuple(
        BaselineEntry(
            str(item["source_group_id"]),
            str(item["verdict"]),
            tuple(str(value) for value in item["issue_tags"]),
            str(item["primary_observation"]),
            Path(str(item["run_directory"])),
        )
        for item in payload["entries"]
    )
    if len({entry.source_group_id for entry in entries}) != len(entries):
        raise ValueError("DEV baseline SOURCE_GROUPS must be independent")
    if any(entry.verdict not in {"PASS", "PARTIAL", "FAIL"} for entry in entries):
        raise ValueError("DEV baseline verdict must be PASS, PARTIAL, or FAIL")
    return entries


def common_failure_families(
    entries: Sequence[BaselineEntry],
    tag_to_family: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    evidence: dict[str, list[str]] = {}
    for entry in entries:
        for tag in set(entry.issue_tags):
            family = tag_to_family.get(tag)
            if family is not None:
                evidence.setdefault(family, []).append(entry.source_group_id)
    return {
        family: tuple(sorted(source_groups))
        for family, source_groups in evidence.items()
        if len(set(source_groups)) >= 3
    }
