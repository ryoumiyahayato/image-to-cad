"""Keep the classifier's actual decision aligned with filtered line output."""

from rapidocr import RapidOCR


class DirectionAwareRapidOCR(RapidOCR):
    def build_final_output(
        self, ori_img, det_res, cls_res, rec_res, cropped_img_list, op_record
    ):
        texts = tuple(rec_res.txts or ())
        scores = tuple(rec_res.scores or ())
        labels = tuple(cls_res.cls_res or ())
        directions = ()
        if len(texts) == len(scores) == len(labels):
            threshold = float(self.text_cls.cls_thresh)
            directions = tuple(
                (
                    "180" if str(label) == "180" and float(score) > threshold else "0",
                    float(score),
                )
                for text, confidence, (label, score) in zip(texts, scores, labels)
                if text.strip() and confidence >= self.text_score
            )
        result = super().build_final_output(
            ori_img, det_res, cls_res, rec_res, cropped_img_list, op_record
        )
        # Unsupported backend output stays on the existing conservative route.
        if len(directions) == len(getattr(result, "txts", ()) or ()):
            result.reading_directions = directions
        return result
