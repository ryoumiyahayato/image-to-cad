"""One isolated mechanism correction; not accepted for production.

Keep the accepted perspective crop for the existing orientation classifier.
Apply its observed 0/180 transform to the same v1 rectangle for recognition.
No text, confidence, truth, source identity or coordinates select answers.
Geometry eligibility is exactly Goal12 v1. Unsupported transformations retain
the classifier's original output. No extra classifier/recognizer calls.
"""
import math

VERSION = 'goal13-baseline-orientation-rectangle-rec-v1'

def install(engine, observer=None):
    import cv2
    import numpy as np
    original_crop = engine.crop_text_regions
    original_cls = engine.cls_and_rotate
    pending = None

    def crop(img, boxes):
        nonlocal pending
        originals = original_crop(img, boxes)
        rectangles = []
        for original, points in zip(originals, boxes):
            q = np.asarray(points)
            rect = None
            if q.shape == (4,2) and np.isfinite(q).all():
                edges = (q[1]-q[0], q[2]-q[3])
                angles = [abs(math.degrees(math.atan2(float(e[1]),float(e[0])))) for e in edges]
                x0,y0 = np.floor(q.min(axis=0)).astype(int)
                x1,y1 = np.ceil(q.max(axis=0)).astype(int)
                if max(angles) <= 5.0 and x1-x0 >= y1-y0 and 0 <= x0 < x1 <= img.shape[1] and 0 <= y0 < y1 <= img.shape[0]:
                    rect = img[y0:y1,x0:x1].copy()
            rectangles.append(rect)
        pending = (originals, rectangles)
        return originals

    def cls(images):
        nonlocal pending
        pair, pending = pending, None
        oriented, cls_result = original_cls(images)
        if pair is None or len(pair[0]) != len(images) or len(oriented) != len(images):
            if observer is not None:
                observer({'choice':'BASELINE_UNMATCHED_CALL','count':len(images)})
            return oriented, cls_result
        originals, rectangles = pair
        result = list(oriented)
        for i,(before,after,rectangle) in enumerate(zip(originals,oriented,rectangles)):
            choice = 'BASELINE_GEOMETRY_FALLBACK'
            if rectangle is not None:
                if np.array_equal(before,after):
                    result[i] = rectangle
                    choice = 'RECTANGLE_BASELINE_UPRIGHT'
                elif np.array_equal(cv2.rotate(before,cv2.ROTATE_180),after):
                    result[i] = cv2.rotate(rectangle,cv2.ROTATE_180)
                    choice = 'RECTANGLE_BASELINE_ROT180'
                else:
                    choice = 'BASELINE_UNSUPPORTED_TRANSFORM'
            if observer is not None:
                observer({'input_index':i,'choice':choice,'original_shape':list(before.shape),'rec_shape':list(result[i].shape)})
        return result, cls_result

    engine.crop_text_regions = crop
    engine.cls_and_rotate = cls
