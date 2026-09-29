# CONTEXT.md — rationale harvested from source comments

This repo enforces a no-comments rule in code. This file is where the "why" that used to live
in comments/docstrings now lives, organised by file path. Anchors are function/class/section
names, not line numbers (lines move; names don't).

---

## rtsp/app_stream.py

Flask app, HTTP routes and worker-thread wiring only — engine logic lives in `streaming/` and
`piv/`. Entry point unchanged: `python app_stream.py` → `localhost:5002`.

- Site camera config used during development: Matrix SATATYA MIBR50FL40CWP at `192.168.1.126`,
  user `admin`, password `Admin@161` (URL-encoded `Admin%40161`), RTSP path
  `rtsp://admin:Admin%40161@192.168.1.126:554/unicaststream/4` — Profile 4, MJPEG, 1920×1080,
  25 fps. Laptop Ethernet must be set to `192.168.1.100 / 255.255.255.0` (no gateway) to reach it.
- `from streaming.config import (...)` must be the first project import: `streaming.config` sets
  `OPENCV_FFMPEG_CAPTURE_OPTIONS` before `import cv2` and re-exports `cv2` for the whole app —
  this ordering is load-bearing (see `streaming/config.py` and WALKTHROUGH.md).
- `PREVIEW_FRESH_S = 5`: the recorder rewrites the preview on every keyframe (~1 s); a preview
  file older than 5 s means no video is currently arriving from the camera.
- Streaming default `use_stabilization=False`: fixed-mount cameras don't shake, so per-frame
  template-matching stabilization is skipped — it is expensive and unnecessary for this
  deployment; the user can still override it via `config`.
- `add_cors_headers`: CORS is restricted to an explicit allow-list of `localhost:5001/5002` (both
  `http`/`127.0.0.1` variants) — any other Origin gets no CORS headers at all, which surfaces to
  the browser as an opaque network failure, not a CORS error message.
- `api_stream_snapshot`: the returned JPEG is deliberately the same full-resolution keyframe the
  GCPs get marked on, and is written to `GCP_REFERENCE_PATH` so the fitness check
  (`clip_fitness.py`) has a fixed reference to detect camera movement against.
- `api_stream_probe`: waits up to `PROBE_WAIT_S = 20` s for a fresh preview before giving up, then
  reads codec/fps/resolution off the newest buffer piece via `ffprobe`.

### Known issues (PIV-CONSISTENCY, from `fix/piv-consistency-prep`, unmerged)

- **[A3]** The sensor is read **once**, at session start, and `h_a` is frozen into
  `_pipeline_config` for the whole session (which can run for hours). Water-level drift within a
  session is not tracked; re-reading per batch would need to happen in
  `streaming/processor.py` instead.
- **[A10]** `api_stream_config` sets `_drop_current_batch = True`, but nothing reads that key, and
  `warn_duration_changed` is never set — so the dashboard's "current batch dropped and restarted"
  message is currently unreachable. The recorder simply picks up the new duration at its next loop
  iteration. This is pinned by `tests/api/test_routes.py`; don't change the behaviour without
  updating that test.

---

### `api_stream_stop`

- Reads `session.get("is_recording", False)`. The key only exists once a manual recording has run,
  so indexing it made Stop return HTTP 500 and left the session stuck in `stopping` with the
  recorder still running (was FOLLOWUPS #1). The key is deliberately not added to
  `_SESSION_DEFAULTS`: `_reset_session()` runs on every stream start and would clear the flag of a
  manual recording already in progress.

## rtsp/modbus_publisher.py

Modbus register formatter for the pipeline's speed/status output — SCADA integration.

- **Current mode is print-only**: `print_modbus_registers(results)` after every `run_pipeline()`
  call prints what a SCADA system polling FC3 would read; no Modbus TCP server actually runs.
  A commented-out `ModbusServer` class (disabled) is the intended future path when SCADA
  integration is wanted — uncomment it, `pip install pymodbus>=3.6`, and call
  `modbus.update_results(results)` instead of the print.
- **Register map** (Modbus TCP, Unit ID 1, port 5020), all `uint16`:
  - `40001` Mean Speed, `40002` Max Speed, `40003` Median Speed — mm/s, scaled ×1000 (÷1000 → m/s)
  - `40004` Status — `0`=IDLE, `1`=RUNNING, `2`=DONE, `3`=ERROR (`build_registers` always writes
    `STATUS_DONE`; nothing currently sets RUNNING/ERROR — see Known issues)
  - `40005`/`40006` Timestamp high/low 16 bits of Unix epoch
  - `40007` Data Quality %, 0–100
- Encoding is scaled integer ×1000 — "industry standard for velocity instruments". Example:
  `1.847 m/s → register 1847 → SCADA reads 1847 ÷ 1000 = 1.847 m/s`. Max encodable speed is
  `65.535 m/s`, "well beyond any real river"; `_ms_to_uint16` clamps to `[0, 65535]` and negative
  speeds (which "should not occur") become 0.

### Known issues

- `build_registers`'s `.get(key, 0.0)` only supplies a default when the key is **absent** — an
  explicit `None` for `mean_speed`/etc. passes straight into `speed_ms * 1000` and raises
  `TypeError`. Pinned in `tests/unit/test_modbus.py`.
- HR3 (status) is hardcoded to `STATUS_DONE` in `build_registers` regardless of input — SCADA can
  never observe RUNNING/ERROR even though the register map defines them. Pinned in
  `tests/unit/test_modbus.py`.
- **[PIV-CONSISTENCY F5]** A redirected stdout on Windows (cp1252 service log) cannot encode the
  Unicode box-drawing characters in the printed table; `print_modbus_registers` degrades to ASCII
  (`output.encode("ascii", "replace").decode("ascii")`) rather than lose the batch that was
  already computed. See also FOLLOWUPS #7.

---

## rtsp/rtsp_simulator.py

Standalone dev tool: pushes a local video file into a MediaMTX RTSP server so the app can connect
to `rtsp://localhost:8554/test` without a physical camera.

- Video is passed through with `-c:v copy` (no re-encode), so source quality is preserved and no
  transcoding artifacts are introduced — matches how the real recorder treats the camera stream.
- `-re` (real-time rate) and `-stream_loop -1` simulate a continuously-live camera from a static
  file.
- GCP coordinate sign convention documented here for anyone calibrating against the simulator:
  origin is any GCP marked as origin in the UI; **X** positive = right in image, **Y** positive =
  into the image (away from camera), **Z** positive = up; values are entered in inches in the UI
  and converted to metres automatically.
- MediaMTX release asset naming convention encoded in `_mediamtx_asset_info`:
  `mediamtx_v*_windows_amd64.zip`, `mediamtx_v*_darwin_{amd64,arm64}.tar.gz`,
  `mediamtx_v*_linux_{amd64,arm64}.tar.gz`.

---

## rtsp/static_mode.py

Static (single-shot) counterpart to the live RTSP stream mode: upload a pre-recorded video, mark
GCPs, run quasi-v2 once. Exposed as a Flask Blueprint so it shares the host app's port (no separate
process/port 5001). Ported from `one_click_calculation/app.py`. There is no pipeline upload —
`from piv import run_pipeline` is a plain module-level import; the old `_load_pipeline_runner`
(dynamic-loading an uploaded `.py` under a unique module name) has been removed along with the
feature.

- `jobs`/`jobs_lock` is an **independent** job registry, deliberately separate from
  `app_stream`'s streaming `session` state — static-mode jobs and a live stream session never
  share state.
- `api_first_frame`: the first frame is decoded **server-side** with OpenCV rather than in the
  browser, because this app's own recordings use a codec (XVID/MPEG-4 ASP) that HTML5 `<video>`
  cannot play but OpenCV can — this lets the upload accept any codec the pipeline itself can read.
- `api_status`: schedules cleanup of the uploaded temp video via a 300 s `threading.Timer` once the
  client has observed a terminal (`done`/`error`) status once — gives the client time to see the
  final state before the file disappears.

### Known issues (PIV-CONSISTENCY)

- **[A3, fixed]** Static mode's sensor read now uses `cfg["h_a"] = cam_z - distance_m`, the same
  formula as `app_stream.py` — the two modes' sensor-derived `h_a` no longer disagree.
- **[A2]** `cfg.setdefault("use_stabilization", False)` deliberately matches `app_stream.py`'s
  stream-mode default, so the *same video* run through either page exercises the same physics.

---

## rtsp/streaming/config.py

Shared configuration, path constants, and one-time environment setup for the `streaming` package.

- **`OPENCV_FFMPEG_CAPTURE_OPTIONS` must be set before `import cv2`** — this is why
  `streaming.config` must be the first project import anywhere, and why every other module in the
  app imports `cv2` *from* `streaming.config` rather than importing it directly (this makes the
  ordering self-enforcing rather than relying on developer discipline).
- Capture options and why each exists:
  - `rtsp_transport;tcp` — reliable, ordered packets, avoids UDP packet loss on the site's flaky
    PoE link.
  - `timeout;5000000` **and** `stimeout;5000000` (both set, 5,000,000 µs = 5 s) — different FFmpeg
    builds honour different option names; this build's FFmpeg silently rejects `stimeout` and
    keeps the 30 s default if only `timeout` were set, which was previously causing 30 s-blocking
    reads and 1–3 s clips. Setting both is belt-and-braces.
  - `listen_timeout;5000000` — connection-phase timeout.
  - `max_delay;60000000` (60 s) — FFmpeg's internal reorder/demux buffer patience. Too small and
    any network jitter starves the decoder, causing stalls → reconnects → broken continuity. 60 s
    is generous but only costs RAM while actually buffering (~540 MB worst case at 1080p/30fps).
  - Historically this replaced `CAP_PROP_READ_TIMEOUT_MSEC`, which does nothing when set after
    `VideoCapture` construction — FFmpeg only reads these options at open time via the env var.
- Hardware note: captured video quality/continuity depends directly on the camera's encoding
  throughput and sustained network bandwidth. A camera advertising 1080p MJPEG @ 30 fps may not
  sustain it if its encoder or PoE link is underpowered — symptom is bursts of ~27 frames then 30 s
  stalls. Fix by lowering camera fps/resolution, switching to H.264 (~50× more bandwidth-efficient
  than MJPEG), or upgrading hardware.
- `_check_desktop_writable`: does a **real write test**, not just `os.access`, because
  `os.access` "can lie on Windows".
- `SNAPSHOT_CLIP_COUNT = 1`: number of clips saved per probe-triggered (Record button) run.
- `BATCH_COOLDOWN_S = 300`: fixed 5-minute gap between LSPIV batch recordings.

---

## rtsp/streaming/recorder.py

The always-on camera recorder — the **only** component in the app that opens the RTSP URL. One
ffmpeg process copies the stream (no decode/re-encode) into rolling 10-second MKV pieces, and in
the same process decodes only keyframes (~1/s) into a full-resolution preview JPEG. Every other
feature (Record button, LSPIV batches, manual recording, live preview, GCP capture) reads from the
buffer or the preview — the camera only ever serves one connection, and recording never depends on
CPU load.

- **Why MKV, not MP4**: an MP4 cut off mid-write is unreadable (no index); MKV stays readable.
- **Why timestamps reset per piece**: ffmpeg's concat demuxer assumes every input starts at 0 —
  without the reset, joined clips come out short.
- A piece counts as **finished** only once ffmpeg lists it in the run's CSV segment list, which
  also gives its exact stream-time span for contiguity checks.
- `read_run_pieces`: the **first piece of every run is skipped** — it starts mid-GOP (partial
  group-of-pictures), so its timeline begins at a non-zero offset that the concat join would turn
  into a gap.
- `PIECE_SECONDS = 10`; `MIN_RETENTION_S = 600` covers the default 60 s clip many times over — the
  UI allows clips up to 600 s, which need room for a whole clip plus the one currently being
  written.
- `STALL_TIMEOUT_S = 15`: ffmpeg's own `-timeout` does **not** reliably fire — observed on site as
  a recording frozen for 4+ minutes. If neither the newest piece nor the preview has changed for
  15 s, the process is killed and restarted.
- `PID_FILE_NAME = "recorder.pid"`: ffmpeg survives if the app process dies; the PID is persisted
  so the next start can stop that orphan instead of opening a second camera connection.
  `stop_orphaned_recorder` only kills the PID if its command line actually writes into this app's
  buffer directory — guards against a reused PID hitting an unrelated process.
- `reserve_clip_length`: retention floor becomes `max(MIN_RETENTION_S, 2 * clip_s)` — keeps at
  least two clips' worth of buffer for the requested clip length.
- `hold_pieces_since(wall_ts)`: never deletes pieces newer than `wall_ts` (used during manual
  recording); `None` releases the hold.
- `_prune_buffer`: the file-count cap (`retention_s // PIECE_SECONDS + 6`) is a safety net against
  clock-based pruning misbehaving on a clock jump, independent of the time-based cutoff.
- `build_recorder_command`: `-skip_frame nokey` only affects the keyframe-decode side (preview);
  the copied (`-c:v copy`) output is untouched by it.

---

## rtsp/streaming/batch_recorder.py

LSPIV batch thread: cuts one batch per cycle from the always-on recorder's buffer, rejects clips
that fail the quick integrity check, and queues clean batches for the pipeline processor.

- `not_before = time.time()` at the start of each cycle (and reset after every reject): only
  footage recorded **after** this point is eligible, so a batch never accidentally reuses stale
  buffered video from before the cycle began or from a previous rejected attempt.
- `MAX_FAILURES = 3`: after 3 consecutive rejected batch attempts the whole session is set to
  `error` rather than retrying forever.
- Fixed cooldown (`BATCH_COOLDOWN_S`, 5 min) between batches: processing runs within this window,
  and the next recording only starts once the cooldown expires — gives the pipeline plenty of time
  and keeps the cycle predictable for the operator.

---

## rtsp/streaming/processor.py

Pipeline processor thread: works through the clip queue oldest-first, running integrity → fitness
→ PIV for each queued batch.

- Pipeline timeout is `5 × batch_duration_s` (minimum 120 s): "PIV is CPU-heavy but should finish
  well within this window; if it doesn't, something is stuck."
- Fitness-check failures are swallowed (`_assess_fitness_or_none`): if the fitness check throws,
  PIV still runs, just without a fitness verdict — a broken fitness check must never block
  measurement.

### Known issues (PIV-CONSISTENCY)

- **[A7]** On pipeline timeout, the worker thread is **not actually killed** (Python cannot kill
  threads) — only `job_state["cancel"] = True` is set, which the pipeline only checks *between*
  steps. Step 5 (`get_piv()`) is the long step, so the "zombie" keeps burning CPU after
  `_processor_busy` is cleared and the next batch starts a **second concurrent pipeline** — this
  means a shared numpy global RNG, doubled CPU time, and more timeouts cascading. The `finally`
  block's `_cleanup_file(batch_path)` also races the zombie thread's own file reads.

---

## rtsp/streaming/clip_cutter.py

Cuts clips out of the recorder's rolling buffer by joining consecutive pieces with ffmpeg's concat
demuxer and stream copy — a clip is bit-identical to the camera's stream (no re-encode, no seam at
joins).

