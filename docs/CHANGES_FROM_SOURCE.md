# Changes from the source repo, and open TODOs

This repo was created on 2026-09-29 from `D:\pravah\claude-test`:

- app, UI and recorder: branch `feature/always-on-recorder` at `ffc2a35`
- app-side consistency fixes: branch `fix/piv-consistency-prep` at `6a17c12`
- algorithm: `runners/quasi_automated_bodart2024/quasi_v2/` (now `rtsp/piv/`)

## Removed

- The built-in pipeline (old `rtsp/piv/`) and the whole `runners/` folder. quasi-v2 is the only
  algorithm.
- The "upload custom pipeline" feature: the `pipeline` form field, `/api/pipelines`,
  `_load_pipeline_runner`, `pipeline_name` / `step_times` in responses, the upload control and
  `pipeline.js` in both UIs. The Pipeline bar shows a fixed `quasi-v2 (Bodart 2024)` tag.
- Every code comment and docstring. The rationale moved to `docs/CONTEXT.md`.
- `rtsp/automation/` (Playwright harness). It predated the JS module split: its
  `startStream(cfg)` call ignored the calibration, so every run failed with "At least 4 GCP pairs
  are required", on the source repo too.
- `rtsp/PROGRESS.md`, `gcp_calibration.html`, `docs/auto_gcp_plan.md`.

## Ported from `fix/piv-consistency-prep` into quasi-v2

Details and finding ids in `docs/INCONSISTENCY_FINDINGS.md` and `docs/CONTEXT.md`.

- `lens_position` is passed into `pyorc.CameraConfig`, so the focal-length fit uses it [A1].
- The `CameraConfig` build runs under a fixed numpy RNG seed, restored afterwards [A1].
- `resolve_h_ref`: nested `gcps.h_ref` (what the UI writes) is read [A3].
- Stabilization is off unless `use_stabilization` is true, in both modes [A2].
- Static mode sensor formula is `h_a = cam_z - distance_m`, same as stream mode [A3].
- fps outside 1..240 is replaced by 25 with a warning, and forced onto pyorc and P₃.
- Modbus printout falls back to ASCII on a stdout that cannot encode it.
- Per-batch config sha1 log line in stream mode.
- Diagnostics module and a per-run `<video>_debug.json` (camera model, GCP reprojection, time
  axis, PIV validity).
- Wrong-`pyorc`-package import guard (from on-site commit `b98ec53`). The rest of `b98ec53` is
  superseded by the always-on recorder and by P₀.

## Bugs found and fixed here (all also present in the source repo)

Each is pinned by a test that fails on the source code.

1. **quasi-v2 returned no measurement on Kunah.** P₀ (`compute_auto_resolution`) passed a
   non-contiguous array to `cv2.convexHull` whenever GCPs have a z value, which the UI always
   sends; the exception was swallowed and 0.05 m/px returned, so P₀ never ran in production. That
   made the ortho image 38×46 px, P₃'s 40 px test window failed, framestep fell back to 60, and
   every vector was masked out (NaN, then a crash). Now 0.01 m/px, framestep 8.
   Test: `rtsp/tests/unit/test_auto_params.py`.
2. **Stream mode rejected every 30 fps and 60 fps clip.** Recorder pieces are Matroska with a
   1 ms time base, so 60 fps intervals are stored as 17/17/16 ms; `measure_clip_timing` used
   `1 / median_interval` = 58.82 fps against a 0.5 % tolerance. Only 25 or 50 fps cameras passed.
   It now measures `(intervals + missing) / span`.
   Tests: `rtsp/tests/component/test_clip_integrity.py`.
3. **Stop returned HTTP 500** unless a manual recording had run first, leaving the session stuck
   in `stopping` with the recorder running (was FOLLOWUPS #1).
   Test: `test_stop_before_any_manual_recording_stops_the_session`.
4. **quasi-v2's parameter summary crashed on a cp1252 stdout** (Windows service log), losing a
   computed batch. Now falls back to ASCII.
   Test: `test_computed_params_summary_survives_a_stdout_that_cannot_encode_unicode`.
5. **An all-NaN result** now raises "No valid velocity vectors survived filtering…" after writing
   the debug JSON, instead of `cannot convert float NaN to integer` from the Modbus conversion.
6. `visualize` failures are logged instead of losing a computed batch.

## Verified on 2026-09-29

- Fast suite 237 passed; golden (quasi-v2 on Kunah) passes, and three runs under different global
  RNG seeds were bit-identical.
- Static mode through the real UI on Kunah: 0.066 / 0.153 / 0.279 m/s, images served.
- Stream mode against `rtsp_simulator.py` (constant 60 fps Kunah): clip accepted, quasi-v2
  result mean 0.138 m/s, Stop returns 200 and the session reaches `stopped`.

## TODO — needs a decision

- [ ] **Low coverage.** After pyorc's mask chain only ~36 of 621 grid cells produce a velocity on
      Kunah (5 on the stream clip). The numbers are reproducible but thin. No thresholds were
      changed; tuning the algorithm is an owner decision.
- [ ] **Golden numbers are reproducible, not field-validated.** Kunah: framestep 8, 0.01 m/px, mean
      0.0657, median 0.1529, max 0.2795 m/s. Mean is below median because the along-flow
      signed-magnitude aggregation counts a few upstream cells as negative.
- [ ] **Fixed camera intrinsics** (`use_fixed_intrinsics` + `camera_matrix`) existed in the old
      built-in pipeline but never in quasi-v2, and the UI never sets it. Port it once a site
      calibration is pinned; it removes the focal-length fit altogether.
- [ ] **Staff-gauge water height** (`water_height_method = "staff_gauge"`) imports
      `staff_gauge_reader`, which exists in neither repo. Build it or delete the branch.
- [ ] **Kunah GCP #4 reprojects 92 px off** and the solved camera sits 0.34 m from the entered
      one: with exactly 4 GCPs pyorc uses P3P, so the 4th GCP carries all the error. A 5th GCP or
      a re-survey is a field task [A11].
- [ ] **P₃ fails when the ortho image is smaller than its 40 px test window** and silently falls
      back to the maximum framestep. Fixed for Kunah by the P₀ fix, but still possible on a small
      AOI.
- [ ] **Real-camera run of the always-on recorder** is still outstanding; everything above was
      tested with the RTSP simulator.
