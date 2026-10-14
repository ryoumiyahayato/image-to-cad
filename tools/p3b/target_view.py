"""Explicit candidate-only UI overlay; contains no expected class or prediction."""

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def target_overlay(gray, row, scale=2, *, trial=False, members="all"):
    if trial:
        return trial_overlay(gray, row, scale, members)
    image = gray.convert("RGB").resize(
        (256 * scale, 256 * scale), Image.Resampling.NEAREST
    )
    draw = ImageDraw.Draw(image)
    x, y, _, _ = row["source_bbox"]
    geometry = row.get("candidate_geometry", [])
    colors = ("#e32936", "#007eae")
    close_pair = (
        len(geometry) == 2
        and row.get("quality", {})
        .get("metrics", {})
        .get("PAIR_SEPARATION_STABILITY", {})
        .get("mean_px", 100)
        * scale
        < 4
    )
    for i, (_, line, _) in enumerate(geometry[:2]):
        points = [((line[k] - x) * scale, (line[k + 1] - y) * scale) for k in (0, 2)]
        color = colors[i]
        if close_pair:
            a, b = np.array(points[0]), np.array(points[1])
            distance = float(np.linalg.norm(b - a))
            # Alternating display dashes distinguish overlapping paths without offsetting geometry.
            for start in np.arange(i * 8, distance, 16):
                p = a + (b - a) * start / max(distance, 1e-9)
                q = a + (b - a) * min(start + 8, distance) / max(distance, 1e-9)
                draw.line((tuple(p), tuple(q)), fill=color, width=3)
        else:
            draw.line(points, fill=color, width=3)
        for endpoint, (px, py) in enumerate(points, 1):
            draw.ellipse(
                (px - 4, py - 4, px + 4, py + 4), fill=color, outline="white", width=1
            )
            # Text labels stay inside the viewport even when an endpoint is close to an edge.
            label = ("A" if i == 0 else "B") + str(endpoint)
            lx, ly = (
                min(max(px + (-28 if i == 0 else 9), 3), image.width - 25),
                min(max(py + (-18 if i == 0 else 9), 3), image.height - 16),
            )
            draw.rectangle((lx - 1, ly - 1, lx + 19, ly + 12), fill="white")
            draw.text((lx, ly), label, fill=color)
    if not geometry and row.get("target_roi"):
        tx, ty, tw, th = row["target_roi"]
        box = (
            (tx - x) * scale,
            (ty - y) * scale,
            (tx + tw - x) * scale,
            (ty + th - y) * scale,
        )
        draw.rectangle(box, outline="#e32936", width=3)
        cx = (box[0] + box[2]) / 2
        # Crosshair outside the ink bbox, keeping the nominated pixels unobscured.
        draw.line((cx - 5, box[1] - 6, cx + 5, box[1] - 6), fill="#e32936", width=2)
        draw.text((max(2, box[0]), max(2, box[1] - 16)), "Target", fill="#e32936")
    return image