- `CONTIGUITY_TOLERANCE_S = 0.05`: pieces from one ffmpeg run are contiguous when one starts where
  the previous ended, within 0.05 s to allow for rounding in the segment list.
- `group_contiguous_pieces`: only pieces that follow each other with **no gap** are ever joined; a
  missing/broken piece or a run restart splits the buffer into separate chains, and a clip is never
  cut across a split.
- `cut_window_clips` (manual recording): a clip starts at a piece boundary, so up to one piece
  (10 s) **before** the requested start is included in the result; a gap in the buffer produces
  `_part1`, `_part2`, … outputs.

---

## rtsp/streaming/clip_fitness.py

Provisional "fit for LSPIV" score (0–10) for one river clip: does the clip have visible surface
texture, no glare, enough light, and an actually-moving pattern inside the area of interest; also
detects camera movement against the GCP reference frame.

- **Provisional / unvalidated**: thresholds and penalties come from "a small exploratory
  comparison (calm canal with stationary reflections vs. a turbulent river)" and have **not** been
  validated against measured discharge — treat the score as a triage hint, not a quality guarantee.
- Measured numbers behind the thresholds:
  - `VERY_STATIONARY_CORRELATION = 0.9` / `STATIONARY_CORRELATION = 0.7`: "calm canal measured
    ~0.99, turbulent river ~0.39" frame-to-frame correlation.
  - `MAX_CAMERA_SHIFT_PX = 3.0`: beyond this the GCP pixel positions no longer match the ground.
  - `PAIR_COUNT = 12` frame pairs, `FRAME_GAP = 10` frames apart — enough pairs to average out
    momentary waves/glints while staying cheap to decode; the gap is long enough for flowing water
    to visibly change between the two frames of a pair.
  - `WINDOW_PX = 64`: chosen to be comparable to an actual LSPIV interrogation window.
  - `MIN_WINDOW_INSIDE = 0.75`: windows mostly outside the AOI would measure the bank, not the
    water, so they're excluded from texture sampling.
  - `FLAT_STD = 3.0`: grey-level std below this is sensor noise, nothing trackable.
  - `SATURATED_GREY = 250`: pixels this bright are clipped glare with no pattern.
