"""Extract visible Unicode PDF text as editable whole runs.

Hidden OCR is excluded. Adjacent compatible runs on the same baseline are joined
without per-character objects or sample-specific text substitutions.
"""
from __future__ import annotations

import numpy as np
import pymupdf as fitz


def extract_visible_pdf_text(page):
    # Text trace includes hidden OCR. Invisible paint is not an editable visible
    # original and must not be painted a second time over a scanned page.
    rows = []
    seen = set()
    for span in page.get_texttrace():
        if span["type"] == 3 or span.get("opacity", 1.0) <= 0:
            continue
        text = "".join(chr(c[0]) if 0 <= c[0] <= 0x10FFFF else "\ufffd" for c in span["chars"])
        if not text.strip() or not span["chars"]:
            continue
        origin = tuple(span["chars"][0][2])
        key = (text, origin, tuple(span["dir"]), span["size"])
        # Fill-and-stroke text can appear in two consecutive text traces.
        if key in seen:
            continue
        seen.add(key)
        row = dict(span, text=text, origin=origin)
        if rows:
            last = rows[-1]
            direction = np.asarray(row["dir"], float)
            delta = np.asarray(origin) - np.asarray(last["origin"])
            baseline_distance = abs(delta[0] * direction[1] - delta[1] * direction[0])
            old_box = fitz.Rect(last["bbox"])
            projections = [np.dot(np.asarray(tuple(p)) - np.asarray(last["origin"]), direction)
                           for p in (old_box.tl, old_box.tr, old_box.bl, old_box.br)]
            gap = float(np.dot(delta, direction) - max(projections))
            same_line = (row["font"] == last["font"] and row["size"] == last["size"]
                         and row["dir"] == last["dir"] and row["type"] == last["type"]
                         and row.get("color") == last.get("color")
                         and baseline_distance < max(0.01, row["size"] * 0.02)
                         and -0.01 <= gap <= max(row.get("spacewidth", 0), row["size"] * 0.4)
                         and row["seqno"] <= last["last_seqno"] + 1)
            if same_line:
                if gap > row["size"] * 0.18 and not last["text"].endswith(" ") and not text.startswith(" "):
                    last["text"] += " "
                last["text"] += text
                last["bbox"] = tuple(old_box | fitz.Rect(row["bbox"]))
                last["last_seqno"] = row["seqno"]
                continue
        row["last_seqno"] = row["seqno"]
        rows.append(row)
    return rows
