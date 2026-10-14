# Continuation disambiguation D6

## Result

`INSUFFICIENT_DISAMBIGUATING_EVIDENCE`

No later existing pipeline stage cleanly separates the seven qualified structural continuations from the four hard dimension/text lookalikes. The correct outcome is C: retain ambiguity and do not propose an automatic production merge rule.

This study replayed the unchanged current pipeline with non-authoritative `SourceSupportLifecycle` registrations for the six A2-SG-009 positive axes and four hard A2-SG-009 negatives. D2-005 and D2-006 reuse the checkpointed lifecycle evidence. No continuation was synthesized. The A2-SG-009 replay reproduced the recorded production `FinalStructure` ID `33172d9bb3a26669a9de387eb61497ffd97b5fbf462e8c448c28376caa4e8d40`.

## Earliest-safe-decision matrix

`A` means `AMBIGUOUS`. No case reaches `CONFIRMED_STRUCTURAL_CONTINUATION` or `REJECTED_TEXT_OR_GLYPH_LOOKALIKE` from existing operational evidence.

| Case | Kind | Detector | Post-consolidation | Post-eligibility | Post-text | Post-ownership | Post-topology | Final |
|---|---|---|---|---|---|---|---|---|
| D2-001 | positive | A | A | A | A | A | A | A |
| D5-UL-01 | positive | A | A | A | A | A | A | A |
| D5-UL-02 | positive | A | A | A | A | A | A | A |
| D5-UR-01 | positive | A | A | A | A | A | A | A |
| D5-UR-02 | positive | A | A | A | A | A | A | A |
| D5-UR-03 | positive | A | A | A | A | A | A | A |
| D2-006 | positive | A | A | A | A | A | A | A |
| D5-TEXT-UL-01 | hard negative | A | A | A | A | A | A | A |
| D5-TEXT-UL-02 | hard negative | A | A | A | A | A | A | A |
| D5-TEXT-UL-03 | hard negative | A | A | A | A | A | A | A |
| D5-TEXT-UR-01 | hard negative | A | A | A | A | A | A | A |

The classifications are deliberately operational. The positive/negative labels remain the qualified review truth, but the question here is whether an existing pipeline stage can establish that truth safely for a deferred hypothesis. It cannot.

## Evidence trace

| A2 case | Kind | Raw axis coverage | Eligible coverage | Line-filter protection | Post-text LINE | Final owner | Final LINE / outline geometry |
|---|---|---:|---:|---:|---:|---|---:|
| D2-001 | positive | 0.850 | 0.850 | 0.930 | 0.000 | GRAPHIC_FALLBACK | 0 / 0 |
| D5-UL-01 | positive | 0.600 | 0.300 | 0.970 | 0.000 | GRAPHIC_FALLBACK | 0 / 0 |
| D5-UL-02 | positive | 0.780 | 0.000 | 1.000 | 0.000 | GRAPHIC_FALLBACK | 0 / 0 |
| D5-UR-01 | positive | 0.640 | 0.640 | 1.000 | 0.000 | GRAPHIC_FALLBACK | 0 / 0 |
| D5-UR-02 | positive | 0.610 | 0.600 | 1.000 | 0.000 | GRAPHIC_FALLBACK | 0 / 0 |
| D5-UR-03 | positive | 0.630 | 0.470 | 1.000 | 0.000 | GRAPHIC_FALLBACK | 0 / 0 |
| D5-TEXT-UL-01 | hard negative | 0.690 | 0.510 | 1.000 | 0.000 | GRAPHIC_FALLBACK | 0 / 0 |
| D5-TEXT-UL-02 | hard negative | 0.600 | 0.520 | 1.000 | 0.000 | GRAPHIC_FALLBACK | 0 / 0 |
| D5-TEXT-UL-03 | hard negative | 0.660 | 0.520 | 1.000 | 0.000 | GRAPHIC_FALLBACK | 0 / 0 |
| D5-TEXT-UR-01 | hard negative | 0.760 | 0.760 | 1.000 | 0.000 | GRAPHIC_FALLBACK | 0 / 0 |

