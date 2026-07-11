from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .dxf_validator import validate_dxf


REQUIRED_FREECAD_VERSION = "0.19.2"
_PLACEHOLDERS = {
    "",
    "unknown",
    "n/a",
    "na",
    "none",
    "todo",
    "tbd",
    "unspecified",
    "待定",
    "未知",
}
_ALLOWED_COORDINATE_MODES = {"paper_mm", "model_mm"}
_ALLOWED_ORIENTATIONS = {"portrait", "landscape"}
_ALLOWED_CATEGORIES = {
    "flat_scan",
    "mild_perspective",
    "severe_perspective",
    "blur_shadow_fold",
    "hidden_paper_edge",
    "non_paper_negative",
    "multi_resolution",
    "portrait_landscape",
    "mixed_geometry",
    "original_cad_dimensions",
}


@dataclass(frozen=True)
class FixtureValidationResult:
    fixture_directory: Path
    fixture_id: str | None
    passed: bool
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["fixture_directory"] = str(self.fixture_directory)
        return value


@dataclass(frozen=True)
class FixtureSetValidationResult:
    root: Path
    qualifying_count: int
    minimum_required: int
    passed: bool
    fixtures: tuple[FixtureValidationResult, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "qualifying_count": self.qualifying_count,
            "minimum_required": self.minimum_required,
            "passed": self.passed,
            "fixtures": [fixture.to_dict() for fixture in self.fixtures],
            "errors": list(self.errors),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _meaningful_text(value: object) -> bool:
    return isinstance(value, str) and value.strip().casefold() not in _PLACEHOLDERS


def _safe_child(directory: Path, value: object, field: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty relative path")
        return None
    relative = Path(value)
    if relative.is_absolute():
        errors.append(f"{field} must be relative to the fixture directory")
        return None
    root = directory.resolve()
    candidate = (directory / relative).resolve()
    if candidate != root and root not in candidate.parents:
        errors.append(f"{field} escapes the fixture directory")
        return None
    return candidate


def _positive_numbers(value: object, field: str, errors: list[str]) -> list[float]:
    if not isinstance(value, list) or not value:
        errors.append(f"{field} must contain at least one positive number")
        return []
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            errors.append(f"{field} must contain only numbers")
            return []
        number = float(item)
        if not math.isfinite(number) or number <= 0:
            errors.append(f"{field} values must be finite and positive")
            return []
        numbers.append(number)
    return numbers


def _validate_tolerances(value: object, errors: list[str]) -> None:
    required = {"endpoint_mm", "angle_degrees", "scale_relative", "hausdorff_mm"}
    if not isinstance(value, dict):
        errors.append("tolerances must be an object")
        return
    if set(value) != required:
        errors.append("tolerances must contain exactly the required four metrics")
        return
    for name, item in value.items():
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            errors.append(f"tolerances.{name} must be numeric")
            continue
        number = float(item)
        if not math.isfinite(number) or number < 0:
            errors.append(f"tolerances.{name} must be finite and non-negative")


def _validate_corners(value: object, errors: list[str]) -> None:
    if not isinstance(value, list) or len(value) != 4:
        errors.append("expected_corners_px must contain exactly four points")
        return
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            errors.append("each expected corner must contain exactly two coordinates")
            return
        for coordinate in point:
            if (
                isinstance(coordinate, bool)
                or not isinstance(coordinate, (int, float))
                or not math.isfinite(float(coordinate))
            ):
                errors.append("expected corner coordinates must be finite numbers")
                return


def _validate_expected_counts(manifest: dict[str, Any], errors: list[str]) -> None:
    entities = manifest.get("expected_entities")
    if not isinstance(entities, dict) or set(entities) != {"line_min", "line_max"}:
        errors.append("expected_entities must contain line_min and line_max")
    else:
        line_min = entities.get("line_min")
        line_max = entities.get("line_max")
        if (
            isinstance(line_min, bool)
            or isinstance(line_max, bool)
            or not isinstance(line_min, int)
            or not isinstance(line_max, int)
            or line_min < 0
            or line_max < line_min
        ):
            errors.append("expected entity range is invalid")

    layers = manifest.get("expected_layers")
    if not isinstance(layers, dict) or not layers:
        errors.append("expected_layers must be a non-empty object")
    else:
        for name, expected_range in layers.items():
            if not _meaningful_text(name):
                errors.append("expected layer names must be meaningful")
                continue
            if (
                not isinstance(expected_range, dict)
                or set(expected_range) != {"min", "max"}
            ):
                errors.append(f"expected_layers.{name} must contain min and max")
                continue
            minimum = expected_range.get("min")
            maximum = expected_range.get("max")
            if (
                isinstance(minimum, bool)
                or isinstance(maximum, bool)
                or not isinstance(minimum, int)
                or not isinstance(maximum, int)
                or minimum < 0
                or maximum < minimum
            ):
                errors.append(f"expected_layers.{name} range is invalid")


def validate_fixture_directory(
    directory: str | Path,
    *,
    required_freecad_version: str = REQUIRED_FREECAD_VERSION,
) -> FixtureValidationResult:
    fixture_directory = Path(directory)
    errors: list[str] = []
    manifest_path = fixture_directory / "manifest.json"
    if not manifest_path.is_file():
        return FixtureValidationResult(
            fixture_directory,
            None,
            False,
            ("manifest.json is missing",),
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return FixtureValidationResult(
            fixture_directory,
            None,
            False,
            (f"manifest.json cannot be read: {exc}",),
        )
    if not isinstance(manifest, dict):
        return FixtureValidationResult(
            fixture_directory,
            None,
            False,
            ("manifest.json must contain an object",),
        )

    fixture_id = manifest.get("id") if isinstance(manifest.get("id"), str) else None
    if not _meaningful_text(fixture_id):
        errors.append("id must be meaningful")
    if manifest.get("is_real_capture") is not True:
        errors.append("is_real_capture must be true; synthetic renders are not real-photo evidence")
    if not _meaningful_text(manifest.get("source_provenance")):
        errors.append("source_provenance must identify the source and capture ownership")
    if not _meaningful_text(manifest.get("licence")):
        errors.append("licence must permit the fixture's intended repository use")
    if not _meaningful_text(manifest.get("reviewed_by")):
        errors.append("reviewed_by must identify the ground-truth reviewer")

    categories = manifest.get("fixture_categories")
    if not isinstance(categories, list) or not categories:
        errors.append("fixture_categories must contain at least one category")
    else:
        invalid_categories = sorted(
            category
            for category in categories
            if not isinstance(category, str) or category not in _ALLOWED_CATEGORIES
        )
        if invalid_categories:
            errors.append(f"unknown fixture categories: {invalid_categories}")

    source_path = _safe_child(
        fixture_directory,
        manifest.get("source_file"),
        "source_file",
        errors,
    )
    ground_truth_path = _safe_child(
        fixture_directory,
        manifest.get("ground_truth_file"),
        "ground_truth_file",
        errors,
    )
    for path, field, allowed_suffixes in (
        (source_path, "source_file", {".jpg", ".jpeg", ".png"}),
        (ground_truth_path, "ground_truth_file", {".dxf"}),
    ):
        if path is None:
            continue
        if not path.is_file():
            errors.append(f"{field} does not exist: {path.name}")
        elif path.suffix.casefold() not in allowed_suffixes:
            errors.append(f"{field} has an unsupported extension")

    for path, field in (
        (source_path, "source_sha256"),
        (ground_truth_path, "ground_truth_sha256"),
    ):
        expected = manifest.get(field)
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append(f"{field} must be a lowercase SHA-256 hex digest")
            continue
        try:
            int(expected, 16)
        except ValueError:
            errors.append(f"{field} must be hexadecimal")
            continue
        if expected != expected.lower():
            errors.append(f"{field} must use lowercase hexadecimal")
        if path is not None and path.is_file() and _sha256(path) != expected:
            errors.append(f"{field} does not match {path.name}")

    paper = manifest.get("paper")
    if not isinstance(paper, dict):
        errors.append("paper must be an object")
    else:
        if not _meaningful_text(paper.get("size")):
            errors.append("paper.size must be meaningful")
        if paper.get("orientation") not in _ALLOWED_ORIENTATIONS:
            errors.append("paper.orientation must be portrait or landscape")

    if manifest.get("coordinate_mode") not in _ALLOWED_COORDINATE_MODES:
        errors.append("coordinate_mode must be paper_mm or model_mm")
    _validate_corners(manifest.get("expected_corners_px"), errors)
    calibration_dimensions = _positive_numbers(
        manifest.get("calibration_dimensions"),
        "calibration_dimensions",
        errors,
    )
    verification_dimensions = _positive_numbers(
        manifest.get("verification_dimensions"),
        "verification_dimensions",
        errors,
    )
    if calibration_dimensions and verification_dimensions:
        if calibration_dimensions == verification_dimensions:
            errors.append(
                "verification_dimensions must be independent from calibration_dimensions"
            )
    _validate_tolerances(manifest.get("tolerances"), errors)
    _validate_expected_counts(manifest, errors)

    if manifest.get("freecad_version") != required_freecad_version:
        errors.append(
            "freecad_version must match the pinned validation version "
            f"{required_freecad_version}"
        )

    if ground_truth_path is not None and ground_truth_path.is_file():
        try:
            ground_truth_validation = validate_dxf(ground_truth_path)
        except Exception as exc:
            errors.append(f"ground-truth DXF cannot be validated: {exc}")
        else:
            if not ground_truth_validation.passed:
                errors.append("ground-truth DXF fails structural validation")
            if ground_truth_validation.line_count <= 0:
                errors.append("ground-truth DXF contains no LINE entities")

    return FixtureValidationResult(
        fixture_directory=fixture_directory,
        fixture_id=fixture_id,
        passed=not errors,
        errors=tuple(errors),
    )


def validate_fixture_set(
    root: str | Path,
    *,
    minimum_required: int = 0,
    required_freecad_version: str = REQUIRED_FREECAD_VERSION,
) -> FixtureSetValidationResult:
    if minimum_required < 0:
        raise ValueError("minimum_required cannot be negative")
    fixture_root = Path(root)
    directories: Iterable[Path]
    if fixture_root.is_dir():
        directories = sorted(
            path
            for path in fixture_root.iterdir()
            if path.is_dir() and (path / "manifest.json").exists()
        )
    else:
        directories = ()

    fixtures = tuple(
        validate_fixture_directory(
            directory,
            required_freecad_version=required_freecad_version,
        )
        for directory in directories
    )
    qualifying_count = sum(1 for fixture in fixtures if fixture.passed)
    errors: list[str] = []
    if qualifying_count < minimum_required:
        errors.append(
            f"only {qualifying_count} qualifying real-photo fixtures; "
            f"minimum required is {minimum_required}"
        )
    invalid_count = sum(1 for fixture in fixtures if not fixture.passed)
    if invalid_count:
        errors.append(f"{invalid_count} fixture manifests are invalid")
    return FixtureSetValidationResult(
        root=fixture_root,
        qualifying_count=qualifying_count,
        minimum_required=minimum_required,
        passed=not errors,
        fixtures=fixtures,
        errors=tuple(errors),
    )
