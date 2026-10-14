"""Raw contour fixtures for cache and contour serialization tests."""
import numpy as np
from app.geometry.scan_cleanup import prepare_scan_page
from app.geometry.raster_trace import RasterTraceResult, trace_binary


def contour_result(image):
    prepared = prepare_scan_page(image)
    paths = tuple(trace_binary(prepared.binary))
    return RasterTraceResult(
        binary=prepared.binary, stages={}, paths=paths,
        threshold=prepared.threshold,
        foreground_pixels=int(np.count_nonzero(prepared.binary == 0)),
        vertex_count=sum(len(path.points) for path in paths),
    )