def trial_overlay(gray, row, scale=2, members="all"):
    """Thin display-only Chinese layers; the source target never changes."""
    if members not in ("none", "A", "B", "all"):
        raise ValueError("Unknown target display layer")
    image=gray.convert("RGB").resize((round(gray.width*scale),round(gray.height*scale)),Image.Resampling.NEAREST)
    if members=="none": return image
    draw=ImageDraw.Draw(image)
    font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc",max(10,round(8*scale)))
    x,y,_,_=row["source_bbox"]
    geometry=row.get("candidate_geometry",[])
    width=max(1,round(.65*scale))
    close=len(geometry)==2 and row.get("quality",{}).get("metrics",{}).get("PAIR_SEPARATION_STABILITY",{}).get("mean_px",100)<3
    for i,(_,line,_) in enumerate(geometry):
        member="AB"[i]
        if members not in ("all",member): continue
        color=("#db2435","#0078aa")[i]
        points=[((line[k]-x)*scale,(line[k+1]-y)*scale) for k in (0,2)]
        if close and members=="all":
            a,b=np.array(points[0]),np.array(points[1]);length=float(np.linalg.norm(b-a))
            for start in np.arange(i*4*scale,length,8*scale):
                p=a+(b-a)*start/max(length,1e-9)
                q=a+(b-a)*min(start+4*scale,length)/max(length,1e-9)
                draw.line((tuple(p),tuple(q)),fill=color,width=width)
        else: draw.line(points,fill=color,width=width)
        for endpoint,(px,py) in enumerate(points):
            radius=1.6*scale
            draw.ellipse((px-radius,py-radius,px+radius,py+radius),outline=color,width=width)
            lx=min(max(px+(-22 if i==0 else 5)*scale,3),image.width-34*scale)
            ly=min(max(py+(-15 if i==0 else 6)*scale,2),image.height-12*scale)
            draw.text((lx,ly),member+("起" if endpoint==0 else "止"),fill=color,font=font,
                      stroke_width=max(1,round(scale/2)),stroke_fill="white")
    if not geometry and row.get("target_roi") and members=="all":
        tx,ty,tw,th=row["target_roi"]
        box=((tx-x)*scale,(ty-y)*scale,(tx+tw-x)*scale,(ty+th-y)*scale)
        draw.rectangle(box,outline="#db2435",width=width)
        draw.text((max(2,box[0]),max(2,box[1]-12*scale)),"区域目标",fill="#db2435",font=font)
    return image


def target_zoom(gray, row, factor=4):
    x, y, _, _ = row["source_bbox"]
    geometry = row.get("candidate_geometry", [])
    if geometry:
        points = np.array([g[1] for g in geometry]).reshape(-1, 2)
        center = points.mean(0) - [x, y]
    else:
        tx, ty, tw, th = row["target_roi"]
        center = np.array([tx + tw / 2 - x, ty + th / 2 - y])
    size = 512 // factor
    left = max(0, min(256 - size, round(center[0] - size / 2)))
    top = max(0, min(256 - size, round(center[1] - size / 2)))
    return gray.crop((left, top, left + size, top + size)).resize(
        (512, 512), Image.Resampling.NEAREST
    )


def annotated_zoom(gray, row, factor=4, **overlay_options):
    x, y, _, _ = row["source_bbox"]
    if row.get("candidate_geometry"):
        center = np.array([g[1] for g in row["candidate_geometry"]]).reshape(
            -1, 2
        ).mean(0) - [x, y]
    else:
        tx, ty, tw, th = row["target_roi"]
        center = np.array([tx + tw / 2 - x, ty + th / 2 - y])
    size = 512 // factor
    left = max(0, min(256 - size, round(center[0] - size / 2)))
    top = max(0, min(256 - size, round(center[1] - size / 2)))
    return target_overlay(gray, row, factor, **overlay_options).crop(
        (left * factor, top * factor, (left + size) * factor, (top + size) * factor)
    )


def source_support_view(gray, row):
    image = target_overlay(gray, row, scale=2)
    draw = ImageDraw.Draw(image)
    pixels = np.argwhere(np.array(gray) < 180)[:, ::-1]
    x, y, _, _ = row["source_bbox"]
    if not len(pixels):
        draw.text((8, 8), "No dark source support", fill="black")
        return image
    for i, (_, line, _) in enumerate(row.get("candidate_geometry", [])):
        points = np.linspace(np.array(line[:2]), np.array(line[2:]), 5) - [x, y]
        for point in points:
            nearest = pixels[np.argmin(np.sum((pixels - point) ** 2, axis=1))]
            distance = float(np.linalg.norm(nearest - point))
            px, py = point * 2
            nx, ny = nearest * 2
            draw.line((px, py, nx, ny), fill="#557b37", width=1)
            draw.ellipse((nx - 3, ny - 3, nx + 3, ny + 3), outline="#238032", width=2)
            lx, ly = min(max(px + 9, 2), 470), min(max(py - 19, 2), 493)
            draw.rectangle((lx - 1, ly - 1, lx + 38, ly + 12), fill="white")
            draw.text((lx, ly), f"{distance:.1f}px", fill="#28591f")
    return image