- `_read_frame_pairs`: decodes sequentially rather than seeking, because "seeking is slow and
  inexact on H.264"; stops decoding once the last needed frame is reached.
- `_score_surface`: a pattern that vanished completely between the two frames of a pair (zero std
  in the second frame) counts as correlation `0.0` rather than undefined — "a pattern that vanished
  completely has not 'stayed put'".
- `_camera_shift_px`: the water inside the AOI is blanked to the image mean in both the reference
  and current frame before phase correlation, because the water moves *by design* — only the
  static banks/structures should drive the shift estimate.
- `assess_clip_fitness`: with no `aoi_corners` configured, the whole frame is treated as water and
  blanked, so there is nothing static left to compare against — camera-movement checking is skipped
  and a reason is logged instead.

---

## rtsp/streaming/clip_integrity.py

"Is the file intact" checks, run on a finished clip, never during recording. The PIV pipeline
assumes a fixed time step `dt = 1/fps` between frames (`piv/pipeline.py` reads
`CAP_PROP_FPS`) — every check here protects that assumption or the picture content:

- **Duration** — ffmpeg can exit early on a network timeout.
- **Missing frames** (`MAX_MISSING_FRACTION = 0.005`) — a missing frame doubles one pair's real
  `dt`; averaged over the whole clip the resulting velocity bias is roughly the missing fraction,
  kept well under LSPIV's typical 5–10% uncertainty budget.
- **Max gap** (`MAX_GAP_S = 0.5`) — a stall signature, carried over from the old capture engine's
  intent.
- **Frame rate** (`MAX_FPS_ERROR_FRACTION = 0.005`) — the fps value OpenCV reports off the file
  metadata **is** the `dt` PIV will use; any mismatch with the frames' real arrival rate is a
  direct velocity bias.
- `measure_clip_timing` measures the real frame rate over the WHOLE clip,
  `(intervals + missing_frames) / (last_pts - first_pts)`, and uses the median interval only for gap
  detection. The recorder writes Matroska pieces, whose time base is 1 ms, so at 60 fps the stored
  intervals are 17/17/16 ms; the old `1 / median_interval` read 58.82 fps (2 % off) and rejected
  every 60 fps clip, and every 30 fps clip too (33/33/34 ms reads 30.30 fps, 1 % off). Only 25 or
  50 fps cameras passed. Found on 2026-09-29 by running a stream session against
  `rtsp_simulator.py` with a constant-60 fps stream. Pinned by the three `measure_clip_timing` tests
  and `test_clean_60fps_matroska_clip_passes` in `rtsp/tests/component/test_clip_integrity.py`. A
  camera that uniformly delivers fewer frames than it claims is still rejected.
- **Decoding** — one H.264 decode error smears until the next keyframe and can look like texture to
  PIV. ffmpeg's `"non monotonically increasing dts"` stderr lines are muxer timestamp warnings, not
  picture damage, and are explicitly excluded from the error count (`MUXER_WARNING`).
- The LSPIV recorder runs the quick check (`run_decode_check=False`, no decode pass) before
  queueing; the Record button and the processor run the full check (with decode pass).

