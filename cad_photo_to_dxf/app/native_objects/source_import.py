"""Read-only native scan import with explicit selection and coordinate evidence.

PNG/JPEG/TIFF use their decoded sample grid without resizing. Scanned PDF is
rasterised at the explicitly requested DPI, never at the GUI preview size.
The algorithm's coordinate frame is the whole selected raster after an exact
quarter-turn. Original bytes are never changed or replaced by that derivative.
"""

from __future__ import annotations

from .performance import profiled
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from .job import NativeJobConfig


class SourceImportError(ValueError):
    def __init__(self, code, message, **details):
        self.code, self.details = code, details
        super().__init__(f"{code}: {message}")


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _selected(value, count, kind):
    if value is None:
        if count != 1:
            raise SourceImportError(
                f"EXPLICIT_{kind.upper()}_REQUIRED",
                f"This source has {count} {kind}s; select one using a 1-based index",
                count=count,
            )
        return 1
    if not 1 <= value <= count:
        raise SourceImportError(
            f"{kind.upper()}_OUT_OF_RANGE",
            f"Requested {kind} {value}; available range is 1..{count}",
            count=count,
            requested=value,
        )
    return value


def inspect_container(path) -> dict:
    """Metadata only; suitable for page/frame selection before any preview."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Native scan input is missing: {path}")
    if path.suffix.lower() == ".pdf":
        import pymupdf as fitz

        try:
            with fitz.open(path) as doc:
                if doc.needs_pass:
                    raise SourceImportError(
                        "ENCRYPTED_PDF",
                        "Password-protected PDF is not supported by this import route",
                    )
                if doc.page_count < 1:
                    raise SourceImportError("EMPTY_PDF", "The PDF has no pages")
                return {
                    "format": "PDF",
                    "page_count": doc.page_count,
                    "frame_count": None,
                }
        except (OSError, RuntimeError) as exc:
            raise SourceImportError(
                "UNREADABLE_PDF", str(exc), original=str(path)
            ) from exc
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as im:
            if im.format not in ("PNG", "JPEG", "TIFF"):
                raise SourceImportError(
                    "UNSUPPORTED_RASTER_FORMAT",
                    f"Decoded format {im.format}; expected PNG, JPEG or TIFF",
                )
            return {
                "format": im.format,
                "page_count": None,
                "frame_count": int(getattr(im, "n_frames", 1)),
            }
    except (UnidentifiedImageError, OSError, SyntaxError, EOFError) as exc:
        raise SourceImportError(
            "UNREADABLE_RASTER", str(exc), original=str(path)
        ) from exc


@profiled("source_import.inspect_source")
def inspect_source(path, *, dpi, page_number=None, frame_number=None) -> dict:
    info = inspect_container(path)
    if info["format"] == "PDF":
        if frame_number is not None:
            raise SourceImportError(
                "FRAME_NOT_APPLICABLE_TO_PDF",
                "Use --page for PDF; --frame selects TIFF/image frames",
            )
        page_no = _selected(page_number, info["page_count"], "page")
        import pymupdf as fitz

        with fitz.open(path) as doc:
            page = doc.load_page(page_no - 1)
            raster_rect = (page.rect * fitz.Matrix(dpi / 72.0, dpi / 72.0)).irect
            info.update(
                page_number_1based=page_no,
                frame_number_1based=None,
                source_size_px=[int(raster_rect.width), int(raster_rect.height)],
                page_rect_points=list(page.rect),
                page_mediabox_points=list(page.mediabox),
                page_cropbox_points=list(page.cropbox),
                intrinsic_PDF_rotation=page.rotation,
                PDF_page_rotation_matrix=list(page.rotation_matrix),
                PDF_to_MuPDF_page_matrix=list(page.transformation_matrix),
                source_metadata_dpi=None,
                source_metadata_dpi_original=None,
                source_exif_orientation=None,
                alpha_composited_on_white=False,
                PDF_rasterization_dpi=int(dpi),
                PDF_vector_extraction_used=False,
            )
            scale = dpi / 72.0
            raster = [
                [scale, 0.0, -raster_rect.x0 - 0.5],
                [0.0, scale, -raster_rect.y0 - 0.5],
                [0.0, 0.0, 1.0],
            ]
            info["PDF_user_space_to_source_pixel_centres"] = affine_product(
                raster,
                affine_product(
                    _fitz_affine(page.rotation_matrix),
                    _fitz_affine(page.transformation_matrix),
                ),
            )
            info["PDF_coordinate_note"] = (
                "PDF user-space points -> MuPDF unrotated page -> intrinsic page rotation -> requested-DPI pixel centres"
            )
    else:
        if page_number is not None:
            raise SourceImportError(
                "PAGE_NOT_APPLICABLE_TO_RASTER",
                "Use --frame for TIFF/image frames; --page selects PDF pages",
            )
        frame_no = _selected(frame_number, info["frame_count"], "frame")
        from PIL import Image

        with Image.open(path) as im:
            im.seek(frame_no - 1)
            raw_dpi = im.info.get("dpi")
            if raw_dpi is not None and not isinstance(raw_dpi, (tuple, list)):
                raw_dpi = [raw_dpi]
            dpi_values = (
                None
                if raw_dpi is None
                else [float(v) if math.isfinite(float(v)) else None for v in raw_dpi]
            )
            original_dpi = (
                None
                if raw_dpi is None
                else [
                    {
                        "type": type(v).__name__,
                        "repr": repr(v),
                        "numerator": int(v.numerator)
                        if hasattr(v, "numerator")
                        else None,
                        "denominator": int(v.denominator)
                        if hasattr(v, "denominator")
                        else None,
                    }
                    for v in raw_dpi
                ]
            )
            info.update(
                page_number_1based=None,
                frame_number_1based=frame_no,
                source_size_px=list(im.size),
                source_metadata_dpi=dpi_values,
                source_metadata_dpi_original=original_dpi,
                source_exif_orientation=im.getexif().get(274),
                alpha_composited_on_white=(
                    im.mode in ("RGBA", "LA") or "transparency" in im.info
                ),
                EXIF_orientation_policy="No additional ImageOps.exif_transpose; coordinates refer to the selected decoded grid",
            )
    return info


def validate_roi(roi, size):
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]):
        raise SourceImportError(
            "ROI_OUTSIDE_SELECTED_SOURCE",
            f"ROI {roi} is outside selected {size[0]} x {size[1]} source",
        )


def affine_product(a, b):
    return [
        [sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)
    ]


def _fitz_affine(matrix):
    a, b, c, d, e, f = list(matrix)
    return [[a, c, e], [b, d, f], [0.0, 0.0, 1.0]]


def affine_inverse(a):
    det = a[0][0] * a[1][1] - a[0][1] * a[1][0]
    if det == 0:
        raise ValueError("SINGULAR_COORDINATE_TRANSFORM")
    p, q, r, s = a[1][1] / det, -a[0][1] / det, -a[1][0] / det, a[0][0] / det
    return [
        [p, q, -p * a[0][2] - q * a[1][2]],
        [r, s, -r * a[0][2] - s * a[1][2]],
        [0.0, 0.0, 1.0],
    ]


def coordinate_contract(size, roi, orientation, dpi):
    w, h = size
    x0, y0, x1, y1 = roi
    if orientation == 0:
        rotation, target_roi, working_size = (
            [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            list(roi),
            [w, h],
        )
    elif orientation == 90:
        rotation = [[0, -1, h - 1], [1, 0, 0], [0, 0, 1]]
        target_roi, working_size = [h - y1, x0, h - y0, x1], [h, w]
    elif orientation == 180:
        rotation = [[-1, 0, w - 1], [0, -1, h - 1], [0, 0, 1]]
        target_roi, working_size = [w - x1, h - y1, w - x0, h - y0], [w, h]
    elif orientation == 270:
        rotation = [[0, 1, 0], [-1, 0, w - 1], [0, 0, 1]]
        target_roi, working_size = [y0, w - x1, y1, w - x0], [h, w]
    else:
        raise ValueError("UNSUPPORTED_QUARTER_TURN")
    scale = 25.4 / dpi
    cad = [
        [scale, 0.0, -target_roi[0] * scale],
        [0.0, -scale, target_roi[3] * scale],
        [0.0, 0.0, 1.0],
    ]
    source_cad = affine_product(cad, rotation)
    return {
        "source_size_px": list(size),
        "working_size_px": working_size,
        "source_ROI_xyxy_px": list(roi),
        "working_ROI_xyxy_px": target_roi,
        "source_to_working": rotation,
        "working_to_source": affine_inverse(rotation),
        "working_to_CAD": cad,
        "CAD_to_working": affine_inverse(cad),
        "source_to_CAD": source_cad,
        "CAD_to_source": affine_inverse(source_cad),
        "matrix_convention": "column homogeneous [x,y,1]; pixel centres at integer coordinates",
        "ROI_convention": "half-open integer sample index bounds; not transformed as pixel-centre corner points",
        "CAD_convention": "existing writer: ((working_x-x0)*25.4/dpi, (y1-working_y)*25.4/dpi)",
        "orientation_clockwise_degrees": orientation,
        "rotation_interpolation": "none: exact quarter-turn sample permutation",
        "unit": "paper_mm",
        "engineering_scale_verified": False,
    }


@profiled("source_import._decode")
def _decode(path, info, dpi):
    import numpy as np

    if info["format"] == "PDF":
        import pymupdf as fitz

        with fitz.open(path) as doc:
            page = doc.load_page(info["page_number_1based"] - 1)
            pix = page.get_pixmap(dpi=int(dpi), colorspace=fitz.csGRAY, alpha=False)
            return (
                np.frombuffer(pix.samples, dtype=np.uint8)
                .reshape(pix.height, pix.width)
                .copy()
            )
    from PIL import Image

    try:
        with Image.open(path) as im:
            im.seek(info["frame_number_1based"] - 1)
            im.load()
            if info["alpha_composited_on_white"]:
                rgba = im.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                im = Image.alpha_composite(background, rgba)
            return np.asarray(im.convert("L"))
    except (OSError, SyntaxError, EOFError) as exc:
        raise SourceImportError(
            "RASTER_DECODE_FAILED", str(exc), original=str(path)
        ) from exc


@dataclass(frozen=True)
class PreparedSource:
    gray: object
    working_roi: tuple[int, int, int, int]
    source_sha256: str
    manifest: dict


def assert_fresh_evidence(job: NativeJobConfig):
    """Never reuse a prior job's text, repair locations or import evidence."""
    if job.evidence_dir.exists() and any(job.evidence_dir.iterdir()):
        raise SourceImportError(
            "EVIDENCE_DIRECTORY_ALREADY_OCCUPIED",
            f"Use a new empty job evidence directory: {job.evidence_dir}; explicit caches are read-only inputs",
            requested_job_id=job.job_id,
        )


