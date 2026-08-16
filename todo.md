# Project TODO

- [x] Rebuild the React/Tailwind frontend while preserving the Python gateway and realtime protocol
- [x] Harden serialized cartela selection and deselection intent processing
- [x] Enforce durable realtime selection snapshots across players and admins
- [x] Enforce the strict server-authoritative 45-second selection window
- [x] Route late entries directly into spectator mode
- [x] Enforce one authoritative winning player and one winning cartela per round
- [x] Remove join-order bias from same-call winner tie-breaking with server-secret HMAC
- [x] Remove the premature 30-call no-winner refund behavior
- [x] Validate selection behavior under simulated lag and the 45-second boundary
- [x] Validate the corrected player-flow regression contract locally
- [x] Confirm refreshed GitHub CI for PR #47 is green
- [x] Merge PR #47 to main after CI passes
- [x] Delete the react-rebuild branch after merge
- [ ] Verify Render gateway health and frontend build timestamp (frontend reachable; gateway endpoint timed out from browser and sandbox probes)
- [x] Record the clarified requirement: fair random draws must determine the winner naturally; the engine must not preselect a user or cartela