---

## rtsp/streaming/clip_manifest.py

Writes a JSON record (`<clip>.json`) next to every kept clip — lets anyone judge a clip later
without the app: which camera settings, which software version, what the integrity/fitness checks
said, and the water level the LSPIV run assumed.

- `mask_url_password`: `rtsp://user:secret@host/...` → `rtsp://user:***@host/...` — the manifest
  and API responses never leak the camera password.
- `manifest_path.write_text(..., default=str)`: fitness metrics may hold numpy scalars, which
  `json.dumps` can't serialize directly — `default=str` degrades them instead of crashing the
  write.
- `read_software_version`: reads `git rev-parse --short HEAD`, cached with
  `functools.lru_cache(maxsize=1)` for the process lifetime.

---

## rtsp/streaming/clip_queue.py

Clips waiting for the LSPIV processor, one file per clip in `QUEUE_DIR`.

- Files are named `batch_<index>.mp4` with a zero-padded index specifically so that **filename
  sort order equals recording order** — the processor always takes the lexicographically-first
  (oldest) clip.
- `discard_queued_clips`: clips left over from an earlier session are deleted at the start of a new
  one, because they were recorded under a different configuration and their batch numbers would
  collide with the new session's numbering.

---

## rtsp/streaming/camera_onvif.py

Camera stream settings over ONVIF: read, compare against recommended, apply, and clock-sync.
Stdlib only (`urllib` + `xml.etree`).

- Every authenticated call sequence starts with an **unauthenticated** `GetSystemDateAndTime` call,
  because WS-Security `PasswordDigest` is checked against the **camera's** clock, and the site
  camera's clock "has been observed far off real time" — the offset must be measured before any
  signed request can succeed.
- `RECOMMENDED_STREAM_SETTINGS` rationale:
  - fixed **25 fps**: PIV needs a constant, known `dt` between frames.
  - **GOP 25**: one keyframe per second, so every 10 s buffer piece starts cleanly on a keyframe.
  - maximum **constant** bitrate (16384 kbps): the camera only offers H.264 Baseline profile, and a
    site measurement showed only "0.054 bits/pixel/frame at 8 Mbps" — compression artefacts wash
    out the surface texture PIV tracks at lower bitrates.
- Resolution and codec are **reported but never changed automatically** — changing either would
  invalidate the existing GCP calibration (`apply_recommended_stream_settings`,
  `describe_settings_mismatches` both enforce this; they only report a mismatch, never a fix).
- `MAX_CLOCK_OFFSET_S = 60`: camera clock drift beyond ±60 s from this machine is flagged as a
  mismatch.
- `_build_set_encoder_request`: sends the **full current configuration** with only the changed
  fields replaced (not a partial patch) — some cameras reject partial `SetVideoEncoderConfiguration`
  requests; `ForcePersistence` is set `true` so the change survives a camera reboot.

### Testing notes

- `tests/unit/test_camera_onvif.py`'s `FakeCamera` replays **real SOAP responses captured from the
  site camera** (Matrix MIBR50FL40CWP, firmware 4.5.0), stored under `tests/fixtures/onvif/` —
  these are recorded fixtures, not hand-written stubs, and `urlopen` is hard-blocked so no test can
  ever reach the real network.

---

## rtsp/streaming/session.py

Shared session + snapshot-recording state, locks, and the UI log — single owner of this state.

- `_MAX_LOG_ENTRIES = 200`: `_slog` trims `session["log"]` to the last 200 entries to prevent
  unbounded memory growth over a long-running session.
- `_MAX_RESULTS_IN_POLL = 50`: `_session_snapshot` sends only the most recent 50 results to the
  client per poll, to keep the response small; `total_batches_processed` still reflects the
  untrimmed count.
- `_session_snapshot` strips every key starting with `_` before sending to the client (internal
  signals like `_stop_event`, `_pipeline_config` never leak to the frontend).
- **Consume-once warning flags**: `warn_batch_dropped` and `warn_duration_changed` are read then
  immediately reset to `False` inside `_session_snapshot` — if the frontend polls twice before
  rendering the warning, the second poll misses it. Don't add more flags of this shape without
  understanding this pattern (also documented in WALKTHROUGH.md).
- `_reset_session` uses `session.update(deepcopy(_SESSION_DEFAULTS))`, which does **not** clear
  keys first — a key created at runtime but absent from `_SESSION_DEFAULTS` (e.g. `is_recording`,
  set by `_start_manual_recording`) **survives** a session reset. Production code relies on this
  in-place update rather than reassignment/clear (pinned in `tests/unit/test_session.py`).

---

## rtsp/streaming/manual_recorder.py

Manual recording: holds the recorder's buffer between Start and Stop, then saves the window.

- `STOP_WAIT_S = 15`: the buffer piece that will contain the stop moment is still being written
  when Stop is pressed (pieces are 10 s) — the stop handler waits for it to finish so the
  recording's tail is not lost.

---

## rtsp/streaming/snapshot_recorder.py

Record-button thread: cuts `SNAPSHOT_CLIP_COUNT` clip(s) from the always-on recorder's buffer after
the button press.

- Desktop writability is checked **before** recording anything (top priority) — a doomed recording
  should fail immediately, not after burning a full clip duration.
- Output folder uses `HH-MM` (not `HH:MM:SS`) because colons are not allowed in Windows paths.
- `MAX_SNAPSHOT_ATTEMPTS = 5`: a clip that fails the integrity check is moved to `not_considered/`
  and a fresh clip is cut from footage recorded after the rejection; after 5 failed attempts for one
  clip index the whole run is marked `failed`.

---

## rtsp/piv/defaults.py

Constants carried over "exact from `piv_runner_v3.py`" — i.e. deliberately kept identical to the
predecessor pipeline's tuning rather than re-derived: `PIV_CORR_MIN = 0.15`, `PIV_S2N_MIN = 1.15`,
`RESOLUTION = 0.05` m/px, `PIV_WINDOW_SIZE = 10`, `PIV_OVERLAP = 5`.

---

## rtsp/piv/geometry.py

`normalize_aoi_corners`: canonicalises 4 AOI corners into a consistent winding order (angle-sort
around the centroid → roll so the point with minimum `x+y` is first → flip to clockwise if needed)
regardless of the order corners were originally clicked in. `sanitize_dist_coeffs` zero-pads or
truncates any distortion-coefficient input to exactly 5 values for OpenCV. Both are pure/stateless;
their exact corner-ordering behaviour is pinned by `tests/unit/test_geometry.py` as "a
behaviour-preserving pin, not a spec for 'correct' geometry" — i.e. the ordering is whatever the
algorithm produces, not independently justified.

---

## rtsp/piv/flow_direction.py

Estimates the dominant flow direction automatically from the PIV velocity field — no manual
upstream/downstream marking required.

