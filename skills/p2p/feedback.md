- Target: `p2p send` `transport_failed` code and instruction
- Requested change: `p2p send` should return the underlying `NSCocoaErrorDomain Code=640` / POSIX 28 error writing cmux state on a full boot volume, because the surfaced code and instruction direct agents toward cmux inspection and retry, neither of which can clear disk exhaustion.
- Reason: The surfaced code/instruction directs agents toward cmux inspection and retry, neither of which can clear disk exhaustion.
- Source: Two identical transport failures at 149 MiB free; the unchanged send succeeded after space was cleared. memory-routing-pipeline issue 05, fourth-correction report attempt; packet provenance: producer-run.md:1249, source-local id C31

- Target: the pinned title/surface pair that rejected a stable surface, and the shared tooling guidance at line 467
- Requested change: Stable `surface:285` accepted `issue08_verifier`, later rejected the same pinned title/surface pair because its current title was `verifier`, then succeeded when re-resolved by title alone back to the same surface; the prescribed explicit-surface remedy caused the bounce.
- Reason: The title was unstable while the surface stayed stable, the inverse of the recorded drift model; the prescribed explicit-surface remedy caused the bounce.
- Source: `peer_surface_mismatch` with `current_title: verifier`; successful `title_in_workspace` retry to `surface:285`; shared tooling guidance at line 467. issue-08 verification `08-verify-a1` messaging; packet provenance: producer-run.md:1820, source-local id C42