def validate_cache(cache_dir, manifest):
    if cache_dir is None:
        return {"requested": False, "decision": "NO_CACHE"}
    cache_dir = Path(cache_dir)
    files = [
        cache_dir / name
        for name in (
            "completed_stages.json",
            "native_verified_cache.json",
            "native_completion_stages.json",
        )
    ]
    checked = []
    for path in files:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        identity = data.get("job_source_identity")
        if identity is not None:
            if identity != manifest["cache_identity"]:
                raise SourceImportError(
                    "CACHE_JOB_IDENTITY_MISMATCH",
                    f"Selected page/frame/ROI/DPI/orientation differs from {path}",
                )
            basis = "full v3 page/frame/ROI/DPI/orientation/sample identity"
        else:
            if not manifest["legacy_v2_cache_equivalent"]:
                raise SourceImportError(
                    "LEGACY_CACHE_NOT_VALID_FOR_TRANSFORMED_JOB",
                    "Old cache has no selected-page/rotation identity; use no cache or a matching v3 cache",
                )
            basis = "legacy single-frame raster, exact unchanged decoded grid and orientation 0; existing producer checks retained"
        if (
            data.get("source_sha256") != manifest["source_sha256"]
            or data.get("roi_xyxy_px") != manifest["coordinates"]["working_ROI_xyxy_px"]
        ):
            raise SourceImportError(
                "CACHE_SOURCE_OR_ROI_MISMATCH", f"Source SHA or ROI differs from {path}"
            )
        if data.get("source_array_sha256") not in (
            None,
            manifest["working_array_sha256"],
        ):
            raise SourceImportError(
                "CACHE_GRAY_SAMPLES_MISMATCH",
                f"Decoded grayscale samples differ from {path}",
            )
        checked.append(
            {"path": str(path), "sha256": file_sha(path), "identity_basis": basis}
        )
    if (cache_dir / "text_ocr_cache").is_dir() and not manifest[
        "legacy_v2_cache_equivalent"
    ]:
        row = cache_dir / "text_ocr_cache/manifest.json"
        data = json.loads(row.read_text(encoding="utf-8")) if row.is_file() else {}
        if (
            data.get("source_array_sha256") != manifest["working_array_sha256"]
            or data.get("roi_xyxy_px") != manifest["coordinates"]["working_ROI_xyxy_px"]
        ):
            raise SourceImportError(
                "DISCOVERY_CACHE_WORKING_FRAME_MISMATCH",
                "OCR cache lacks the transformed raster and ROI fingerprint",
            )
    return {
        "requested": True,
        "directory": str(cache_dir),
        "checked": checked,
        "producer_checks_bypassed": False,
        "decision": "IDENTITY_CHECKED_PRODUCER_CHECKS_STILL_REQUIRED",
    }


