# RTSP Video Capture — Architecture Walkthrough

> **Audience:** Any developer or AI agent modifying files in the `rtsp/` folder.
> Read this *before* changing any recording, timing, or PIV logic.

---

## What this system does

Captures RTSP video from a Matrix SATATYA camera and feeds it into a
**pyorc LSPIV** (Large Scale Particle Image Velocimetry) pipeline that
computes water-surface velocity frame-by-frame.

**LSPIV requires temporally continuous video.** If frame N is at time
t = 10.000 s and frame N+1 is at t = 10.033 s, velocity is correct.
If frame N+1 is actually from t = 40.033 s (because the camera stalled
for 30 s), PIV thinks the water moved 33 ms worth when it really moved
30 s worth — velocity is wildly wrong and the entire batch is garbage.

Every design decision below exists to guarantee that continuity.

---

## Camera behaviour (Matrix SATATYA MIBR50FL40CWP)

| Profile | URL suffix       | Codec | Resolution | FPS |
|---------|------------------|-------|------------|-----|
| 1       | unicaststream/1  | H.264 | 2592×1944  | 20  |
| 4       | unicaststream/4  | MJPEG | 1920×1080  | 30  |

**We use Profile 4 (MJPEG).** H.264 GOP boundaries cause frame
corruption on reconnect; MJPEG frames are self-contained.

### Known first-connection stall

On the first RTSP connection after idle, the camera delivers ~28 frames
(~0.9 s) then goes silent for ~30 s. Subsequent connections are stable.
This is a firmware behaviour, not a network issue. The recorder's
watchdog restarts ffmpeg after 15 s without new video, and a clip is
never cut across the resulting gap (see "Cutting clips").

---

## `OPENCV_FFMPEG_CAPTURE_OPTIONS` (legacy)

`streaming/config.py` still sets RTSP options (TCP, timeouts) in this env
var before `import cv2`, and `streaming.config` must stay the first
project import. Nothing opens the camera through OpenCV any more —
OpenCV only reads finished files, where these options have no effect —
so they are harmless leftovers.

---

## Recording design: one always-on recorder

### Why it was rebuilt (on-site failure, 24 Sep 2026)

Until September 2026 every recording opened its own camera connection
through OpenCV, decoded every frame in Python, re-encoded it to XVID AVI
and remuxed that to MP4. A "budget countdown" deducted `1/fps` per written
frame to decide when a clip was long enough, and a separate
`_FrameGrabber` thread kept a second connection open for the live
preview, paused around each recording.

On site with the 5 MP (2592×1944) H.264 profile this failed in two ways:

1. **CPU-bound capture.** Decoding and re-encoding 5 MP frames could not
   keep up with the camera. Frames were dropped inside the capture loop,
   so the clip's frame spacing no longer matched `1/fps` — the exact
   assumption PIV depends on — while the budget countdown still reported
   a full-length clip.
2. **A second camera connection.** The preview grabber reconnected while
   a recording was running. The camera cannot serve two connections
   well; the recording connection lost packets and stalled.

The fix is structural, not a tuning change: the camera is recorded
without decoding, by exactly one process, all the time, and every
feature reads from that recording.

### The recorder (`streaming/recorder.py`)

`get_camera_recorder()` returns the single `CameraRecorder`. It is the
**only** code that opens the RTSP URL. `start_recording(url)` is
idempotent (a different URL restarts it); nothing ever stops it except
a URL change or process exit.

It runs one ffmpeg process that:

- **copies** the video stream (`-c:v copy` — no decode, no re-encode, so
  CPU load cannot drop frames) into 10-second MKV **pieces** in
  `recordings/buffer/`, named by wall-clock start time and ffmpeg run id;
- decodes **keyframes only** (~1 per second) into `buffer/preview.jpg`,
  a full-resolution frame used for the live view, the probe and GCP
  marking.

Pieces are MKV because an MP4 cut off mid-write is unreadable; each
piece's timestamps restart at 0 so the concat join does not stretch
clips. A piece counts as finished only once ffmpeg lists it in the run's
CSV segment list, which also gives its exact start/end in stream time.
The first piece of every run is skipped (it starts mid-GOP).

**Retention:** pieces older than 10 min are deleted, or older than two
clips' worth when a longer clip length is reserved
(`reserve_clip_length`). A file-count cap is a safety net against clock
jumps. `hold_pieces_since(t)` keeps everything since `t` (manual
recording) until released with `None`.

**Watchdog:** ffmpeg's own `-timeout` did not reliably fire on site (a
recording froze for 4+ minutes). If neither the newest piece nor the
preview changes for `STALL_TIMEOUT_S` (15 s), ffmpeg is killed and
restarted; `restarts` and `last_error` are visible at
`GET /api/stream/recorder_status`.

