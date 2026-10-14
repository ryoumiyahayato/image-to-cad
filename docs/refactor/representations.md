# Straight-line representation decisions

The supplied audit counts policy filters and bundles as transforms; the same
definition is used below. Actual endpoints stay in LineSegment throughout:
ownership raster -> vector means filtering the original objects, not recovering
coordinates from pixels. The audit's claimed repeated precision loss therefore
does not occur in this path.

| Source type | Target type | Call site | Purpose | Decision |
|---|---|---|---|---|
| LSD float32 array | LineSegment | detect_lines | detector domain boundary | Necessary |
| LineSegment | filtered LineSegment | detect_lines | minimum detector support | Necessary policy |
| LineSegment | extended LineSegment | reconstruct_straight_lines | supported reconstruction | Necessary algorithm |
| LineSegment | ledger route observation | observe_route/transformation | preserve original evidence across transformations | Necessary identity |
| LineSegment | uint8 line mask | partition_content | source-pixel semantic overlaps | Necessary raster algorithm |
| masks | CandidateOwnership | partition_content | named categories in one coordinate frame | Necessary data bundle |
| CandidateOwnership | ArbitratedOwnership | arbitrate_content_candidates | resolve semantic overlaps | Necessary algorithm |
| ownership result | original LineSegment subset | arbitrate_content_candidates | select original proposals without changing coordinates | Necessary selection |
| accepted lines | ReconciliationResult | reconcile | certify source identity and exact subsegments | Necessary algorithm |
| committed lines | updated ownership mask | _assign_and_reconcile | represent restored/new pieces for residual tracing | Necessary changed data |
| updated masks | committed-line veto | _assign_and_reconcile | reject a reconciliation/ownership disagreement, update semantic objects | Necessary safety boundary |
| ReconciliationResult | JunctionConsumptionResult | consume_junction_contract (opt-in) | trusted external junction obligations | Necessary optional feature already present |
| committed lines | FinalStructure tuple | build_final_structure | final immutable geometry | Necessary final boundary |
| FinalStructure | contract-wrapped FinalStructure | old service | metadata only | Redundant; deleted in D |
| FinalStructure lines | ezdxf LINE | add_straight_line_entities | scale/Y inversion serialization | Necessary output boundary |

Second arbitration cannot be removed as a packaging change: reconciliation can
admit restoration pieces absent from initial ownership, and the final residual
mask changes contour output. It also checks committed-line veto and object
selection. Kept its semantics and grouped this coherent operation into a plain
function; no manager/context class. No mask becomes an object's identity.
