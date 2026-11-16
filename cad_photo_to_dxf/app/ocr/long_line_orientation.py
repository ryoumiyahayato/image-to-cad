"""Protect long OCR crops from anisotropic direction classification.

This adapter only cancels a 180-degree flip when two disjoint native-aspect
native-aspect windows independently say upright. Extra non-edge votes also
require stable whole-line recognition. It never edits recognized strings.
"""

from copy import copy
from math import isfinite

import cv2
import numpy as np


class LongLineOrientationClassifier:
    def __init__(self, classifier, recognize=None):
        self.classifier = classifier
        self.recognize = recognize

    def _stable_upright_reading(self, crop):
        """Corroborate a non-edge vote pair; never accept a score alone.

        The same source-oriented line must survive a white-margin change. This
        is model consistency evidence, not an independent ground-truth oracle.
        No dictionary, expected string, page name or target coordinate is used.
        """
        if not callable(self.recognize):
            return False
        try:
            pad = max(2, int(round(crop.shape[0] * 0.10)))
            padded = cv2.copyMakeBorder(
                crop, pad, pad, pad, pad, cv2.BORDER_CONSTANT,
                value=255 if crop.ndim == 2 else (255,) * crop.shape[2],
            )
            review = self.recognize([crop.copy(), padded])
            texts = review.txts
            scores = review.scores
            if len(texts) != 2 or len(scores) != 2:
                return False
            first, second = (" ".join(str(value).split()) for value in texts)
            return (
                first == second
                and sum(char.isalnum() for char in first) >= 4
                and all(isfinite(float(value)) and float(value) >= 0.95 for value in scores)
            )
        except (AttributeError, TypeError, ValueError, IndexError, RuntimeError):
            return False

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
                if any(str(label) == "180" and float(score) >= threshold for label, score in votes):
                    continue
                height, width = crops[index].shape[:2]
                window_width = int(round(height * model_width / model_height))
                starts = (0, (width - window_width) // 2, width - window_width)
                supporting = [
                    position for position, (label, score) in enumerate(votes)
                    if str(label) == "0" and float(score) >= threshold
                ]
                disjoint = [
                    (first, second) for first in supporting for second in supporting
                    if first < second and starts[second] - starts[first] >= window_width
                ]
                if not disjoint:
                    continue
                # Preserve the existing edge contract. An additional middle+edge
                # pair cannot override orientation without a stable whole-line
                # read; overlapping windows are not independent votes.
                if (0, 2) in disjoint:
                    pair = (0, 2)
                else:
                    if not self._stable_upright_reading(crops[index]):
                        continue
                    pair = max(disjoint, key=lambda value: min(float(votes[k][1]) for k in value))
                updated_images[index] = crops[index].copy()
                updated_labels[index] = (
                    "0", min(float(votes[k][1]) for k in pair),
                )
            updated = copy(result)
            updated.img_list = updated_images
            updated.cls_res = updated_labels
            updated.elapse = result.elapse + review.elapse
            return updated
        except (AttributeError, TypeError, ValueError, IndexError, RuntimeError):
            # Optional input review cannot discard successful classification.
            return result
