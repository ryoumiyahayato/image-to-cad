# Implementation clarification 2 — evidence granularity and identity input

The first real frozen-contract compatibility evaluation passed without a
change to its arithmetic bounds: 87 allowed diagnostic differences, zero
strict changes, zero out-of-interval values and zero ambiguous gates. Its
original v1 strict result remains FAIL. The exact first implementation SHA
and result are separately preserved; later code must not replace that identity.

The initial design's phrase "all intermediate enclosures ... retained" was
too broad. The implementation persists the final field intervals, spectral-gap
and normal-equation determinant bounds, gate records, every finite-segment-pair
classification and complete companion checks. The strict input samples and
published rational/outward-operation definitions allow other intermediates to
be regenerated; the report does not contain a trace of every arithmetic
operator. Important unresolved denominators, core spectral gaps, determinants,
finite parameters, deduplication distances and companion-angle boundaries now
also retain their failing bounds, named gate and available input indices.

An external expected legacy producer identity must be an explicit lowercase
64-character SHA-256. Missing/empty/malformed caller identities are rejected;
two absent producer keys cannot pass by comparing equal to a missing argument.
This changes identity validation, not diagnostic intervals or source geometry.

The PENDING integration retains unadopted raw paths and checks their complete
subtree strictly. Its replay reason is explicitly
`MATCHED_STRICT_REPLAY_OF_NUMERICALLY_PENDING_PLAN`, with numeric adoption status
`PENDING`. This is a successfully repeated negative decision, not a numeric
adoption approval or a legacy compatibility pass.
