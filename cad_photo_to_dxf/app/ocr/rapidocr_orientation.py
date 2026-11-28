"""Keep RapidOCR's crop orientation in the returned full-line quadrilaterals."""

import numpy as np
from rapidocr import RapidOCR


class OrientedRapidOCR(RapidOCR):
    def run_ocr_steps(self, img, op_record):
        detected, classified, recognized, crops = super().run_ocr_steps(img, op_record)
        if detected.boxes is None or classified.cls_res is None or recognized.txts is None:
            return detected, classified, recognized, crops

        # Do this before RapidOCR maps and filters the detection boxes, while
        # each detection still has its corresponding crop and classifier result.
        for index, (box, crop, (label, score)) in enumerate(
            zip(detected.boxes, crops, classified.cls_res),
        ):
            width = max(np.linalg.norm(box[1] - box[0]), np.linalg.norm(box[2] - box[3]))
            height = max(np.linalg.norm(box[3] - box[0]), np.linalg.norm(box[2] - box[1]))
            # RapidOCR quarter-turns tall detections counterclockwise before
            # classification. A landscape crop from a portrait box records that turn.
            turns = int(height > width and crop.shape[1] > crop.shape[0])
            if label == "180" and score > self.text_cls.cls_thresh:
                turns += 2
            if turns:
                detected.boxes[index] = np.roll(box, -turns, axis=0)
        return detected, classified, recognized, crops