### Cutting clips (`streaming/clip_cutter.py`)

A clip is a stream-copy concat of consecutive pieces, so it is
bit-identical to what the camera sent. Only pieces of the same run whose
stream times follow each other without a gap are joined; a restart or a
missing piece splits the buffer into separate chains, and a clip is
never cut across a split. `wait_for_latest_clip(duration, dest, timeout,
not_before_wall=...)` waits until the newest gap-free run covers the
requested duration, using only pieces that started after
`not_before_wall` (the button press, or the last rejected attempt).

Clip length therefore comes from the camera's own timestamps. There is
no timing model to get wrong — the old budget countdown, stall threshold
and 80 % early/late-disruption rule are gone with the engine they
protected.

### Checks after recording, never during

- **Integrity** (`streaming/clip_integrity.py`) — is the file intact:
  duration, missing frames (< 0.5 %), longest gap (< 0.5 s), the fps
  OpenCV will report (that value *is* PIV's dt) and, in the full check,
  a decode pass for corrupted pictures. The LSPIV recorder runs the quick
  check (no decode) before queueing; the Record button and the processor
  run the full check.
- **Fitness** (`streaming/clip_fitness.py`) — is the clip fit for LSPIV:
  score 0–10, status `ok` / `low_confidence` / `invalid`, compared
  against `recordings/gcp_reference.jpg` (the frame the GCPs were marked
  on, saved by `GET /api/stream/snapshot`). `invalid` (e.g. the camera
  moved) skips PIV for that batch. If the check is unavailable or throws,
  PIV runs without it and the fitness fields are `None`.

Queued clips left over from an earlier session are discarded when a new
session starts (`discard_queued_clips`) — they belong to a different
configuration and their batch numbers would collide.

Every kept clip gets a manifest `<clip>.json`
(`streaming/clip_manifest.py`): source, masked RTSP URL, ffprobe stream
info, camera settings over ONVIF (or `null`), integrity and fitness
verdicts, water level and the git revision.

---

## Recording flows

All flows read from the recorder; none opens the camera.

### Record button (`_run_snapshot_recording`)

- **State:** `_snapshot_rec` dict, protected by `_snapshot_rec_lock`
- Cuts `SNAPSHOT_CLIP_COUNT` (1) clip of the selected duration, recorded
  after the press
- Full integrity check; pass → `Desktop/<YYYY-MM-DD>/<HH-MM>/vid_1.mp4`
  + `vid_1.json`
- Fail → `not_considered/vid_1_try{n}.mp4` + manifest, `error` holds the
  reason (e.g. "3.1 % frames missing"), and a newer clip is cut; after 5
  failed attempts the status is `failed`
- No PIV processing — for operator review only

### LSPIV batches (`_recorder_thread` → queue → `_processor_thread`)

- **State:** `session` dict, protected by `session_lock`
- Each cycle cuts a `batch_duration_s` clip recorded after the cycle
  started and runs the quick integrity check. Rejects go to
  `<audit>/not_considered/`; 3 consecutive rejects set the session to
  `error`.
- Clean batches are copied to the Desktop audit folder (`vid_{n}.mp4`)
  and queued in `recordings/queue/` (`streaming/clip_queue.py`,
  `batch_00000.mp4`, … — name order is recording order). Then the fixed
  `BATCH_COOLDOWN_S` pause.
- The processor takes the oldest queued clip, runs the full integrity
  check, then fitness, then PIV, and writes the manifest next to the
  audit copy. **Batches are never dropped** — the old single hand-off
  slot deleted a batch whenever the processor was busy; the queue waits.

### Manual recording (`/api/stream/record/start`, `/record/stop`)

- Start holds the buffer from that moment; Stop waits for the piece
  containing the stop time to finish, then saves the buffer between the
  two times to `recordings/recording_<start>.mp4` (+ manifest). A gap in
  the buffer yields `_part1`, `_part2`, …
- The clip starts and ends on piece boundaries, so it can include up to
  one piece (10 s) before Start and after Stop.
- No integrity check — **never feed these to LSPIV** without checking.

---

## `_processor_thread` and pipeline timeouts

The processor runs the PIV pipeline with a timeout of `5 × batch_duration_s`.
If the pipeline hangs, `job_state["cancel"] = True` is set, but **the
worker thread keeps running** — Python cannot kill threads. The cancel
flag is only checked between pipeline steps. If a single step (e.g.,
`get_piv()`) hangs internally, the cancel is never seen.

---

## `pyorc.CameraConfig` — ortho params vs the PIV window

```python
cam_kwargs = dict(
    resolution=resolution,   # P0 auto-computes this from GCP density in
                              # assisted/quasi_automated mode; only a manual
                              # workflow falls back to the fixed default (0.05)
    window_size=_prelim_window,  # ortho grid param — NOT the PIV window_size
)
```

`resolution` and `window_size` here are **ortho-grid metadata**, not fixed site
constants — quasi-v2's P₀ tool (`piv/auto_params.py`) auto-derives `resolution`
from GCP convex-hull density for `assisted`/`quasi_automated` workflows (the
production default), and `window_size` is derived from it too. Only the
`"manual"` workflow uses the literal fallback constants in `piv/defaults.py`
(`RESOLUTION = 0.05`, `PIV_WINDOW_SIZE = 10`). Either way, the user-facing PIV
sliders (`piv_window_size`, `piv_overlap`) are a **different** parameter passed
to `get_piv()` later. Do not conflate `CameraConfig(window_size=...)` with the
PIV window — that will break orthorectification.

---

## `pymodbus` must be pinned at 3.6.9

`sensor_reader.py` uses `device_id=` kwarg in `read_holding_registers()`.
Newer pymodbus versions renamed this to `slave=` or `unit=`. Upgrading
pymodbus will break sensor reads silently (wrong default device ID, no
error thrown).

---

## No re-encoding anywhere on the recording path

Recorder pieces, joined clips, audit copies and extra saves are all
stream copies of what the camera sent. **Do not "optimize" by adding
`-c:v libx264`** or decoding frames in Python: re-encoding costs CPU per
frame (the 24 Sep 2026 failure) and may alter frame timing, breaking
LSPIV continuity.

---

## Session state — consume-once warning flags

`warn_batch_dropped` and `warn_duration_changed` are reset to `False`
inside `_session_snapshot()` on the first poll that reads them. If the
frontend polls twice before displaying the warning, the second poll
misses it. Don't add more consume-once flags without understanding
this pattern.

---

## Logging — `_slog` vs `_log.info`

- `_slog(msg)` — writes to both Python logger AND `session["log"]`
  (visible in UI). Capped at 200 entries to prevent memory bloat.
- `_log.info(msg)` — Python logger only, not visible in UI, survives
  session reset.

If you need logs that survive session reset, use `_log.info()`.
If you need logs visible in the UI, use `_slog()`.

---

## Thread safety — two locks, never nest them

| Lock | Protects |
|------|----------|
| `session_lock` | All pipeline state (`session` dict) |
| `_snapshot_rec_lock` | Snapshot recording state (`_snapshot_rec` dict) |

Code never acquires both simultaneously. If you add code that needs
both, you risk deadlock. Always acquire one, release it, then acquire
the other.

---

## CORS — localhost only

CORS headers are restricted to `localhost:5001` and `localhost:5002`.
If you deploy on a different port or host, API calls from the frontend
will be silently blocked. The error appears as a network failure in the
browser, not a clear CORS message.

---

## Temporary files

Clips are cut into `STREAM_TMP` and moved out (Desktop, audit folder or
queue) as soon as they are checked. A crash mid-check can leave a clip
there; nothing cleans `STREAM_TMP` automatically.

---

## Probe, live view and snapshot read the recorder

`/api/stream/probe`, `/api/stream/live` and `/api/stream/snapshot` start
the recorder (idempotent) and read `buffer/preview.jpg` and the newest
piece — they never open the camera. Probe waits up to 20 s for a fresh
preview; the stream parameters come from ffprobe on the newest piece.

---

## PIV pipeline — the `piv/` package (quasi-v2, Bodart 2024)

The pipeline is now **quasi-v2**, the Bodart 2024 quasi-automated/assisted LSPIV
implementation, living in `rtsp/piv/`. Framestep is no longer a hardcoded constant: the
`assisted`/`quasi_automated` workflows auto-compute it per run (tool P₃), and the velocity-field
noise/spike thresholds are the quasi-v2 values, not the old fixed 0.005/3×-median pair. See
`docs/CONTEXT.md` (`rtsp/piv/auto_params.py`, `rtsp/piv/filters.py`, `rtsp/piv/pipeline.py`) for
the current thresholds, formulas and rationale.

---

## Key constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `duration_s` (param) | user-selected | Clip length for snapshot & pipeline recording |
| `SNAPSHOT_CLIP_COUNT` | 1 | Clips per snapshot run |
| `MAX_SNAPSHOT_ATTEMPTS` | 5 | Record-button clips tried before `failed` |
| `PIECE_SECONDS` | 10 | Length of one buffer piece |
| `MIN_RETENTION_S` | 600 | Buffer kept (or two clips' worth, if longer) |
| `STALL_TIMEOUT_S` | 15 | No new video for this long → restart ffmpeg |
| `MAX_MISSING_FRACTION` / `MAX_GAP_S` | 0.5 % / 0.5 s | Integrity limits |
| `BATCH_COOLDOWN_S` | 300 | 5-min gap between pipeline batches |
| `_MAX_LOG_ENTRIES` | 200 | Session log cap to prevent memory bloat |
| `_MAX_RESULTS_IN_POLL` | 50 | Results cap in poll response |
| `MAX_FAILURES` | 3 | Consecutive failures before recorder aborts |

---

## File layout

```
rtsp/
├── app_stream.py             ← Flask app + HTTP routes + thread wiring (thin)
├── static_mode.py            ← Static-mode blueprint (upload video → run once)
├── camera_routes.py          ← /api/camera/* blueprint: read / apply settings, sync clock
├── camera_request_validation.py ← input checks for those routes
├── streaming/                ← capture/recording engine (split from app_stream.py)
│   ├── config.py             ← FFmpeg env var + cv2 re-export (import FIRST), paths, logging
│   ├── recorder.py           ← the always-on recorder (ONLY camera connection)
│   ├── clip_cutter.py        ← cut clips from the buffer
│   ├── clip_integrity.py     ← "is the file intact" checks
│   ├── clip_fitness.py       ← "fit for LSPIV" score, camera-moved check
│   ├── clip_manifest.py      ← <clip>.json next to every kept clip
│   ├── clip_queue.py         ← clips waiting for the processor
│   ├── camera_onvif.py       ← camera stream settings over ONVIF
│   ├── models/               ← Piece, RecorderStatus, verdict dataclasses
│   ├── session.py            ← shared session/_snapshot_rec state, locks, _slog
│   ├── snapshot_recorder.py  ← Record-button thread
│   ├── batch_recorder.py     ← LSPIV batch thread (cut → check → queue)
│   ├── processor.py          ← pipeline processor thread (queue → checks → PIV)
│   ├── manual_recorder.py    ← manual recording (hold + cut window)
│   └── video_files.py        ← batch save / cleanup helpers
├── piv/                      ← LSPIV pipeline — quasi-v2 (Bodart 2024 quasi-automated/assisted)
│   ├── pipeline.py           ← run_pipeline (the workflow orchestrator)
│   ├── auto_params.py        ← P₀ auto resolution, P₃ auto framestep, auto PIV window/overlap
│   ├── water_mask.py         ← P₁ water-only grid, P₂ searching-area from spotted displacements
│   ├── flow_direction.py     ← automatic flow-direction estimate (magnitude-weighted PCA)
│   ├── discharge.py          ← ISO 748:2021 velocity-area discharge computation
│   ├── geometry.py           ← AOI corners, distortion coefficient sanitizing
│   ├── filters.py            ← quality + velocity-field filters, F₀ spatial coherence
│   ├── visualize.py          ← result renderers (matplotlib Agg)
│   ├── defaults.py           ← RESOLUTION, PIV_*, REQUIRED_KEYS
│   └── job_log.py            ← _log(job_state, msg)
├── modbus_publisher.py       ← Modbus register formatter (print-only mode)
├── sensor_reader.py          ← Modbus sensor reader (water level)
├── templates/
│   ├── index_stream.html     ← Stream UI (markup; assets under static/)
│   └── index_static.html     ← Static-mode UI (markup)
├── static/
│   ├── css/app.css           ← shared stylesheet (both pages)
│   ├── js/shared/            ← ES modules shared by both pages
│   ├── js/stream/            ← stream-page modules (entry: main.js)
│   ├── js/static_mode/       ← static-page modules (entry: main.js)
│   └── results/
│       └── stream_tmp/       ← clips being checked before they are moved
├── recordings/               ← buffer/ (pieces + preview.jpg), queue/,
│                               gcp_reference.jpg, manual recordings
```

Docs (repo root `docs/`, not inside `rtsp/`): `WALKTHROUGH.md` (this file), `FOLLOWUPS.md`,
`FRONTEND_MAP.md`, `TODO.md`, `CONTEXT.md`, `INCONSISTENCY_FINDINGS.md`.

Desktop output:
```
Desktop/
├── <YYYY-MM-DD>/
│   └── <HH-MM>/
│       ├── vid_1.mp4
│       ├── vid_1.json            ← manifest
│       └── not_considered/
│           ├── vid_1_try1.mp4
│           └── vid_1_try1.json
└── <date_time>_processed_video/   ← Pipeline audit copies
    ├── vid_1.mp4
    ├── vid_1.json                ← manifest (after processing)
    └── not_considered/
        ├── batch_1_try1.mp4      ← rejected by the quick check
        └── batch_00001.mp4       ← rejected by the processor's full check
```
