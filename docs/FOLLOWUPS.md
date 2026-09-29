# FOLLOWUPS — pre-existing issues found during the refactor (NOT fixed, by policy)

The refactor is behaviour-preserving: bugs found while moving code were kept
bug-for-bug and logged here to fix later as their own changes (each needs a
test first).

1. **RESOLVED — `api_stream_stop` no longer 500s before any manual recording.**
   It now reads `session.get("is_recording", False)`, like the record/start and
   record/stop routes. The key was deliberately NOT added to `_SESSION_DEFAULTS`:
   `_reset_session()` runs on every stream start and would clear the flag of a
   manual recording already in progress. Pinned by
   `test_stop_before_any_manual_recording_stops_the_session`.

2. **RESOLVED — code removed.** `pipeline_name` no longer exists in
   `api_stream_start`; the pipeline-upload removal took the dead variable
   with it.

3. **RESOLVED — moot.** `v_x_raw`/`v_y_raw` belonged to the old pipeline;
   quasi-v2's `run_pipeline` (piv/pipeline.py) has no such variables.

4. **RESOLVED — pipeline upload removed.** This item concerned
   `static_mode._load_pipeline_runner` executing uploaded Python by design.
   The custom-pipeline-upload feature has been removed from backend and
   frontend (the only pipeline is now quasi-v2 in `rtsp/piv/`), so this
   concern no longer applies.

5. **Frontend (from FRONTEND_MAP.md):** index_static.html shipped the entire
   live-dashboard JS as dead code (resolved naturally by the Phase-4 split);
   its top-level `#rtspUrl` keydown listener threw at page load (also gone
   after the split); its `<title>` still says "Stream Mode" (cosmetic, left
   as-is to keep the refactor behaviour-pure).

6. **O8 — on-site fixes (`b98ec53` on `on_site_changes`): capture part
   obsolete.** The OpenCV capture engine and preview grabber they patched
   (grabber.py, capture.py) were replaced by the always-on recorder
   (streaming/recorder.py, Sep 2026 — see WALKTHROUGH.md "Recording
   design"), so the grabber pause tracking, resume-between-retries and
   CAP_PROP_FPS sanity fallback no longer apply. The on-site fixes to the old
   built-in pipeline's `piv_runner.py` are similarly obsolete now: `rtsp/piv/pipeline.py`
   is quasi-v2 (Bodart 2024), a different implementation than what those fixes targeted,
   so check whether the underlying issue still applies there before porting anything.
   Also found during that rewrite: the manual-recording routes
   `POST /api/stream/record/start` and `/record/stop`, which the frontend
   calls, were missing from app_stream.py; they are restored on top of the
   recorder's buffer.

7. **RESOLVED.** `print_modbus_registers` prints Unicode box-drawing
   characters; when stdout is REDIRECTED (piped to a file/service log) on
   Windows, Python used to encode with cp1252 and the print raised
   UnicodeEncodeError, which propagated out of `run_pipeline` and killed the
   batch. Fixed: on `UnicodeEncodeError` the function now falls back to an
   ASCII-only rendering instead of raising. Pinned by
   `TestPrintSurvivesNonUnicodeStdout` in `rtsp/tests/unit/test_modbus.py`.

8. **`modbus_publisher.build_registers` TypeError on explicit None:** the
   `.get(key, 0.0)` defaults only cover *absent* keys — a results dict with
   `"mean_speed": None` raises TypeError. Pinned in tests/unit/test_modbus.py.

9. **Modbus status register (HR3) is hardcoded to DONE** — SCADA can never
   observe RUNNING/ERROR states even though the register map defines them.
   Pinned in tests/unit/test_modbus.py.

10. **`filter_velocity_field` edge cases** (pinned in tests/unit/test_filters.py):
    an all-zero or all-NaN speed field triggers an early return BEFORE any
    masking/logging — all-zero fields pass through unchanged; and when the
    valid-cell median is ≤ the 0.001 noise floor, spike removal is entirely
    disabled, so extreme outliers survive next to floor-level values.

11. **RESOLVED — not applicable here.** Branch cleanup concerned claude-test. The
   Playwright harness (`rtsp/automation/`) was deleted on 2026-09-29: it predated
   the JS module split, so its `startStream(cfg)` call ignored the calibration and
   every run failed with "At least 4 GCP pairs are required".
