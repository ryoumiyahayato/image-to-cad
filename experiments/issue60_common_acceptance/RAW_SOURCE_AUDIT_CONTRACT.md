# Independent raw-source responsibility audit, version 2

This is a bounded diagnostic and acceptance input. It is not an object producer
and cannot authorize CAD adoption by itself. It imports no source graph,
planner, receipt, B candidate, producer PASS, or target chain.

## Input API

```python
audit_raw_source_responsibility(
    gray, geometries, *, roi_xyxy,
    source_origin_xy=(0, 0),
    attachment_declarations=(),
    source_identity=None,
    target_object_ids=None,
)
```

`gray` is the original uint8 grayscale array for this invocation, with no
thinning, dilation, hole filling, OCR, or inferred pixels. Source pixel centers
have integer coordinates. `source_origin_xy` is the global coordinate of array
element `[0, 0]`. `roi_xyxy` contains integer, half-open pixel indices. The ROI
selects evaluation scope; its border cannot be accepted as a stroke boundary.

Each geometry has `object_id`, `kind`, `points`, `bulges`, `closed`, and optionally
`handle`, `parent_object_id`, `member_index`, `bbox_xyxy`, and
`unsupported_reason`, `coverage_valid`, and `bbox_scope`. Coordinates come from the **actual saved DXF**, converted
to source coordinates by an independent reader. Context objects are supplied
alongside targets. `target_object_ids=None` audits all supplied objects; an
explicit list limits endpoint/support checks to those objects and pair checks
to pairs with at least one target. Context objects' remote endpoints are not
new acceptance targets.

Supported centerlines are finite LINE or zero-bulge LWPOLYLINE/CONNECTION_PATH
segments. Nonzero bulges, arcs, and other members are never replaced with a
chord. A relevant unsupported member's observed AABB makes the local endpoint
context unresolved. An unsupported member may only be excluded spatially when
its AABB has explicit `coverage_valid=true` from the independent reader. Missing
or uncertified bounds remain unresolved without suppressing raw measurements.
This fail-closed context-input contract is the only version-2 change; the
version-1 source model, thresholds, initial run, and freeze remain preserved.
Actual lineweight and nonzero display width are not a
substitute for source responsibility; this module audits centerline geometry.

Optional attachment declarations contain `{guest, end, host}`, with `end` 0 or
1 (`-1` also denotes the final endpoint). A host may name an actual member or
its `parent_object_id`. Any provided `anchor` or producer result is retained as
an **unverified declaration**; it does not choose a pixel component, width,
intersection, or accepted boundary. Undeclared contacts are found independently.

## Frozen observation model

1. Black is `gray < 128`. A black pixel denotes its closed unit square. Segment
   cell events and finite segment intersections use exact rational arithmetic
   on the supplied binary64 coordinates. No coordinate is snapped or rounded.
   A positive-length interval with no black-cell support is a hard rejection.
   Positive white-cell **interior** crossings are distinguished from a segment
   on a black/white cell boundary and from zero-length white-corner contacts.
   The latter two are not automatically called real white gaps.
2. All finite segment pairs involving targets are checked. Exact positive
   collinear overlap is rejected. An actual point intersection in original
   white is rejected. Pixel-corner-only connectivity is unresolved. A declared
   endpoint contact that is not exactly observed stays unresolved; a tiny
   distance is reported and does not silently become a connection.
3. Actual original white holes are the 4-connected white components enclosed
   within the evaluation ROI. Every enclosed white pixel is retained. A solid
   black skeleton cycle is not a hole. A real hole need not be an error: holes
   between multiple legitimate strokes are reported, and source support decides
   whether actual geometry crosses them.
4. At each target endpoint, actual finite geometry is sampled inward at arc
   distances **4, 6, 8, 12, and 16 native pixels**. Context geometry is sampled
   at both signs of those offsets around its nearest finite point. Normal
   cross sections extend at most 16 pixels each way. Their original connected
   black intervals must have observed white boundaries. A sample whose measured
   radius plus the pixel half-diagonal reaches another finite centerline is
   excluded as junction-contaminated; exclusions and raw measurements remain.
   At least two isolated sections are required.
