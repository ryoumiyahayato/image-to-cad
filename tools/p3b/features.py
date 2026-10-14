"""Fixed compact feature contract; excludes IDs, split, labels, fate and P3A decision."""

import numpy as np
from PIL import Image

FEATURE_NAMES = (
    "separation_256",
    "angle_delta_180",
    "overlap_256",
    "dpi_600",
    "dpi_known",
    "mean_gray",
    "std_gray",
    "dark_fraction",
    "gradient_x",
    "gradient_y",
    "width_px_16",
    "width_known",
    "stable_fraction",
    "dark_core_fraction",
    "center_offset_16",
    "profile_samples_19",
    "contrast_separated_fraction",
    "pair_present",
)


def feature_vector(row, folder):
    g = np.array(Image.open(folder / "gray.png").convert("L"), dtype=np.float32) / 255
    f = row.get("features", {})
    profiles = [
        m.get("profile")
        for m in (row.get("current_p3a_measurement") or [])
        if m.get("profile")
    ]
    p = profiles[0] if profiles else {}
    dpi = row.get("source_dpi")
    return np.array(
        [
            f.get("distance_px", 0) / 256,
            f.get("angle_delta_deg", 0) / 180,
            f.get("overlap_px", 0) / 256,
            (dpi or 0) / 600,
            float(dpi is not None),
            g.mean(),
            g.std(),
            (g < 128 / 255).mean(),
            np.abs(np.diff(g, axis=1)).mean(),
            np.abs(np.diff(g, axis=0)).mean(),
            p.get("source_width_px", 0) / 16,
            float(bool(p)),
            p.get("stable_fraction", 0),
            p.get("dark_core_fraction", 0),
            p.get("center_offset_px", 0) / 16,
            p.get("samples", 0) / 19,
            p.get("contrast_separated_fraction", 0),
            float(len(row["candidate_geometry_ids"]) == 2),
        ],
        dtype=np.float32,
    )


def image_tensor(row, folder):
    # Channels: [ink darkness, candidate edges, nominal candidate centerline].
    channels = [
        np.array(Image.open(folder / (name + ".png")).convert("L"), dtype=np.float32)
        / 255
        for name in ("gray", "edges", "centerline")
    ]
    channels[0] = 1 - channels[0]
    return np.stack(channels)
