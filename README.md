# Pravah — LSPIV Velocity Analyzer

Box-side large-scale particle image velocimetry (LSPIV) application for Pravah's river and canal
discharge stations. A Flask app (`rtsp/app_stream.py`, port 5002) records or accepts video of a
river, calibrates the view against ground control points, and measures surface velocity with a
single built-in algorithm: **quasi-v2**, the quasi-automated LSPIV workflow of Bodart et al. (2024).
Everything runs locally — no internet connection is needed after installation.

---

## What It Does

You point the app at a fixed-position camera (bridge, pole, tripod) viewing a river or stream, or
upload a pre-recorded video. The pipeline:

1. Uses ground control points (GCPs) and camera geometry to calibrate the view
2. Auto-selects the ortho resolution, restricts the grid to water, and auto-computes the framestep
3. Orthorectifies each batch to real-world coordinates and runs PIV cross-correlation
4. Applies spatial-coherence filtering and a time-median aggregate, and estimates flow direction
   automatically

Results — mean, max, and median surface velocity (m/s), a velocity heatmap, and a camera overlay —
are shown in the browser and published to Modbus registers (print-only today; see
`docs/CONTEXT.md` under `rtsp/modbus_publisher.py`).

## Two Modes

- **Stream mode** (`/`) — connect to an RTSP/ONVIF camera, mark GCPs and the area of interest (AOI)
  in a wizard, then run continuously: an always-on recorder segments the camera feed, clips are cut,
  checked, and queued, and a processor thread runs the pipeline on each accepted clip.
- **Static mode** (`/static-mode`) — upload a recorded video, same wizard, one pipeline run.

There is exactly one measurement algorithm (quasi-v2); there is no pipeline upload or pipeline
choice.

The full architecture, recording design, and on-site notes live in
**[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)**.

---

## Requirements

| Requirement | Minimum Version | Notes |
|---|---|---|
| Python | 3.8+ | 3.10+ recommended |
| pip | 21+ | Comes with Python |
| ffmpeg | any recent build | Must be on `PATH` — the recorder shells out to it directly (not a pip package) |
| RAM | 4 GB | 8 GB recommended for longer videos |
| Storage | 2 GB free | For pyorc, OpenCV, and result images |
| OS | Windows 10 / macOS 12 / Ubuntu 20.04 | 64-bit only |

---

## Installation

```bash
# Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

> **Offline installation:** run the install on a connected machine first, then bundle the packages
> onto a USB:
> ```bash
> pip download -r requirements.txt -d ./offline_packages
> # On the field laptop:
> pip install --no-index --find-links=./offline_packages -r requirements.txt
> ```

---

## Running the App

```bash
python rtsp/app_stream.py
```

Then open **http://localhost:5002** in your browser.

On Windows/macOS/Linux you can instead use the launcher scripts, which install dependencies and
start the app from the repo root: `Application/run_app.bat` (Windows) or `Application/run_app.sh`
(macOS/Linux).

To stop the app, press `Ctrl + C` in the terminal.

---

## Documentation

- **[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)** — architecture and the why behind non-obvious
  decisions (recording design, thread safety, PIV pipeline).
- **[docs/CONTEXT.md](docs/CONTEXT.md)** — per-file rationale (the no-comments-in-code rule means
  this is where "why" lives).
- **[docs/CHANGES_FROM_SOURCE.md](docs/CHANGES_FROM_SOURCE.md)** — what changed from claude-test, bugs fixed, open TODOs.
- **[docs/FOLLOWUPS.md](docs/FOLLOWUPS.md)** — known bugs, deliberately unfixed and pinned by tests.
- **[docs/INCONSISTENCY_FINDINGS.md](docs/INCONSISTENCY_FINDINGS.md)** — the run-to-run
  inconsistency investigation and the fixes ported from it.
- **[docs/FRONTEND_MAP.md](docs/FRONTEND_MAP.md)**, **[docs/TODO.md](docs/TODO.md)**.

---

## Running Tests

```bash
python -m pytest              # fast suite (unit + component + API) — must be green before any commit
python -m pytest -m golden    # numeric-stability gate: runs the real pipeline on a field video
```

The golden test needs a fixture video not committed to the repo (`~/Desktop/Kunah_1.mp4`, or set
`PRAVAH_GOLDEN_VIDEO`) and skips gracefully without it. See
**[rtsp/tests/README.md](rtsp/tests/README.md)** for the test layout and the golden-regeneration
protocol.

---

## Troubleshooting

### Port 5002 already in use
```bash
# macOS / Linux:
lsof -ti:5002 | xargs kill
# Windows (PowerShell):
netstat -ano | findstr :5002
# then: taskkill /PID <pid_number> /F
```
Or edit `rtsp/app_stream.py` and change `port=5002` to any free port.

### Processing fails with "ERROR building CameraConfig"
- Check that GCPs are spread across the frame (not all in a line or cluster).
- Verify Z coordinates are positive (distance *down* from the lens).
- Try adding 1–2 more GCP points.

### Processing fails with "ERROR in frames.project()"
- The AOI corners may be outside the calibrated area. Draw the AOI slightly inward from the frame
  edges.
- Check that the water height is entered correctly.

### Results show near-zero velocity everywhere
Usually the AOI is not covering actual flowing water, or GCP coordinates are wrong. Check that:
- The AOI polygon covers moving water (not a static bank region)
- GCP X/Y/Z values match your field measurements
- Camera height was entered as a positive value