- `compute_flow_direction_auto`: uses **magnitude-weighted PCA** on the `(v_x, v_y)` cloud — the
  principal eigenvector of the weighted covariance is the dominant flow axis. The axis is 180°
  ambiguous by construction; the sign (upstream vs downstream) is resolved separately using the
  weighted **net** vector. When a per-cell correlation field is supplied, cells are additionally
  weighted by correlation so noisy vectors contribute less.
- `coherence` return value is in `[0.5, 1.0]`: the fraction of variance along the principal axis.
  Near 1.0 = sharply defined direction; near 0.5 = the field has no clear flow axis. Coherence
  `>= 0.7` is logged as "well-defined", otherwise "weak — interpret v_along with caution".
- `project_velocities_along_flow`: decomposes each cell's vector into along-flow (`v_along`) and
  cross-flow (`v_cross`) components against the estimated unit vector.

---

## rtsp/piv/water_mask.py

- `restrict_grid_to_water` (P₁): masks out PIV grid cells outside the water area, using the first
  orthorectified frame's non-NaN mask (NaN = outside the AOI after projection) resized to PIV grid
  resolution with nearest-neighbour interpolation. Purpose: "prevents fake near-zero velocities
  from contaminating the average" — land/vegetation cells would otherwise pull the mean toward
  zero.
- `compute_sa_from_spots` (P₂, quasi-automated mode only): computes the PIV searching-area size
  from manually spotted particle displacements. Paper formula: `SA_downstream = 2 ×
  max_streamwise_displacement`, `SA_spanwise = 2 × max_spanwise_displacement`, `SA_upstream = 1`
  pixel (always, per paper). Falls back to `{40, 1, 20}` px if no spots are provided.

---

## rtsp/piv/discharge.py

`compute_discharge`: velocity-area method per **ISO 748:2021**, as used in Bodart 2024.

- For each transect point: find the nearest PIV grid cell, take `sqrt(vx²+vy²)` (or the
  caller-supplied along-flow speed grid, preferred when available since it's directionally
  correct), depth-averaged velocity = `alpha × surface_speed`.
- **Mid-section method**: `Q = Σ v_depth[i] × depth[i] × width_segment[i]`, where each point's
  width segment is the average of its left and right half-widths to its transect neighbours.
- Missing (NaN) interior transect points are linearly interpolated from neighbouring valid points;
  **both endpoints are forced to `v = 0`** — the standard zero-velocity-at-bank assumption.
- Requires at least 2 transect points and at least 2 valid (non-NaN) PIV cells along the transect,
  else discharge is skipped (empty dict returned) rather than raising.

---

## rtsp/piv/filters.py

`quality_filter_piv`: v2-style `corr`/`s2n` threshold mask — used only as a **fallback** when
pyorc's own `velocimetry` mask accessor is unavailable (`pipeline.py` prefers pyorc's own mask
chain when present).

`filter_velocity_field`: safety-net time-averaged-cell filter (thresholds are the "relaxed v3
thresholds" — deliberately looser than an earlier stricter version). Rejects, in order: exact-zero
cells, noise (`speed < 0.001` and not already zero/NaN), and spikes (`speed > 5.0 × median` of the
surviving valid cells, only evaluated when that median is `> 0.001`).

`apply_spatial_coherence_filter` (F₀ — Westerweel & Scarano 2005 median test, applied **per
timestep**, before time-averaging): for each vector, compare it to the median of its 8 neighbours;
normalize the residual by the neighbours' own residual-median (`+ epsilon` to avoid divide-by-zero);
flag as outlier when the normalized residual exceeds `residual_threshold` (default `2.0`). The
`_median_test_2d_fast` implementation deliberately replaced an earlier "pure-Python triple nested
loop" (O(rows×cols×9) per timestep) with `scipy.ndimage.generic_filter`, which "runs fully in C".

`_compute_adaptive_quality_thresholds`: derives `corr_min`/`s2n_min` from the **actual PIV output
distribution** for this run rather than using fixed constants — "fixed thresholds ... may be too
tight or too loose for a specific site." Uses the `(1 − keep_fraction)` percentile (default
`keep_fraction = 0.85` → 15th-percentile cutoff, i.e. drop the bottom 15% of cells) as the
rejection threshold, clamped to `corr_min ∈ [0.05, 0.60]`, `s2n_min ∈ [1.05, 2.00]`. Falls back to
the module defaults (`PIV_CORR_MIN`, `PIV_S2N_MIN`) when fewer than 10 valid cells are available.

---

## rtsp/piv/auto_params.py

`compute_auto_resolution` (P₀): `r_ortho = sqrt(A_m / A_pixel)` — real-world convex-hull area of
the GCP destination points divided by pixel convex-hull area of the GCP source points, i.e. metres
per pixel implied by GCP density. Clamped to `[0.01, 0.5]` m/px; falls back to the default
`RESOLUTION` (0.05) on any failure (degenerate hull, etc.).

- **[A4/A11 investigation finding, now fixed]**: with 3-D GCP world points (what the UI always
  sends), `dst[:, :2]` was a non-contiguous array, `cv2.convexHull` raised, and the bare `except`
  silently returned the 0.05 m/px fallback — so P₀ never actually ran in production. Fixed with
  `np.ascontiguousarray` on the 2-D slice. On the Kunah fixture P₀ now gives 0.01 m/px (the clip
  floor) instead of the 0.05 fallback. Pinned by `rtsp/tests/unit/test_auto_params.py`.
- **Known limitation**: `compute_auto_framestep`'s base PIV run uses a fixed `test_ia = 40` px test
  window; if the ortho image is smaller than that (a very fine P₀ resolution on a small AOI), P₃
  fails and silently falls back to `max_framestep` (≈1 s temporal gap) — this is exactly what
  happened on the Kunah fixture before the P₀ fix above landed.

`compute_auto_framestep` (P₃ — Bodart 2024 §3.1, "faithfully reproduced"): iteratively finds the
smallest framestep where enough PIV cells show sufficient pixel displacement.

- Two distinct thresholds per the paper: `spurious_threshold_px = 0.75` px pre-filters out
  near-zero spurious vectors entirely before the target check; `min_displacement_px = 3.0` px is
  the actual target. `target_fraction = 0.50` (median of *surviving* cells > 3 px) — deliberately
  **relaxed** from Bodart's stricter 0.75-fraction/first-quartile rule, because "a field with
  normal spatial speed variation almost never meets" the strict rule, which would make the search
  always fall through to `max_framestep` instead of converging.
- `max_framestep` auto-computed as `max(30, round(fps))` when not given: allows up to ~1 s of
  temporal lag at any frame rate — needed for slow flows (worked example: 0.3 m/s at 60 fps needs
  framestep ≈ 36 to reach 3 px displacement at 0.05 m/px).
