# Multiscale structural stroke evidence D7

## Result

`HANDCRAFTED_STRUCTURAL_EVIDENCE_INSUFFICIENT`

The same seven qualified structural positives and four D6-ambiguous dimension/text negatives were measured in the captured processing binary and independently thresholded source image. Measurements use three neighborhoods whose axial extent is based on the maximum of gap length, 12 times local stroke width, and 18 times the existing processing scale; meso and wide contexts are 2x and 4x that base. No score, classifier, merge rule, or production threshold was created.

No scalar measurement separates the two classes. Axial and long-range persistence are partial signals only: positives persist farther on average at some scales, but all ranges overlap, and `D5-TEXT-UR-01` is one of the strongest wide-context runs. The other families show no stable direction across source/binary representations and scale. A small conjunction would therefore be fitted to eleven labels rather than supported by an independent margin.

Outcome B applies. The next evidence candidate is validated broader-context dimension-chain and text/glyph perception that recognizes annotation semantics such as labels, repeated dimension layout, and associated markers. Any future result must remain advisory evidence for candidate preservation, continuation hypotheses, or review routing; `FinalStructure` remains the sole reconstruction authority.

## Diagnostic matrix

The compact table shows binary measurements. `Axial L/M/W` is the minimum supported run on either side of the gap divided by gap length. Width is wide-window coefficient of variation/change across gap; drift is normalized by stroke width. Off-axis is wide-window off-axis fraction/tortuosity. Long-range is wide bilateral persistence/axis-support fraction. The full report contains before/after run lengths, both corridor widths, component counts, branch and junction proxies, alignment, and the corresponding source-image values at every scale.

| Case | Kind | Gap px | Axial L/M/W | Width CV/change | Drift | Narrow occupancy | Side occupancy | Off-axis/tortuosity | Anisotropy | Long-range | Result |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| D2-001 | structural | 21.2 | 1.74/3.44/6.21 | 0.62/0.40 | 0.41 | 0.373 | 0.066 | 0.41/1.12 | 609.5 | 6.21/0.958 | AMBIGUOUS |
| D5-UL-01 | structural | 20.6 | 1.16/2.33/4.66 | 0.78/0.00 | 0.60 | 0.507 | 0.206 | 0.45/1.47 | 260.3 | 4.66/1.000 | AMBIGUOUS |
| D5-UL-02 | structural | 20.1 | 1.19/2.39/2.68 | 0.76/0.00 | 0.69 | 0.315 | 0.111 | 0.69/1.83 | 120.5 | 2.68/0.612 | AMBIGUOUS |
| D5-UR-01 | structural | 23.7 | 1.05/2.07/2.83 | 0.63/0.40 | 0.95 | 0.399 | 0.124 | 0.62/1.28 | 239.1 | 2.83/0.867 | AMBIGUOUS |
| D5-UR-02 | structural | 22.5 | 1.38/2.71/3.11 | 0.77/0.40 | 0.81 | 0.395 | 0.152 | 0.70/1.30 | 282.2 | 3.11/0.849 | AMBIGUOUS |
| D5-UR-03 | structural | 21.1 | 1.14/2.18/2.18 | 0.83/0.29 | 0.56 | 0.291 | 0.083 | 0.33/0.91 | 199.4 | 2.18/0.823 | AMBIGUOUS |
| D2-006 | structural | 131.3 | 5.04/7.82/7.82 | 0.95/1.86 | 0.60 | 0.461 | 0.164 | 0.98/1.85 | 224.8 | 7.82/0.900 | AMBIGUOUS |
| D5-TEXT-UL-01 | hard negative | 33.9 | 1.27/1.27/1.27 | 0.79/0.00 | 0.51 | 0.274 | 0.048 | 0.60/1.32 | 381.6 | 1.27/0.663 | AMBIGUOUS |
| D5-TEXT-UL-02 | hard negative | 22.5 | 1.11/2.18/3.34 | 0.71/0.00 | 1.00 | 0.382 | 0.194 | 0.63/1.48 | 215.1 | 3.34/0.982 | AMBIGUOUS |
| D5-TEXT-UL-03 | hard negative | 23.7 | 1.05/1.98/1.98 | 0.63/0.00 | 0.59 | 0.291 | 0.038 | 0.38/1.32 | 245.3 | 1.98/0.770 | AMBIGUOUS |
| D5-TEXT-UR-01 | hard negative | 20.0 | 1.85/3.65/7.26 | 0.63/0.00 | 0.74 | 0.371 | 0.114 | 0.64/1.31 | 472.5 | 7.26/1.000 | AMBIGUOUS |
| D2-005 | structural control | 54.0 probe | 4.02/7.35/7.35 | 0.73/0.06 | 0.64 | 0.331 | 0.062 | 0.90/1.16 | 216.4 | 7.35/0.563 | NO REGRESSION |
| Blank-gap sanity | safe negative | 30.0 | 3.07/3.07/3.07 | 0.19/0.00 | 0.57 | 0.484 | 0.081 | 0.79/1.00 | 267.3 | 3.07/0.904 | REJECTED BY EXISTING CONNECTIVITY |
| Blank + parallel-rule sanity | safe negative | 30.0 | 3.07/3.07/3.07 | 0.19/0.00 | 0.57 | 0.484 | 0.081 | 0.79/1.00 | 267.3 | 3.07/0.904 | REJECTED BY EXISTING CONNECTIVITY |
| Continuous double-rule sanity | safe negative | 20.0 probe | 3.00/6.00/8.10 | 0.07/0.00 | 0.00 | 0.458 | 0.129 | 0.40/1.00 | 5496.7 | 8.10/0.830 | REJECTED AS DISTINCT RULES |