@profiled("source_import.prepare_source")
def prepare_source(job: NativeJobConfig, *, persist=True) -> PreparedSource:
    import numpy as np
    from PIL import Image

    if persist:
        assert_fresh_evidence(job)
    before_sha = file_sha(job.input_path)
    info = inspect_source(
        job.input_path,
        dpi=job.dpi,
        page_number=job.page_number,
        frame_number=job.frame_number,
    )
    validate_roi(job.roi, info["source_size_px"])
    source_gray = _decode(job.input_path, info, job.dpi)
    if [source_gray.shape[1], source_gray.shape[0]] != info["source_size_px"]:
        raise SourceImportError(
            "DECODED_SIZE_CHANGED",
            "Source dimensions changed between metadata and decode",
        )
    source_gray_sha = hashlib.sha256(
        memoryview(np.ascontiguousarray(source_gray)).cast("B")
    ).hexdigest()
    working = np.ascontiguousarray(np.rot90(source_gray, k=-(job.orientation_cw // 90)))
    working_sha = hashlib.sha256(memoryview(working).cast("B")).hexdigest()
    coords = coordinate_contract(
        info["source_size_px"], job.roi, job.orientation_cw, job.dpi
    )
    if info["format"] == "PDF":
        pdf_source = info["PDF_user_space_to_source_pixel_centres"]
        coords["PDF_user_space_to_source_pixel_centres"] = pdf_source
        coords["PDF_user_space_to_working"] = affine_product(
            coords["source_to_working"], pdf_source
        )
        coords["PDF_user_space_to_CAD"] = affine_product(
            coords["source_to_CAD"], pdf_source
        )
        coords["CAD_to_PDF_user_space"] = affine_inverse(
            coords["PDF_user_space_to_CAD"]
        )
    if file_sha(job.input_path) != before_sha:
        raise SourceImportError(
            "SOURCE_CHANGED_DURING_IMPORT", "Original input hash changed"
        )
    legacy = (
        info["format"] != "PDF"
        and info["frame_count"] == 1
        and job.orientation_cw == 0
        and not info["alpha_composited_on_white"]
    )
    identity = {
        "source_sha256": before_sha,
        "format": info["format"],
        "page_number_1based": info["page_number_1based"],
        "frame_number_1based": info["frame_number_1based"],
        "source_ROI_xyxy_px": list(job.roi),
        "working_ROI_xyxy_px": coords["working_ROI_xyxy_px"],
        "orientation_clockwise_degrees": job.orientation_cw,
        "recognition_dpi": job.dpi,
        "working_array_sha256": working_sha,
        "working_size_px": coords["working_size_px"],
    }
    manifest = {
        "schema": "native-source-import-v3",
        "job": job.payload(),
        "source_path": str(job.input_path),
        "source_sha256": before_sha,
        "source_file_unchanged": True,
        "selection": info,
        "source_decoded_array_sha256": source_gray_sha,
        "working_array_sha256": working_sha,
        "coordinates": coords,
        "cache_identity": identity,
        "legacy_v2_cache_equivalent": legacy,
        "original_file_replaced_or_edited": False,
        "recognition_resized_to_preview": False,
    }
    manifest["cache_validation"] = validate_cache(job.cache_dir, manifest)
    if persist:
        job.evidence_dir.mkdir(parents=True, exist_ok=True)
        job.temp_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = job.evidence_dir / "import_manifest.json"
        if manifest_path.exists():
            raise FileExistsError(
                f"Import evidence already exists; use a fresh job directory: {manifest_path}"
            )
        if not legacy:
            derivative = job.temp_dir / (job.job_id + ".working.png")
            if derivative.exists():
                raise FileExistsError(
                    f"Working derivative already exists: {derivative}"
                )
            Image.fromarray(working).save(derivative)
            manifest["derived_working_file"] = {
                "path": str(derivative),
                "sha256": file_sha(derivative),
                "role": "explicit page/frame/rotation derivative, not original source",
            }
        preview = Image.fromarray(working)
        preview.thumbnail(
            (job.preview_max_dimension, job.preview_max_dimension),
            Image.Resampling.LANCZOS,
        )
        preview_path = job.evidence_dir / "import_preview.png"
        preview.save(preview_path)
        sx, sy = preview.width / working.shape[1], preview.height / working.shape[0]
        # Resize pixel-centre mapping, not just edge scaling.
        wp = [[sx, 0, (sx - 1) / 2], [0, sy, (sy - 1) / 2], [0, 0, 1]]
        manifest["preview"] = {
            "path": str(preview_path),
            "size_px": list(preview.size),
            "sha256": file_sha(preview_path),
            "working_to_preview": wp,
            "preview_to_working": affine_inverse(wp),
            "source_to_preview": affine_product(wp, coords["source_to_working"]),
            "used_for_recognition": False,
        }
        _dump(manifest_path, manifest)
        _dump(job.evidence_dir / "job_config.json", job.payload())
    working.setflags(write=False)
    return PreparedSource(
        working, tuple(coords["working_ROI_xyxy_px"]), before_sha, manifest
    )


@profiled("source_import.read_preview")
def read_preview(
    path, *, dpi, page_number=None, frame_number=None, orientation=0, max_dimension=1600
):
    """GUI-only preview; its array must never be passed into recognition."""
    import numpy as np
    from PIL import Image

    info = inspect_source(
        path, dpi=dpi, page_number=page_number, frame_number=frame_number
    )
    gray = _decode(path, info, dpi)
    image = Image.fromarray(
        np.ascontiguousarray(np.rot90(gray, k=-(orientation // 90)))
    )
    working_size = list(image.size)
    image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    return np.asarray(image.convert("RGB")), {
        **info,
        "preview_size_px": list(image.size),
        "working_size_px": working_size,
        "recognition_dpi": dpi,
        "orientation_clockwise_degrees": orientation,
        "preview_used_for_recognition": False,
        "source_sha256": file_sha(path),
    }