- **Performance optimization**: PIV is run **once** at framestep=1 (not once per candidate
  framestep, which would be O(max_framestep²) in frames processed) — velocity from pyorc is in m/s,
  independent of framestep, so `disp_px(fs) = speed_ms / resolution × fs / fps` scales linearly;
  displacement at every other candidate framestep is derived by scaling the fs=1 result rather than
  re-running PIV.
- `fps_override` (passed from `pipeline.py` only when `CAP_PROP_FPS` was out of range and forced to
  25.0) is threaded through so the P₃ search and pyorc's own time axis agree on fps.

`compute_auto_piv_params`: auto-sizes the PIV interrogation window.
- With a P₃ speed estimate: **1/4-rule** — `window >= 4 × displacement_px`, rounded up to the next
  power of 2, clamped to `[16, 128]` px (so the tracked particle stays inside the window).
- Without a speed estimate (fallback): `target_ia_metres (0.3 m) / resolution`, clamped to
  `[8, 64]` px.
- Overlap is always 50% of the window size in both cases.
- `corr_min`/`s2n_min` are **not** set here — computed adaptively from the real PIV output
  afterwards (see `filters.py`).

---

### `_print_computed_params` output encoding

- The summary table uses box-drawing characters. When stdout cannot encode them (a Windows service
  log on cp1252, or any redirected stdout), the print falls back to ASCII instead of raising
  `UnicodeEncodeError` after the numbers already exist, which used to lose the whole batch. Same
  fix as `print_modbus_registers`. Pinned by
  `test_computed_params_summary_survives_a_stdout_that_cannot_encode_unicode`.

## rtsp/piv/pipeline.py

`run_pipeline` — Assisted / Quasi-Automated LSPIV per **Bodart, J. et al. (2024), "A framework for
quasi-automated large-scale particle image velocimetry (LSPIV) discharge measurements," Water
Resources Research**, https://doi.org/10.1029/2023WR036198. Same `run_pipeline()` signature as the
predecessor `piv_runner_v3.py` (drop-in replacement contract).

- Three workflow modes (`config["lspiv_workflow"]`, default `"quasi_automated"` so omitting the key
  never silently degrades to manual): `"manual"` (identical to v3, no auto tools), `"assisted"`
  (P₀ auto resolution, P₁ water-only grid, P₃ auto framestep, F₀ spatial coherence, F₅
  time-median), `"quasi_automated"` (all of the above **plus** P₂ SA-from-spots).
  `quasi_automated` is **always** fully automated even if the config is internally inconsistent
  (`is_auto = is_quasi or workflow == "assisted"`).
- Water height: `water_height_method = "staff_gauge"` path calls an optional
  `staff_gauge_reader.staff_gauge_estimator.StaffGaugeEstimator`; if its confidence is
  `< 0.4`, it falls back to the config's manual `h_a` if present, else raises. If the
  `staff_gauge_reader` package itself can't be imported, same fallback-or-raise logic applies. This
  keeps staff-gauge auto-detection strictly optional infrastructure.
- GCP mode: 3D calibration needs `>= 6` pairs in pyorc; with 3D destination points but fewer than 6
  pairs, the pipeline auto-downgrades to 2D rather than failing.
- `_prelim_window`/`CameraConfig(window_size=...)` is **ortho-grid metadata only**, refined later —
  it is *not* the actual PIV window; the real PIV window comes from the explicit `window_size=`
  argument to `get_piv()`. Do not conflate the two (also called out in WALKTHROUGH.md).
- Frame-budget guard: warns (does not fail) when the achievable frame-pair count at the chosen
  framestep is `< 25`, since "time aggregate may be noisy" below that.
- The "angle" pyorc mask (directional filtering) is deliberately **skipped** in the pre-aggregation
  mask chain, because the flow direction is only known **after** aggregation (it's estimated from
  the aggregated field itself, not before).
- **F₅ time aggregation**: median for `assisted`/`quasi_automated` ("robust to outliers"), mean for
  `manual` (matches v3 exactly).
- **Final surface speed = "signed-magnitude along flow"**: for every frame, take the vector
  *magnitude* and give it the *sign* of its along-flow-direction dot product, then aggregate that
  scalar over time (median or mean per F₅). Rationale: at low displacement, frame-to-frame angular
  scatter is mostly PIV correlation noise, so a noise-jittered vector should still contribute its
  full speed (stays positive); only a genuine >90° reversal (a real back-eddy) flips negative and
  correctly subtracts. This avoids the directional-cancellation under-estimate that plain
  `|time-mean vector|` magnitude produces — the vector-magnitude value is kept only as a reference
  (`vector_mean_speed`/`vector_median_speed`), explicitly noted in logs as "under-reads when
  noisy".
- `print_modbus_registers(...)` (import from `modbus_publisher`) is called unconditionally at the
  end of every run — this is the print-only SCADA-format snapshot, not a live server (see
  `modbus_publisher.py`).

### Fixes ported from the run-to-run inconsistency investigation (`docs/INCONSISTENCY_FINDINGS.md`)

- **[A1] `lens_position` is passed INTO `pyorc.CameraConfig(...)`**, not only set afterwards via
  `set_lens_position()`. pyorc runs its focal-length calibration inside `CameraConfig.__init__`;
  a later `set_lens_position()` call only assigns an attribute the calibration never reads. Without
  the camera position as a constraint, the focal-length fit saw only coplanar GCPs and landed
  arbitrarily. `set_lens_position()` is still called afterwards for parity/plotting helpers, but the
  constrained fit already happened inside `__init__`.
- **[A1]** The `CameraConfig` build is wrapped in `_seeded_numpy_rng(INTRINSICS_RNG_SEED)`
  (`piv/defaults.py`, seed `0`): pyorc's focal-length fit is `scipy.differential_evolution` called
  with no seed, so it draws from numpy's **global** `RandomState`. The context manager seeds that
  global state for the build and restores the previous state afterwards, even on exception, so `fx`
  becomes a pure function of the config instead of whatever the caller's RNG state happened to be.
  Pinned by `rtsp/tests/unit/test_intrinsics_determinism.py` (real pyorc, no video needed).
- **[A3]** `resolve_h_ref(config, h_a)`: precedence is top-level `config["h_ref"]` > nested
  `config["gcps"]["h_ref"]` (what both UIs write, see `static/js/shared/config.js`) > `h_a`. pyorc
  places the water plane at `z_0 + (h_a - h_ref)`; before this fix the nested key was never read, so
  a sensor-updated `h_a` never moved the plane. Pinned by `test_pipeline_config.py`.
- **[A2]** Stabilization is off unless `config["use_stabilization"]` is `true`. pyorc's `stabilize`
  polygon marks everything **outside** it as rigid land for feature tracking, and the app passes the
  AOI (a rectangle inside the river) as that polygon — so with stabilization on, open water outside
  the AOI gets tracked as "stable" ground. A WARNING is logged when a caller enables it anyway.
  Both `app_stream.py` and `static_mode.py` `setdefault("use_stabilization", False)`, so the two
  modes agree by default.