`D2-005` and the continuous double-rule control have no real candidate gap; their centered spans are diagnostic probes only and are marked as such in the JSON. The blank controls demonstrate an important limit: persistence outside a known unsupported gap is not connectivity through it and cannot override the existing rejection.

## Distribution and overlap findings

| Evidence family | Classification | Representative binary ranges (structural vs hard negative) | Interpretation |
|---|---|---|---|
| Axial persistence | PARTIAL_SIGNAL | local bilateral 1.05–5.04 vs 1.05–1.85; meso 2.07–7.82 vs 1.27–3.65; wide 2.18–7.82 vs 1.27–7.26 | Mean shift exists, but every scale overlaps and the wide negative maximum nearly reaches the positive maximum. |
| Transverse stability | NO_SIGNAL | wide width CV 0.62–0.95 vs 0.63–0.79; drift 0.41–0.95 vs 0.51–1.00 | Overlap is broad and direction is inconsistent. D2-006's mixed thick/thin stroke is a positive extreme. |
| Corridor occupancy | NO_SIGNAL | wide narrow 0.291–0.507 vs 0.274–0.382; side 0.066–0.206 vs 0.038–0.194 | Binary means differ slightly, but ranges overlap; raw-source occupancy reverses direction because surrounding page ink dominates. |
| Off-axis complexity | NO_SIGNAL | wide off-axis 0.328–0.979 vs 0.378–0.635; tortuosity 0.912–1.851 vs 1.305–1.479 | Genuine junctions and nodes can be more complex than the annotation cases. |
| Anisotropy | NO_SIGNAL | wide 120.5–609.5 vs 215.1–472.5 | Both classes are strongly linear and axis-aligned. |
| Long-range context | PARTIAL_SIGNAL | wide bilateral 2.18–7.82 vs 1.27–7.26; support 0.612–1.000 vs 0.663–1.000 | Some positives persist farther on average, but dimension rules can persist just as far. |

Every source and binary scalar range tested overlaps. The raw values and per-case distributions in `diagnostic-report.json` make that overlap explicit; it is not hidden behind a weighted score.

## Conclusion

- Robust interpretable separation: `NO`
- Handcrafted structural evidence insufficient: `YES`
- New evidence required: `YES`
- Next production change candidate: `NONE`
- Ready to implement: `NO`
- Production semantic delta: `NONE`
- Validation: `NO`
- Locked blind: `0 / 8`
