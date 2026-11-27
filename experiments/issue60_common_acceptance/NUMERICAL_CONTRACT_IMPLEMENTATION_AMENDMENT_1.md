# Implementation clarification 1 — before the first compatibility evaluation

The original design file `NUMERICAL_CONTRACT_FROZEN.md` is retained unchanged
(SHA-256 `5d66cd10802ee91a6064f64a289b2d096e72fd7eafe6d5eb6ddc7c87a0a759bb`).
This addendum is frozen before the first evaluation of its numerical contract
against the real 87-field pair. The unchanged A producer has already reproduced
the original strict FAIL and exactly the same 87 differences. No diagnostic
interval membership test on that real pair has yet been executed.

The finite-parameter reference model explicitly includes **both** Cramer
quotients and ordinary partial-pivot 2x2 elimination. The enclosure is their
hull. Every subtraction, product, division and candidate pivot order is
evaluated with rational/outward-binary64 arithmetic. This records a concrete
second finite arithmetic chain corresponding to a common way to solve the
old 2x2 system; it is not a universal LAPACK error guarantee and has no fitted
absolute or ULP multiplier. A denominator interval containing zero or an
undecidable determinant/parameter/point-deduplication gate remains unresolved.
The entire segment-pair set, including discarded pairs, is examined.

All input coordinate differences, including companion endpoint axes, begin
with exact rational values of the supplied binary64 coordinates before the
first outward operation. Existing thresholds use their **binary64** values,
including `0.85`, `1e-9`, `1 + 1e-9` and `1e-7`; they are not silently replaced
with different decimal rational constants.

For a v2 component rejected by the new numeric guard, its complete raw
candidate paths are preserved as `numerical_pending_candidate_paths`, outside
the adopted `paths` set. That unresolved subtree has **no diagnostic whitelist**
and is compared strictly on replay. A matching negative plan may pass identity
replay while reporting `numeric_adoption_status=PENDING`; this cannot become a
numeric adoption approval. The legacy compatibility function never receives
this exception. It must certify its diagnostics and keep its original strict
FAIL visible.

The attached-end intersection constructor and native-fit geometric gates are
unchanged. This task's robust guard claim is confined to the enumerated
direction, competition, separation, companion, cycle residual/common-point,
finite-contact detection and deduplication checks. Exact comparison still
protects every actual endpoint and geometry outside that numerical scope.

Initial unit verification found two incorrectly specified ambiguity fixtures:
a simple vertical crossing and axis-aligned deduplication case were fully
decidable under exact binary64 input arithmetic. That run was **2 failed,
23 passed**. They were replaced with analytically constructed non-axis-aligned
boundary fixtures. The interval implementation was not widened to make these
tests or the real data pass. This failure is a test-expectation correction,
separate from the preserved real strict-replay FAIL.