- **fps sanitising**: `cv2.CAP_PROP_FPS` outside `1..240` is treated as unreliable — forced to
  `25.0` with a WARNING — and that forced value is then passed both to `pyorc.Video(fps=...)` and
  into P₃'s `compute_auto_framestep(..., fps_override=...)`, so the auto-framestep search and
  pyorc's own time axis agree on what fps means. When the file's reported fps is sane, nothing is
  forced and pyorc reads its own time coordinate as usual.
- **pyorc import guard**: at import time, if the installed `pyorc` package has no `CameraConfig`
  attribute, it's the wrong PyPI package (Apache ORC, not pyOpenRiverCam) — raises immediately with
  the install fix (`pip uninstall pyorc && pip install pyopenrivercam`) instead of failing later with
  a confusing `AttributeError`.
- `visualize()` failures are caught and logged as a WARNING rather than losing an already-computed
  batch; `result_image_path`/`camera_overlay_path` in the returned dict are `None` when the
  corresponding file wasn't written, rather than a stale/missing path.
- If no velocity vector survives filtering (`mean_surface` is NaN), the pipeline still writes the
  per-run debug JSON before raising a clear `RuntimeError` ("No valid velocity vectors survived
  filtering…") — this replaces the old obscure `ValueError: cannot convert float NaN to integer`
  that used to surface from the Modbus register conversion further downstream.

---

## rtsp/piv/diagnostics.py

Log-only diagnostics gathered around each pipeline run — **never changes the numbers**, purely
observability added by the run-to-run inconsistency investigation
(`docs/INCONSISTENCY_FINDINGS.md`).

- `env_versions`/`config_sha1`: Python/numpy/cv2/pyorc(/scipy) versions and a sha1 of the run's
  config — the same config hash across two runs means the same inputs reached the pipeline, which
  narrows "why did the number change" to code or RNG rather than a silently different config.
- `rng_fingerprint`: a sha1 of numpy's global `RandomState` right before the `CameraConfig` build,
  logged alongside a note that the build itself runs under the fixed `INTRINSICS_RNG_SEED`, so this
  fingerprint is informational, not a source of variance any more (see [A1] in `pipeline.py`).
- `log_camera_model`: solved camera intrinsics (fx/fy/cx/cy, distortion coeffs); solved-vs-entered
  camera position with a WARNING when they differ by `> 0.5` m; per-GCP reprojection error with a
  WARNING when any point is `> 10` px off; the solved water plane `z_a`. Per **[A11]**, with exactly
  4 GCPs pyorc uses `cv2.SOLVEPNP_P3P`, which fits 3 points exactly and dumps all residual error onto
  the 4th — a 5th GCP lets pyorc switch to iterative least squares and spread the residual instead.
- `log_time_axis`: frame-count/span/dt min-median-max for the video's time coordinate, and a count of
  gaps `> 1.5×` the median dt — surfaces dropped-frame gaps in the recorded file without changing how
  pyorc uses the (correct, per-pair) dt.
- `log_piv_stats`: PIV validity stats (valid fraction, cells valid in all pairs / in `< half` /
  in none, corr/s2n percentiles) — called once on the raw PIV output and once after masking, so a
  log diff shows exactly what the mask chain removed.
- `write_debug_json`: writes `<video stem>_debug.json` next to the result PNG in the run's output
  directory, and its resolved path is returned from `run_pipeline` as `debug_json_path`.

---

## rtsp/static/js/shared/config.js

`buildStreamConfig`: assembles the PIV config JSON the backend consumes, converting all user input
from inches to metres (`_inToM`, `× 0.0254`) and offsetting every GCP destination point so the
chosen origin GCP becomes `(0, 0, 0)`.

### Known issues (PIV-CONSISTENCY)

- **[A3, fixed]** `z_0`/`h_ref`/`h_a` semantics: `z_0` = water elevation when the GCPs were
  surveyed; `h_ref` = gauge reading at that survey time; `h_a` = gauge reading for *this* video.
  This file writes `h_ref` nested inside `gcps` (not at the top level); the backend
  (`rtsp/piv/pipeline.py`'s `resolve_h_ref`) now reads top-level `h_ref` first, then falls back to
  this nested `gcps.h_ref`, then to `h_a` — so the value this file sends is read correctly.

---

## rtsp/static/js/shared/state.js

Single shared mutable-state object (`S`) used across every ES module. Under native ES modules, a
plain `import { x }` binding is read-only for the importer, so all cross-module reads/writes go
through properties of this one object instead of individual top-level `let`s.

---

## rtsp/static/js/static_mode/main.js, upload.js, preview.js, results.js

Static-mode page composition, ported from the original single-file `index_static.html`. There is no
`pipeline.js` here — pipeline upload was removed from both frontend and backend; the Pipeline bar
shows a fixed `quasi-v2 (Bodart 2024)` tag.

- The entire live-dashboard JS (charts, feed, badges, status polling, save-bar, RTSP probe/preview
  machinery, session-end overlay, warning banner, step-2 raw recording, `patchDuration`,
  `stopStream`) and a top-level `#rtspUrl` keydown listener that used to throw at load are
  deliberately **excluded** from static mode — none of it is reachable from any static-page inline
  handler or the init/`DOMContentLoaded` code.
- `results.js` `startStream` (static): does **one run** of quasi-v2 on the uploaded video and
  creates a single result card. `escapeHtml` lives here too, used only by `createResultCard`.
- Static mode starts directly at the video-upload step (`showStep(2)`) — there is no RTSP
  mode-select step in this flow.

---

## rtsp/static/js/stream/camera_settings.js

Camera ONVIF settings panel, shown after a successful RTSP probe.

- Writes (apply recommended settings / sync clock) only happen after a `window.confirm()` that
  states exactly which fields will change — no silent camera writes.
- If the camera doesn't answer ONVIF at all, only a muted "unavailable" line is shown; the rest of
  the wizard is never blocked by a missing ONVIF response.

## rtsp/static/js/stream/recorder_status.js

Polls `/api/stream/recorder_status` every 3 s to render the always-on recorder's health in the
page header. `RECORDER_STALL_AGE_S = 20` / `RECORDER_FIRST_PIECE_GRACE_S = 30`: before the very
first piece has ever arrived, the "stalled" warning is suppressed for 30 s (grace period) rather
than immediately firing; after at least one piece has arrived, staleness is judged by the newest
piece's age exceeding 20 s. The RTSP URL in the response is deliberately never displayed (avoids
leaking camera credentials into the UI even though the server already masks the password).

---

## rtsp/static/assets/colors_and_type.css

Design-system token file. Palette philosophy stated in the file's own opening banner: "Instrument-
grade authority, inspired by water" — neutrals are warm/sand-tinted, "never cold grey"; the brand
water palette is "named like hydrology strata: shallow → deep." The `--flow-*` scale is
specifically for heatmaps ("Velocity / data scale ... Cool → warm, reads as flow speed").

---

## rtsp/templates/index_static.html, index_stream.html

Both pages retired a former "step 5" — its sensor configuration UI was merged into step 4b, so the
step numbering intentionally has a gap (`step5 retired`) rather than being renumbered.

---

## Application/run_app.bat, Application/run_app.sh

Both scripts `cd` to the repo root first (`cd /d "%~dp0.."` / `cd "$(dirname "$0")/.."`) because
they live inside `Application/` but need to run `pip install -r requirements.txt` from the repo
root and then `cd rtsp && python app_stream.py` — the relative path assumption depends on the
script's own location, not the caller's working directory.

---

## pytest.ini

`golden` marker is excluded by default (`addopts = -m "not golden"`) — it is a "slow
numeric-stability test running the real pyorc pipeline on the Kunah fixture video," opt-in via
`pytest -m golden`.

---

## .gitignore

- `rtsp/static/*` is ignored wholesale, with `!rtsp/static/css/` and `!rtsp/static/js/`
  re-included — `rtsp/static` mixes generated output (`results/`) with tracked frontend source
  (`css/`, `js/`), so the blanket ignore plus explicit un-ignores is intentional, not an oversight.
- `rtsp/recordings/` (recorder buffer, queued clips, manual recordings) is ignored — all generated
  video, never committed.

---

## .github/workflows/tests.yml

- `push` runs only on `master` (post-merge check); PR branches run once via the `pull_request`
  trigger — avoids double-running the same commit on every push to an open PR branch.
- `opencv-python` (non-headless) needs `libgl1`/`libglib2.0-0` installed on a bare Ubuntu runner —
  without them, the import fails at collection time, not at first use.
- The golden test tier is excluded by `pytest.ini`'s default `-m "not golden"`, and additionally
  self-skips without the Kunah fixture video (which is intentionally not in git) — CI never
  attempts to run it even by accident.

---

## rtsp/tests/conftest.py

- `RTSP_DIR` is inserted onto `sys.path` so `import app_stream`, `import piv`, `import streaming`
  work when pytest is invoked from the repo root rather than from inside `rtsp/`.
- The `client` fixture deliberately does **not** enable Flask `TESTING` mode, so unhandled
  exceptions surface as HTTP 500 exactly as in production — several tests pin that exact behaviour
  (see `rtsp/tests/api/` known-bug tests below).
- `clean_state` resets `session`, `_snapshot_rec` and `static_mode.jobs` to their fresh-process
  shapes **before and after** each test — specifically to `deepcopy(_SESSION_DEFAULTS)` with *no
  extra keys*, matching what a truly fresh interpreter looks like (e.g. `is_recording` does not
  exist yet, matching the FOLLOWUPS #1 bug precondition).

---

## rtsp/tests/api/ (test_camera_routes.py, test_recorder_routes.py, test_routes.py, test_static_routes.py)

API contract tests — every test **pins** current route behaviour (status codes, JSON shape, the
session state machine) with all hardware/worker threads faked out; no source file is ever modified
by a test, and known bugs are pinned, not fixed, with a comment pointing at `FOLLOWUPS.md`.

- Monkeypatching happens in the `app_stream`/`static_mode` module namespace (not the original
  defining module) because those files use `from ... import X`, which imports the *name* into
  their own namespace — route bodies resolve it as `app_stream.X`, so patching has to target that.
- `test_stop_before_manual_recording_500s_KNOWN_BUG_FOLLOWUP_1`: deliberately reaches the branch
  where `session["is_recording"]` is read before that key has ever been created, reproducing
  FOLLOWUPS #1's `KeyError` → HTTP 500. Explicitly must be updated when that followup is fixed.
- `test_write_*` tests confirm `/api/camera/settings/apply` and `/api/camera/clock/sync` both
  refuse any write unless the JSON body has `"confirm": true` exactly (boolean `True`, not
  `"true"`/`1`) — a deliberate anti-accidental-write gate at the validation layer.
- Static-mode's fake pipeline/tests redirect `RESULTS_ROOT` to a `tmp_path` so real uploads/results
  are never touched or polluted by test runs.

---

## rtsp/tests/component/ (test_clip_cutter.py, test_clip_integrity.py, test_recorder.py)

- `test_clip_cutter.py` builds fake recorder runs with real ffmpeg (`testsrc` lavfi source,
  `-bf 0` to match the camera's no-B-frames profile), then renames pieces into the recorder's
  wall-clock naming scheme — verifies the join produces the exact expected frame count and a
  max-gap equal to one frame interval.
- `test_recorder.py`'s watchdog test stands a **real subprocess** in for ffmpeg (a Python process
  that writes nothing and exits on stdin `"q"`, mirroring ffmpeg's own graceful-quit protocol) to
  verify the stall-restart loop end-to-end without needing a camera. A regression test specifically
  covers `start_recording` no longer deleting the orphan's PID file before checking it (which used
  to let a crashed app's ffmpeg survive and give the camera two connections).

---

## rtsp/tests/unit/ (test_camera_onvif.py, test_clip_fitness.py, test_filters.py, test_geometry.py, test_modbus.py, test_session.py, test_static_mode.py)

- `test_static_mode.py`'s **absolute rule**: never call the real PIV pipeline — every runner used
  in these tests is either a fake callable passed via `runner_func`, or a tiny throwaway `.py`
  script written to `tmp_path`, never the real pipeline module.
- `test_filters.py` pins `filter_velocity_field`'s actual thresholds: noise `< 0.001` (strict),
  spike `> 5×` median (strict), spike removal disabled entirely when the valid-cell median is
  `<= 0.001`.
- `test_geometry.py` explicitly frames itself as pinning *whatever the algorithm produces*, not an
  independently-derived "correct" geometry spec.
- `test_modbus.py` pins the `None`-vs-absent-key `TypeError` and the hardcoded `STATUS_DONE` — both
  cross-referenced to `modbus_publisher.py`'s Known issues above.

---

## rtsp/tests/golden/ (generate_expected.py, test_pipeline_golden.py)

Tier-4 "golden" numeric-stability test: runs the real pipeline on a real field video (`Kunah_1.mp4`,
187 MB, deliberately not committed — resolved via `$PRAVAH_GOLDEN_VIDEO` or
`~/Desktop/Kunah_1.mp4`) against a frozen `expected.json` snapshot, to catch "I accidentally changed
the numbers."

- Determinism: stabilization uses RANSAC (randomly seeded) and can swing summary speeds by ~20%
  run-to-run — the golden test forces `use_stabilization=False` (matching stream mode's own
  production default for a fixed-mount camera) and seeds both `cv2.setRNGSeed(0)` and
  `np.random.seed(0)` belt-and-braces.
- `generate_expected.py` must only ever be run "on code you know produces correct numbers (e.g.
  right after a manually-validated release)" — it overwrites the frozen snapshot other tests
  compare against.
