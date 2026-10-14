# End-to-end source-support preservation design

This design audit traces the real optimized production path for DEV source
`A2-SG-009`. It replays the scanned-page contour suppression branch and requires
the replayed mask to equal the captured production `final_outline_layer`
pixel-for-pixel. No production decision or FinalStructure semantic is changed.

## First systematic divergence

Fallback eligibility and execution are not the upper/lower difference. All four
regions enter the unclaimed-source graphic fallback. The first systematic
recovery divergence occurs inside `suppress_scan_artifact_traces`: 156 upper-left
and 277 upper-right roots are rejected, versus two lower-left and zero lower-right
roots. Of 439 classified root removals, seven are direct damage roots, 430 are
roots swept into the damage cluster by proximity growth, and two are long sparse
flights.

The same-type D2-002/D2-003 comparison makes the lifecycle difference explicit.
Both targets have source, binary, raw, and eligible LINE evidence. Both are at
least partly rerouted to graphic fallback. The upper target's fallback is removed
by scan-artifact suppression and its FinalStructure target is absent; the lower
target's fallback survives and completes the fragmented native geometry.

## Architectural verdict

Pixel ownership is mutually exclusive. It does conserve every foreground pixel
at the ownership partition, so ownership alone is not the terminal broad-loss
stage. It does not conserve semantic lineage: after a LINE candidate is suppressed
or downgraded, the fallback receives anonymous contour pixels without the line's
source-support identity. The later damage classifier therefore cannot know that a
root contains previously verified drawing evidence.

The proposed `SourceSupportLifecycle` is a non-semantic evidence contract. It
carries source-space support, continuity, confidence, candidate derivations,
ownership claims, fallback decisions, downstream entity IDs, and an explicit
terminal fate. It never promotes pixels to CAD by itself.

The next safe production candidate is instrumentation only: emit stable lifecycle
IDs and terminal reasons across LINE detection, ownership, graphic fallback,
artifact suppression, and FinalStructure before changing any acceptance rule.
