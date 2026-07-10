from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .cancellation import CancellationToken, checkpoint


@dataclass(frozen=True)
class ImageQualityAssessment:
    focus_variance: float
    illumination_variation: float
    contrast_stddev: float
    likely_blank: bool
    severe_shadow_or_fold_risk: bool
    nonrigid_metric_guarantee: bool
    warnings: tuple[str, ...]


def assess_image_quality(
    image: np.ndarray,
    cancellation_token: CancellationToken | None = None,
) -> ImageQualityAssessment:
    """Return conservative image quality signals, not a geometric guarantee."""
    checkpoint(cancellation_token)
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    checkpoint(cancellation_token)

    height, width = gray.shape[:2]
    max_side = max(height, width)
    scale = min(1.0, 1200.0 / max(max_side, 1))
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    focus = float(cv2.Laplacian(small, cv2.CV_64F).var())
    contrast = float(np.std(small))
    blur_size = max(31, int(round(min(small.shape[:2]) * 0.08)))
    if blur_size % 2 == 0:
        blur_size += 1
    illumination = cv2.GaussianBlur(small, (blur_size, blur_size), 0)
    illumination_variation = float(np.percentile(illumination, 95) - np.percentile(illumination, 5))
    likely_blank = contrast < 3.0
    severe_risk = illumination_variation > 55.0

    warnings: list[str] = []
    if likely_blank:
        warnings.append("图像接近纯色，无法可靠识别图纸内容。")
    if focus < 45.0:
        warnings.append("图像清晰度偏低，细线和文字可能丢失。")
    if severe_risk:
        warnings.append("检测到明显照明不均、折痕或局部形变风险。")
    warnings.append(
        "当前几何校正基于整页单应性；严重折叠、波浪和非刚性形变不保证整页误差小于 2%。"
    )
    return ImageQualityAssessment(
        focus_variance=focus,
        illumination_variation=illumination_variation,
        contrast_stddev=contrast,
        likely_blank=likely_blank,
        severe_shadow_or_fold_risk=severe_risk,
        nonrigid_metric_guarantee=False,
        warnings=tuple(warnings),
    )