Coverage is the fraction of the registered three-pixel axis overlapped by each unchanged stage. Exact candidate IDs, Hough/LSD provenance, line histories, masks, claim counts, fallback roots, and source-path measurements are in `diagnostic-report.json`.

### Detector, consolidation, and eligibility

Every case has Hough/LSD provenance. The five thin A2 positives and all four hard negatives retain only ordinary `detected:hough` / `detected:lsd` history; no existing history field supplies semantic identity. Consolidation does not change this class overlap. Eligibility removes more evidence from some positives, especially D5-UL-02, but does not reject the hard negatives as a class. The feasibility study's source connectivity, transverse offset, corridor width, branch density, and off-corridor ink ranges already overlap.

### Text and glyph evidence

The existing evidence has two materially different meanings:

- The OCR/text candidate mask and final TEXT ownership overlap none of the ten A2 axes. No matching final OCR text box exists for any axis.
- The line-filter protection mask overlaps 93–100% of every positive axis and 100% of every hard negative axis. It removes every surviving candidate in both classes.

The protection mask is therefore a shared morphology response, not a discriminator. Treating it as authoritative TEXT evidence would reject all genuine positives, exactly the failure prohibited by this task. No logo or signature candidate/claim overlaps any of the ten axes.

### Ownership and fallback

All ten A2 axes receive the same final owner: `GRAPHIC_FALLBACK`. On each registered axis, LINE, TEXT, LOGO, and SIGNATURE claims are all zero. Each axis is fallback-eligible and executes the scanned-contour fallback, but artifact suppression rejects the overlapping root or roots; none participates in final geometry. Ownership is consequently non-separating, and terminal absence cannot be used as evidence that the hard negatives are text without also misclassifying the positives.

D2-005 remains the useful success control: 100% eligible/post-text/post-filter coverage, final owner LINE, one final line geometry, no fallback execution, and terminal `PRESERVED`.

D2-006 remains explainable under the same evidence model without becoming a safe rule. It has 96.7456% eligible coverage, only 1.0898% post-text LINE coverage, final owner `GRAPHIC_FALLBACK`, zero final LINE ownership claim, and final participation through one contour component plus one line fragment. Its actually connected thick band survives to `FinalStructure`, but that downstream survival neither identifies the missing thin A2 positives nor rejects the hard dimension chains. Using final survival as the decision rule would be circular and source-specific.

The seven already-safe negatives remain rejected by their existing reasons: target mismatch, damaged/ambiguous source, intentional openings, excessive transverse offset, unsupported blank traversal, or conflicting/distinct double rules. No threshold was loosened and D2-005 is unchanged.

### Topology

The feasibility study already showed overlapping local branch-density, tortuosity-adjacent, and off-corridor morphology: genuine axes pass through circles/junctions while dimension chains pass through numerals, circles, and short junction-like strokes. In the current replay every A2 candidate is removed at the text-filter boundary, so no case-specific candidate reaches the later topology audit. Final topology therefore has no structural candidate on which to make the deferred decision. D2-006's final participation is a preservation fact, not a cross-class discriminator.

## Deferred-continuation hypothesis

Preserving `Fragment A`, `Fragment B`, and their source-connected path as a non-authoritative, auditable hypothesis remains architecturally safer than an irreversible detector merge. The current evidence, however, provides no safe later resolver. Creating a production hypothesis object now would add lifecycle machinery without a validated resolution signal, so it is not the next production change candidate.

Evidence that could change this result must be genuinely new and separately validated:

- text/glyph segmentation that distinguishes annotation strokes from nearby structural strokes without rejecting mere text intersections;
- a dedicated structural-stroke classifier using longer-range context and source-supported path morphology;
- domain knowledge for dimension chains, repeated annotations, and inline glyph components;
- an auditable hypothesis ledger only after one of those discriminators demonstrates separation.

## Conclusion

Outcome C applies. Positive structural cases resolved: 0; ambiguous: 7. Hard dimension-text negatives rejected: 0; ambiguous: 4; false-positive merges: 0. There is no earliest safe existing stage, no deferred automatic resolution is justified, and no production change is ready to implement.

Production semantic delta: `NONE`. Validation: `NO`. Locked blind: `0 / 8`.
