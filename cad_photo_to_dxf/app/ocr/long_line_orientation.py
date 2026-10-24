"""Protect long OCR crops from anisotropic direction classification.

This adapter only cancels a 180-degree flip when two disjoint native-aspect
edge windows independently say upright. It never edits recognized strings.
"""

from copy import copy
from math import isfinite

import numpy as np


class LongLineOrientationClassifier:
    def __init__(self, classifier):
        self.classifier = classifier

    def __getattr__(self, name):
        return getattr(self.classifier, name)

    def __call__(self, images):
        result = self.classifier(images)
        crops = [images] if isinstance(images, np.ndarray) else images
        # Unsupported backend shapes retain the backend's original decision.
        try:
            _, model_height, model_width = self.classifier.cls_image_shape
            threshold = max(0.95, float(self.classifier.cls_thresh))
            if model_height <= 0 or model_width <= 0 or not isfinite(threshold):
                return result
            labels = result.cls_res
            if len(labels) != len(crops) or len(result.img_list) != len(crops):
                return result
            indices, windows = [], []
            for index, (crop, (label, score)) in enumerate(zip(crops, labels)):
                height, width = crop.shape[:2]
                window_width = int(round(height * model_width / model_height))
                if (
                    str(label) != "180"
                    or not isfinite(float(score))
                    or float(score) <= self.classifier.cls_thresh
                    or window_width < 1
                    or width < 2 * window_width
                ):
                    continue
                indices.append(index)
                for left in (0, (width - window_width) // 2, width - window_width):
                    windows.append(
                        np.ascontiguousarray(crop[:, left : left + window_width])
                    )
            if not windows:
                return result
            review = self.classifier(windows)
            if len(review.cls_res) != len(windows):
                return result
            updated_images = list(result.img_list)
            updated_labels = list(labels)
            for offset, index in enumerate(indices):
                votes = review.cls_res[offset * 3 : offset * 3 + 3]
                if any(
                    str(label) not in {"0", "180"} or not isfinite(float(score))
                    for label, score in votes
                ):
                    continue
                if any(
                    str(votes[edge][0]) != "0" or float(votes[edge][1]) < threshold
                    for edge in (0, 2)
                ):
                    continue
                if str(votes[1][0]) == "180" and float(votes[1][1]) >= threshold:
                    continue
                updated_images[index] = crops[index].copy()
                updated_labels[index] = (
                    "0",
                    min(float(votes[0][1]), float(votes[2][1])),
                )
            updated = copy(result)
            updated.img_list = updated_images
            updated.cls_res = updated_labels
            updated.elapse = result.elapse + review.elapse
            return updated
        except (AttributeError, TypeError, ValueError, IndexError, RuntimeError):
            # Optional input review cannot discard successful classification.
            return result
