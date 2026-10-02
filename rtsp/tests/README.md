# rtsp/tests — running, layout, and the rules

## Running

```bash
python -m pytest                      # fast tiers (unit + component + API), ~15 s (233 tests, measured 2026-09-29)
python -m pytest -m golden            # numeric-stability gate (real pipeline, ~30 s)
python -m pytest rtsp/tests/unit -k geometry   # one area while debugging
```

CI (GitHub Actions) runs the fast tiers on every push and pull request.

## Layout — what guards what

| Dir | Guards |
|---|---|
| `unit/` | pure logic: piv filters/geometry/auto_params (P₀)/pipeline_config (`resolve_h_ref`)/intrinsics determinism (seeded RNG), Modbus registers, session semantics, static-mode job worker, clip fitness, camera ONVIF |
| `component/` | the capture engine's budget-countdown timing model, against a scripted fake camera (`fakes/fake_capture.py`); clip cutting and the recorder's stall-restart watchdog |
| `api/` | every HTTP route's contract: status codes, JSON shapes, state machine, CORS — hardware and pipeline faked |
| `golden/` | the measurement itself: real quasi-v2 pipeline on the Kunah fixture video, summary speeds plus `framestep_used`/`resolution_used` frozen in `expected.json`, and that the debug JSON (`piv/diagnostics.py`) is written |
| `conftest.py` | shared fixtures (`client`, `clean_state`) — orchestrated centrally; add local fixtures in your own test files |

`unit/` currently covers: `test_filters.py` (quality/velocity-field filters, F₀ spatial coherence),
`test_geometry.py` (AOI corner normalization), `test_auto_params.py` (P₀ auto resolution),
`test_pipeline_config.py` (`resolve_h_ref` precedence), `test_intrinsics_determinism.py` (seeded
`CameraConfig` focal-length fit, real pyorc, no video needed), `test_modbus.py` (register encoding,
ASCII-fallback printing), `test_session.py` (session snapshot/reset semantics), `test_static_mode.py`
(static-mode job worker, never calls the real pipeline), `test_clip_fitness.py`, `test_camera_onvif.py`
(replayed real SOAP fixtures, network hard-blocked).

## The rules (see also CLAUDE.md §5 — Tests Are Contracts)

1. **Never change a test to make code pass.** A failing test means the new
   code changed behavior something depends on. Root-cause it as a separate
   investigation. Do not weaken, skip, xfail, or delete your way to green.

2. **The one sanctioned test change — known-bug pins.** Tests referencing
   FOLLOWUPS.md items (e.g. names containing `KNOWN_BUG_FOLLOWUP_1`) assert
   the CURRENT buggy behavior on purpose. When you fix that bug, flipping its
   pin test to assert the correct behavior belongs in the SAME commit as the
   fix — that pair (fix + flipped pin) is the expected shape of a bug-fix
   commit. Flipping a pin without fixing the bug, or vice versa, is wrong.

3. **Golden regeneration protocol.** `expected.json` encodes physically
   validated numbers, not just reproducible ones. Regenerate ONLY on code
   whose output you have reason to trust (e.g. after manual field validation):

   ```bash
   python rtsp/tests/golden/generate_expected.py
   ```

   Commit the new `expected.json` in its own commit explaining WHY the numbers
   changed and why the new ones are correct. Requires the fixture video at
   `~/Desktop/Kunah_1.mp4` (or set `PRAVAH_GOLDEN_VIDEO`); the 187 MB video is
   deliberately not in git — the golden test skips gracefully without it.
   Note: the golden test no longer pins `use_stabilization=False` itself — the
   pipeline's own default is already off (`piv/pipeline.py`), so nothing
   overrides it. Stabilization is RANSAC-seeded and nondeterministic
   (~20% swings) if a caller enables it — see `docs/INCONSISTENCY_FINDINGS.md`
   [A2].

4. **Requirement changes.** If a requirement genuinely changed and an
   ordinary test now encodes an obsolete expectation, update that test in its
   own commit with a message explaining what changed and why — never bundled
   with the feature commit that broke it.
