# Remaining structure and why it exists

This review uses the supplied audit's family definitions. A short function is
not necessarily a forwarding layer. No application GUI subclass remains and
no detected short function calls another detected short function.

## Short functions detected by the mechanical check

| Function | Actual responsibility |
|---|---|
| core.member_binding._digest | Canonical identity for the external member binding contract. |
| core.processing.ProcessingCacheKey.from_payload | Deserialize an external key through its validated constructor. |
| core.processing._json_sha256 | Canonical configuration hash used by cache identity. |
| geometry.junction_v2_consumer._digest | Canonical identity in the separately trusted junction schema. |
| geometry.reconciliation_geometry._line_identity_key | Exact geometry/provenance identity; not proximity matching. |
| geometry.source_stroke_reconciliation._normal_source_profile | Compute the 17-offset source cross-section used by certification. |
| geometry.source_stroke_reconciliation._source_claim_id | Build a stable, namespaced source claim identifier. |
| geometry.source_stroke_reconciliation._source_scope_digest | Seal the source authority scope in reconciliation proofs. |
| geometry.straight_line_reconstruction._standalone_restoration_is_fully_certified | Evaluate source certificate policy against retained proposals. |
| gui.document._processing_pdf_dpi | Bound the requested PDF DPI by the page size and pixel limit. |
| gui.image_canvas.ImageCanvas.set_image | Public canvas command with reset semantics. |
| gui.image_canvas.ImageCanvas.zoom_in | Qt command using the established 1.25 zoom factor. |
| gui.image_canvas.ImageCanvas.zoom_out | Qt command using the established 0.8 zoom factor. |
| ocr.font_library._system_font_faces | Select actual installed font faces. |
| ocr.text_output_contract.accepted_ocr_texts | Select texts eligible for editable output. |
| ocr.text_output_contract.suppressible_ocr_texts | Select texts whose source outlines may safely be suppressed; a different policy. |

The digest helpers above belong to distinct schema namespaces. A shared hash
service would introduce a layer without removing their schema-specific work.
The mechanical single-call shape also matches computations, filters and public
commands, explaining the retained maximum chain of one.

ProductionProcessingService owns configuration, cancellation and contract
attachment at the actual processing boundary. It no longer repacks output.
build_final_structure is the existing construction API: it normalizes optional
arguments and checks the optional external member binding. The trace-result
reader returns an existing FinalStructure unchanged and constructs one only
for older serialized raster results that actually lack it. This remains a
current cache reader, not a second processing engine.

export_final_structure_dxf maps the authoritative structure, masks, calibration
and options into the actual single-document writer. Single-document writing
and streaming document layout share write_page_entities. Their remaining
orchestration differs in units, page offset, underlay and streaming lifecycle.
Neither decides line identity or topology. Worker classes, cancellation tokens,
review dialogs and canvases have independent Qt/thread or resource lifetimes.
MainWindow's methods are directly bound ordinary functions grouped by job;
there are no superclass-forwarding or mixin chains.

## The seven original validation families

| Original family | Final disposition and remaining reason |
|---|---|
| Coordinate finiteness | LineSegment constructor owns its numeric state. Remaining checks concern other domains: scale, raw detector arrays and external text/JSON coordinates. |
| Zero/minimum length | Detector and algorithm thresholds are policies. Zero-length detector candidates remain legal until filtering; constructor rejection would change existing behavior. |
| Image dimensions/nonempty | Independent public image/underlay boundaries accept raw NumPy arrays. They cannot assume another entry point has already validated those arrays. |
| Type/subclass | GUI inheritance assertion and shadow entity checks removed. External JSON/cache parsing and heterogeneous metadata still require shape/type checks. |
| SHA format | One construction-boundary implementation in core.processing; redundant downstream checks removed. |
| Junction authority | One existing validator at external contract consumption/configuration boundaries. Trust can change with source/configuration, so construction alone is insufficient. |
| Cancellation | Long-running work needs checkpoints in distinct loops/stages. These are operations, not an object invariant. |

Six recurring gate families remain under the original broad counting rule;
this does not mean six duplicated validator implementations. No validation
manager or future F3/D schema was introduced. FinalStructure validates and
freezes its state at construction, including dataclass replacement. Preview,
export and processing do not repeat that full validation.

## Original parallel families

| Family | Disposition |
|---|---|
| CLI/GUI reconstruction | Both call ProductionProcessingService.process_page. V1 removed. |
| Line cleaning | V1 generic cleaner removed; existing source-certified reconstruction preserved. |
| Ownership | Shadow arbitrators removed; current content ownership retained. |
| Geometry authority | Shadow CAD IR removed; FinalStructure is authoritative. Frozen member-binding data remains a reader contract, not a producer. |
| Topology | Dead topology validator and historical endpoint audit removed; current connectivity safety remains. |
| OCR | Dead auxiliary orchestration and old recognition entry removed; current RapidOCR pipeline remains. Its supported pass/fallback parsing is within that engine. |
| DXF serialization | V1 serializer removed. Single-page and streaming exports share one entity writer. |

All fourteen remaining audited representation steps are individually explained
in representations.md. Raster ownership operations filter original vector
objects and do not reconstruct endpoint coordinates from raster pixels.
The second ownership pass consumes newly admitted pieces and updates residual
contours; removing it would change output. Optional junction consumption is an
existing trust boundary, not a new feature.

## Remaining modules above 1,000 lines

| Module | LOC | Why preserved |
|---|---:|---|
| geometry/source_stroke_reconciliation.py | 5802 | Source identity, exact interval coverage, endpoint obligations, certification and commit proofs affect acceptance/output. Extracted unchanged geometry primitives; no generic merging replacement. |
| geometry/straight_line_reconstruction.py | 2024 | Supported extension/restoration proposals and source evidence policies precede reconciliation. Their distinct rejection rules remain covered by regression tests. |
| geometry/content_ownership.py | 1367 | Source-pixel semantic overlap and residual selection determine contours, texts and retained original lines. Two calls process different proposals/masks. |
| geometry/junction_v2_consumer.py | 1105 | Existing optional trusted contract consumption and fail-closed obligations. Producer/shadow infrastructure removed; consumer behavior retained. |

Optional source_support_lifecycle diagnostics retain their event vocabulary for
explicit capture. They are lazily imported, detached from core objects and not
required by default processing. Historical audit generators and their tests
were deleted. No local artifact directory is required.

## Metric limits

verify_architecture.py scans the final Python files and their explicit imports,
including TYPE_CHECKING and optional edges. Call depth is the longest resolved
static function path after recursion is condensed; dynamic dispatch is not
guessed. The old audit's 22 counted sequential stages, so 16 is not a measured
six-frame runtime stack reduction. The old 10-level wrapper figure was the GUI
inheritance chain; that chain is now zero, while isolated short APIs count as
one under the final static rule. God modules use a stated 1,000-line threshold.
Representation/family counts are manually classified using the supplied audit,
with their decisions recorded here rather than inferred from string counts.