5. The measured radius is the greater absolute signed distance from the actual
   centerline to either normal boundary, preserving centerline asymmetry.
   The family of observed radii is `[r_min, r_max]`. For original pixel centers,
   the finite capsule diagnostic uses lower radius
   `max(0, r_min - sqrt(1/2))` and upper radius `r_max + sqrt(1/2)`. This interval
   reports measured width variation plus the radial half-diagonal of a unit
   pixel cell. It is **not** a validated universal pen model or ownership truth.
6. The endpoint window radius is `max(8, 3 * upper_radius + 4)` pixels. Original
   ink is relabeled locally using both 4- and 8-connectivity, from a source
   anchor two pixels into the actual finite approach. Separate ink across a
   real white gap is reported without extending the target. Only forward ink
   centers with projection at least `-sqrt(1/2)` and within the circular window
   enter cap/attachment observations. All relevant finite context envelopes
   are tested; individual and overlapping explanations remain visible.
7. No unassigned forward ink beyond the upper finite envelope gives
   `CAP_OR_JUNCTION_COMPATIBLE`. Connected residual ink gives
   `SOURCE_BOUNDARY_COMPETITION`. A 4-connected residual group with maximum
   distance greater than **2 native pixels** outside every measured upper
   envelope, spanning at least **three distinct one-pixel forward projection
   bins**, gives `OBSERVABLE_UNASSIGNED_CONTINUATION`. This means observable
   connected ink lacks a measured finite-geometry explanation; it does not
   claim to know which stroke owns it. Limited context, clipped windows,
   insufficient sections, or raw corner-only connectivity remain unresolved.

The fixed spans, resource ceilings, and two-pixel observability threshold are
declared applicability limits. They were selected and tested using authored
fixtures before reading the coordinator's actual eight source images. They
are not fitted to a four-object result or to producer decisions. Fixed native
pixels do not establish scale invariance. All raw pixel arrays in the report
are observations from the current source, even if the skeleton or geometry
matches another variant.

## Output and adoption boundary

The JSON contains `policy` and hash, `source_binding`, `geometry_input_sha256`,
`target_object_ids`, `geometry_support`, `pair_contacts`,
`positive_length_overlaps`, `white_holes`, `endpoints`,
`attachment_declaration_checks`, `summary`, and `limitations`.

Each endpoint contains the actual point, terminal direction, every raw width
section and exclusion, original connected forward pixels, disconnected/corner
pixels, each finite envelope's competing pixel explanation, and full unassigned
pixel groups. An endpoint `observation` can distinguish cap compatibility,
boundary competition, and observable continuation even when an independent
context limitation prevents a conclusive overall status.

`HARD_REJECT` means at least one actual unsupported positive interval, unsupported
point contact, or positive geometric duplicate was found. `SOURCE_UNRESOLVED`
means the remaining evidence does not establish the requested responsibility.
`COMPATIBLE_UNDER_LIMITED_RAW_MODEL` means this diagnostic found neither kind of
objection; it is not a certificate of unique object decomposition or product
acceptance. Every report sets `may_adopt_objects_from_this_report_alone=false`
and `independent_source_ownership_proved=false`.

Resource overflow raises a named error; it never silently discards competing
objects or returns a partial PASS. Geometry inputs, source bytes, and producer
files are read-only. The runner writes new outputs only.

## Runner

`run_raw_source_audit.py --source IMAGE --geometry-json JSON --roi X0 Y0 X1 Y1
--out NEW.json` accepts a geometry JSON with `geometries`, optional
`target_object_ids`, and optional `attachment_declarations`. Use
`--source-origin X Y` when the image is an independently preserved crop.
Existing output files are refused. The report records the exact source-file,
geometry-file, implementation, and runner hashes, with no OCR/model calls.
