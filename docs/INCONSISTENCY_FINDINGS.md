# Inconsistent PIV results — investigation findings

**Status:** investigation complete, **nothing fixed**. No source file was modified.
**Date:** 2026-09-16
**Scope:** why `rtsp/` reports a different surface velocity for the same river / same video.
**Method:** static read of the codebase + ~25 real runs of `piv.run_pipeline` on the
Kunah fixture video (`~/Desktop/Kunah_1.mp4`, 3739 frames, 59.7 fps) under controlled
variations. Every number below was measured, not inferred.

> Read alongside `rtsp/FOLLOWUPS.md` (known-and-pinned bugs) and `rtsp/TODO.md`
> (the unported Bodart P0–P3 work). Items already logged there are cross-referenced
> rather than re-litigated.

---

## TL;DR

The reported velocity is not reproducible, and the dominant cause is **not** in this
repo's own arithmetic:

1. **`pyorc.CameraConfig` estimates the focal length from the GCPs using a randomized
   solver that draws from numpy's global RNG.** Unseeded (i.e. production), fx wobbles
   ~0.8 % between runs, which propagates into up to a **21 % swing in `mean_speed`**.
   The escape hatch (`use_fixed_intrinsics` + `camera_matrix`) exists in
   `rtsp/piv/pipeline.py` and **no code path in the app can set it**.
2. **The measurement is sub-pixel**, so what survives is largely correlation noise.
   The app's own advisor says so in every run log (`p25 = 0.57 px`, `only 8.3% of
   points meet threshold`) and is then ignored.
3. **The post-filter distorts the mean and destroys the max**, with a data-dependent
   threshold that amplifies small differences into large ones.
4. **Stream mode and static mode run different physics** on the same video.
5. **The test suite cannot catch any of this** — the only numeric test seeds the RNGs
   and pins a config production never runs, and CI never executes it.

---

## Finding 1 — CameraConfig focal-length estimation is RNG-dependent (ROOT CAUSE)

### Evidence

Same video, same config, repeated runs:

| Condition | `mean_speed` across runs | spread |
|---|---|---|
| `use_stabilization: true` (**static mode's effective default**) | 0.1572, 0.1602, 0.1423, 0.1580 | **11.6 %** |
| `use_stabilization: false` (stream mode's default), unseeded | 0.10844, 0.10852 | 0.07 % |
| `use_stabilization: false`, `np.random.seed(0/1/2)` | 0.10573 / 0.10975 / 0.09069 | **21 %** |

With stabilization off the output is a **deterministic function of numpy's global RNG
state**:

* `seed(0)` reproduced `mean=0.10572936` bit-for-bit in five separate processes.
* `seed(0)` then `np.random.rand(1)` → `0.10470626` (1.0 % shift from one drawn value).
* `seed(0)` then `np.random.rand(7)` → `0.10073049` (4.7 % shift).
* Seeding `cv2` alone does **not** stabilize it; seeding numpy alone does.

The consumer is the CameraConfig construction, not the video pipeline. Watching
`np.random.get_state()` around each pyorc call shows the state is already changed
before `Video.__init__` and never advances again during steps 1–6.

Direct measurement of the estimated focal length from the same 4 GCPs:

```
seed=0: fx = 1281.726     seed=2: fx = 1290.316
seed=1: fx = 1280.388     seed=3: fx = 1284.869
unseeded, two constructions in ONE process: fx = 1284.028, then 1282.571
```

A ~0.8 % fx wobble → up to 21 % velocity swing, because fx sets the whole
orthorectification geometry and therefore the PIV grid and the px→m scale.

### Proof this is the whole story

Pinning the intrinsics and then running **with deliberately different RNG states**
(`np.random.seed(11)`, `seed(148)`, `seed(285)`):

```
FIXED run 0 (rng varied): mean=0.10572936 median=0.09559255 max=0.26447877
FIXED run 1 (rng varied): mean=0.10572936 median=0.09559255 max=0.26447877
FIXED run 2 (rng varied): mean=0.10572936 median=0.09559255 max=0.26447877
```

Bit-for-bit identical. The entire run-to-run variability on the stabilization-off path
is the focal-length estimate.

### Why the existing escape hatch is unreachable

`rtsp/piv/pipeline.py:119-136` already supports pinned intrinsics:

```python
matrix_in_json = "camera_matrix" in config and config["camera_matrix"] is not None
use_fixed_intrinsics = bool(config.get("use_fixed_intrinsics", False))
...
else:
    _log(job_state, "  Camera intrinsics: not fixed — pyorc will estimate from GCPs (may vary between runs)")
```

The code literally logs *"may vary between runs"* — and then ships that path as the only
one. Verified by grep: `camera_matrix`, `dist_coeffs`, `use_fixed_intrinsics`,
`camera_model`, `zoom_level` are **never written** by `rtsp/static/js/shared/config.js`,
`rtsp/app_stream.py`, or `rtsp/static_mode.py`. They can only arrive via a hand-edited
JSON outside the app's own UI flow.

### What I could NOT verify

The exact library call that consumes the RNG. It does **not** go through module-level
`np.random.*` (I wrapped `rand/random/randint/uniform/randn/normal/choice/permutation/
shuffle/seed` and got zero hits), so it reads the global `RandomState` via the C-API
inside `pyorc.CameraConfig` or one of its dependencies. Pinning the intrinsics sidesteps
it entirely, so pinpointing the library internals is not on the critical path.

---

## Finding 2 — the measurement is sub-pixel, i.e. noise-dominated

### The app already knows and says so

From the log of a default run (`framestep=25`, `frames=150`):

```
  --- FRAMESTEP ADVISOR (Bodart 2024 P3 rule) ---
  Currently applied framestep: 25
  Video fps                  : 59.7
  p25 / median / p75 / p90 : 0.57 / 1.40 / 2.31 / 2.87 px
  Target (P3 rule)          : 75% of points >= 3 px  (i.e. p25 >= 3 px)
  Currently met?            : NO — only 8.3% of points meet threshold
```

A displacement of ~1 px median is below the cross-correlation reliability floor the
repo's own `rtsp/TODO.md` cites (Bodart 2024, >=3 px).

### Framestep sweep (intrinsics pinned, so each row is deterministic)

Velocity in m/s is by construction **independent of framestep** — `rtsp/TODO.md` states
this as the premise of the P3 rule. Measured:

| framestep | frames used | `mean_speed` |
|---|---|---|
| 25 | 151 → 7 | 0.10573 |
| 10 | 151 → 16 | 0.12449 |
| 5 | 151 → 31 | 0.13068 |
| 3 | 151 → 51 | 0.23805 |
| 1 | 151 | 0.40736 |

**3.9× spread** on a quantity that should not move at all.

**Important correction to the obvious hypothesis:** the m/s conversion is *not* broken.
I instrumented `Frames.get_piv` and confirmed pyorc derives `dt` from the time
coordinate (`dt = self._obj["time"].diff(dim="time")`, `pyorc/api/frames.py:157`), and
that `isel(time=slice(None,None,framestep))` correctly scales it:

```
framestep=1 : dt_unique = [0.016667, 0.016678, 0.033344, 0.033356, 0.050022]
framestep=25: dt_unique = [0.416833, 0.533544, 0.535378]
```

So the spread is the PIV measuring noise at low framestep, not a scaling bug. At
0.05 m/px ortho resolution and ~0.1 m/s, true displacement is ~1 px at fs=25 and
~0.03 px at fs=1; a spurious correlation peak anywhere in a 10 px window maps to
several m/s.

Side observation from the same instrumentation: **the fixture video's frame timing is
irregular** — dt takes 1x, 2x and 3x the nominal interval, and the first gap is
0.1185 s (~7 frames). pyorc handles this correctly per frame-pair, but it confirms the
recorded files have dropped frames (see Finding 6).

### Sample size

Same framestep, longer read window:

```
frames=150, framestep=25 -> mean=0.10573   (151 -> 7 frames = 6 pairs)
frames=300, framestep=25 -> mean=0.04730   (301 -> 13 frames = 12 pairs)
```

**2.2× from the number of frames alone.** The default reads 150 of the video's 3739
frames — 2.5 s of a 62 s clip — onto a 6x8 = **48-cell grid**, of which 46 survive
filtering. Six frame-pairs over 46 cells is not enough to average the noise out.

`frames`, `framestep`, `piv_window_size`, `piv_overlap`, `piv_corr_min`, `piv_s2n_min`
and `resolution` are **never set by the UI or server** — every run uses the hardcoded
defaults in `rtsp/piv/defaults.py`.

### The quality gate is inert

```
PIV quality mask kept 288/288 cells (100.0%) with corr>=0.15 and s2n>=1.15
```

corr≥0.15 / s2n≥1.15 rejected nothing, on a field whose displacements are sub-pixel.
The one line of defence against noise vectors passes everything.

### The advisor contradicts itself

`rtsp/piv/diagnostics.py:130`:

```python
new_fs = min(30, math.ceil(3.0 / p25 * framestep_current))
```

At p25=0.57 the required framestep is `ceil(3/0.57*25)` = **132**; `min(30, ...)` clamps
it to 30. The log then prints

```
  Increase framestep to 30      (scaling from current p25=0.57 px -> expected p25=3.0 px)
  At recommended framestep, expected pixel displacements:
    p25 / median / p75 / p90 : 0.68 / 1.68 / 2.77 / 3.45 px
```

The claim "expected p25 = 3.0 px" is falsified by the table immediately below it
(0.68 px). The cap of 30 makes the P3 rule unreachable at this site, silently.

---

## Finding 3 — `filter_velocity_field` distorts the mean and destroys the max

`rtsp/piv/filters.py:29-70`. It deletes (a) exact zeros, (b) anything < 0.005 m/s, and
(c) anything > 3x the median of the survivors.

```
input   : [0.0, 0.004, 0.10, 0.12, 0.11, 0.40]   true mean = 0.1223
output  : [nan, nan,   0.10, 0.12, 0.11, nan ]
reported: mean = 0.1100   max = 0.1200
```

Two consequences:

* **Slow or stagnant water is erased, not measured.** A cell reading 0 m/s is a
  measurement, and dropping it biases `mean_speed` upward.
* **`max_speed` is not the maximum.** It is the largest survivor, so it is effectively
  capped at ~3x median. The value published to Modbus is an artefact of the filter.

The threshold is data-dependent, which is the amplifier that turns Finding 1's small
perturbations into large reported differences:

```
[0.10, 0.12, 0.11, 0.40]              -> mean=0.1100  max=0.1200
[0.10, 0.12, 0.11, 0.40, 0.34]        -> mean=0.1675  max=0.3400   (+52% / +183%)
[0.10, 0.12, 0.11, 0.40, 0.34, 0.35]  -> mean=0.2367  max=0.4000   (+115% / +233%)
```

One extra surviving cell moves the reported mean by half. With only 46 valid cells this
is not a corner case, it is the operating regime.

Related, already logged: `rtsp/FOLLOWUPS.md` #10 covers the all-zero / all-NaN early
return and the noise-floor case, but not the mean/max distortion above.

Also note `rtsp/piv/pipeline.py:365` computes
`speed = sqrt(mean_t(v_x)^2 + mean_t(v_y)^2)` — the magnitude of the time-averaged
vector, not the average speed. Defensible, but it means direction reversals cancel, and
it interacts badly with per-timestep quality masking (different cells contribute to
`v_x` and `v_y` at different times).

---

## Finding 4 — stream mode and static mode run different physics

| Parameter | Stream mode | Static mode | Consequence |
|---|---|---|---|
| `use_stabilization` | forced `False` (`rtsp/app_stream.py:179`) | **never set** → `True` via `rtsp/piv/pipeline.py:225` | This is the 0.106 vs 0.157 difference in Finding 1's table — **~48 % apart, decided by which page the operator clicked.** Static mode also inherits the 11.6 % nondeterminism. |
| `h_ref` | UI writes it nested at `gcps.h_ref` (`rtsp/static/js/shared/config.js:36`); pipeline reads it top-level (`rtsp/piv/pipeline.py:70`) | same | The key never matches, so `h_ref` always silently falls back to `h_a`. **The UI field does nothing.** |
| sensor → `h_a` | `cam_z - distance_m` (`rtsp/app_stream.py:169`) | `-distance_m` (`rtsp/static_mode.py:168`) | Different formulas for the same sensor reading; they agree only if the camera sits at Z=0. |

Config persistence is otherwise sound: one `_pipeline_config` is deep-copied per batch
(`rtsp/streaming/processor.py:21`), so batches within a session do share a config.

---

## Finding 5 — two crashes that destroy a batch after the numbers exist

1. **`UnicodeEncodeError` (already `rtsp/FOLLOWUPS.md` #7) — hit live, unprompted, on
   the first run of this investigation.** `print_modbus_registers` prints box-drawing
   characters; with stdout redirected on Windows (cp1252) it raises, and the exception
   propagates out of `run_pipeline` at `rtsp/piv/pipeline.py:393` — *after* the speeds
   are computed but *before* the camera overlay and the `return`. Under a service log,
   every batch dies and no result is ever produced. This is a plausible part of the
   "sometimes we get results, sometimes we don't" symptom.

2. **`fps == 0` → `ZeroDivisionError`.** `rtsp/piv/diagnostics.py:118`:
   `disp_px = mag * (framestep_current / fps) / resolution`. `cv2.CAP_PROP_FPS` returns
   0.0 for some remuxed containers. Confirmed by direct call:
   `RAISED ZeroDivisionError: float division by zero`. The call at
   `rtsp/piv/pipeline.py:329` is **not** wrapped in try/except, so it takes the batch
   with it. `rtsp/FOLLOWUPS.md` #6 notes the unported CAP_PROP_FPS sanity fallback from
   `b98ec53`; this is the concrete consequence.

---

## Finding 6 — the recording path adds its own, varying, error

Verified in `rtsp/streaming/capture.py`:

```python
fps = cap.get(cv2.CAP_PROP_FPS) or 25.0                        # line 34
writer = cv2.VideoWriter(str(avi_path), fourcc, fps, (w, h))   # line 41
```

The nominal (possibly hardcoded 25.0) FPS becomes the file's FPS header. But frames lost
during stalls/reconnects are written **back-to-back** with no gap (`remaining_s -= 1.0/fps`,
line 127, after a `continue` that cost real seconds), so the encoded timing diverges from
the real capture timing. Since pyorc derives velocity from the container's time
coordinate, the velocity is overestimated by exactly that ratio.

The acceptance gate (lines 159-168) allows it:

```python
fps_ratio = eff_fps / fps if fps > 0 else 1.0
if fps_ratio < 0.80:
    had_early_disruption = True   # reject
```

**Anything down to 80 % of nominal is accepted → up to +25 % velocity overestimate,
varying batch to batch with network conditions.** The FPS header written to the file is
always the nominal value and never reflects the per-batch effective rate.

`_open_rtsp` is called fresh per batch and per retry, so `cap.get(CAP_PROP_FPS)` is
re-queried each time and can differ (or fall back to 25.0) between batches of the same
session.

---

## Finding 7 — the test suite cannot catch any of this

`python -m pytest` is green (161 passed), and that green means very little for the numbers:

* `rtsp/tests/golden/test_pipeline_golden.py:36-42` calls `cv2.setRNGSeed(0)` and
  `np.random.seed(0)` **and** forces `use_stabilization=False`. That is the only reason
  `expected.json` reproduces. Without the seeds, the same config returns 0.10844 /
  0.10852 — the golden's `rel=1e-6` assertion would fail.
* Its comment claims `use_stabilization=False` is "Stream mode's production default"
  and calls it "the deterministic production path". Both halves are wrong: static mode
  defaults to `True`, and neither mode is deterministic because neither seeds the RNGs.
* The comment also says "see FOLLOWUPS.md" for the ~20 % stabilization swing;
  **FOLLOWUPS.md does not mention stabilization.**
* `.github/workflows/tests.yml` runs `python -m pytest -v`, and `pytest.ini` carries
  `addopts = -m "not golden"`, so **CI never runs the golden test**; the fixture video
  is not in git either, so it would self-skip regardless. There is zero automated
  protection on the measurement.
* Minor: `CLAUDE.md` advertises the fast suite at "~12 s"; it takes **102 s** here.

---

## Reproduction

All runs used the fixture at `~/Desktop/Kunah_1.mp4` and
`rtsp/tests/golden/kunah_config.json`. Set `PYTHONIOENCODING=utf-8` first, or Finding 5.1
will kill every run.

```bash
export PYTHONIOENCODING=utf-8
```

### A. RNG dependence (Finding 1)

```python
import json, pathlib, sys
ROOT = pathlib.Path(r"D:\pravah\claude-test"); sys.path.insert(0, str(ROOT/"rtsp"))
import numpy as np
from piv import run_pipeline
CFG = json.loads((ROOT/"rtsp/tests/golden/kunah_config.json").read_text())
CFG["use_stabilization"] = False
VIDEO = str(pathlib.Path.home()/"Desktop"/"Kunah_1.mp4")
for seed in (0, 1, 2):
    np.random.seed(seed)
    r = run_pipeline(dict(CFG), VIDEO, {}, f"s{seed}", "out")
    print(seed, r["mean_speed"])
# -> 0 0.10572936 | 1 0.10975178 | 2 0.09068727
```

### B. Focal length alone (fast, no video needed)

```python
import json, pathlib, numpy as np, pyorc
C = json.loads(pathlib.Path(r"D:\pravah\claude-test\rtsp\tests\golden\kunah_config.json").read_text())
g = C["gcps"]; dst = [[float(p[0]), float(p[1])] for p in g["dst"]]
for seed in (0, 1, 2, 3, None):
    if seed is not None: np.random.seed(seed)
    cc = pyorc.CameraConfig(height=C["frame_height"], width=C["frame_width"],
            gcps={"src": g["src"], "dst": dst, "z_0": float(g["z_0"]), "h_ref": float(C["h_a"])},
            resolution=0.05, window_size=10)
    cc.set_lens_position(*C["lens_position"])
    print(seed, float(cc.camera_matrix[0][0]))
```

### C. Determinism with pinned intrinsics

Add to the config and vary the seed between runs — output is identical:

```python
CFG.update({
    "use_fixed_intrinsics": True,
    "camera_matrix": [[1281.72607421875, 0.0, 960.0],
                      [0.0, 1281.72607421875, 540.0],
                      [0.0, 0.0, 1.0]],
})
```

### D. Filter behaviour (fast, no video)

```python
import sys; sys.path.insert(0, r"D:\pravah\claude-test\rtsp")
import numpy as np
from piv.filters import filter_velocity_field
for extra in ([], [0.34], [0.34, 0.35]):
    a = np.array([[0.10, 0.12, 0.11, 0.40] + extra])
    r, _, _ = filter_velocity_field({}, a.copy(), a.copy(), np.zeros_like(a))
    print(a.tolist()[0], "->", np.nanmean(r), np.nanmax(r))
```

### E. fps=0 crash (fast, no video)

```python
import sys; sys.path.insert(0, r"D:\pravah\claude-test\rtsp")
import numpy as np, xarray as xr
from piv.diagnostics import log_piv_diagnostics
v = np.full((5, 4, 4), 0.3)
ds = xr.Dataset({"v_x": (("time","y","x"), v), "v_y": (("time","y","x"), v*0)})
log_piv_diagnostics({}, ds, fps=0.0, resolution=0.05, framestep_current=25)
# -> ZeroDivisionError
```

---

## Suggested order of work (not started, needs owner sign-off)

Per `CLAUDE.md` §5 each of these needs a failing test first, and each is its own commit.

1. **Pin the intrinsics.** Plumb `camera_matrix` / `use_fixed_intrinsics` through
   `config.js` → both modes, calibrated once per site. This alone makes runs
   reproducible and is the highest-value single change. *Verify:* run 3x with different
   `np.random.seed` values, assert bit-identical summaries.
2. **Make static and stream agree.** Set `use_stabilization` explicitly in
   `static_mode.py` (same value as stream), fix the `h_ref` key mismatch, reconcile the
   two sensor→`h_a` formulas. *Verify:* same video through both modes → same numbers.
3. **Fix the sample size.** Raise `frames` well above 150 and choose `framestep` so
   p25 >= 3 px (this site needs ~132, not 25). Expose both in the UI, or finish the
   P3 port in `rtsp/TODO.md`. Lift the `min(30, ...)` cap and fix the self-contradicting
   recommendation text. *Verify:* the framestep sweep should become flat — that is the
   real acceptance criterion for "the measurement is no longer noise".
4. **Guard the two crashes** — FOLLOWUPS #7 (`errors="replace"` or an ASCII banner) and
   the `fps == 0` fallback from `b98ec53` (FOLLOWUPS #6).
5. **Revisit the filter.** Stop erasing slow water from the mean; report a true max or
   rename the field; replace the 3x-median spike rule with something that does not move
   with the data. Note this changes `expected.json` — that is a golden regeneration with
   a physical justification, per `rtsp/tests/README.md` rule 3.
6. **Measure the recorded FPS** instead of trusting `CAP_PROP_FPS`, or write real
   per-frame timestamps, and tighten the 0.80 gate.
7. **Make the golden test honest.** Drop the RNG seeding once item 1 lands (it is then
   unnecessary), stop forcing a config production does not run, and get the fixture into
   CI (LFS or a short clip) so the numeric gate actually executes.

---

## Explicitly NOT verified

* Which library call inside `pyorc.CameraConfig` consumes the numpy RNG (see Finding 1).
* Whether `cv2.CAP_PROP_FPS` actually returns 0 or a wrong value for the site's real
  camera — the `or 25.0` fallback path is reachable in code but I could not observe
  production hardware.
* Any claim about `runners/` (archived pipelines) — out of scope, not executed.
* The frontend was read for config plumbing only; no browser-level testing was done.
* `rtsp/automation/` (Playwright harness) was not run.

---

# Addendum — second review and prep branch (Fable 5.1, 2026-09-16)

Everything above was re-read against source and re-run; its measurements
reproduce bit-for-bit. This addendum records what it missed, what was changed
on branch **`fix/piv-consistency-prep`** (from master `8de1517`, **not pushed**),
and what still needs the site. Every touched site in the code carries a
greppable marker:

```bash
grep -rn "PIV-CONSISTENCY" rtsp --include=*.py --include=*.js
```

Tags `[F1]..[F7]` are the findings above; `[A1]..[A11]` are the items below.

## A1 — the camera position never reached the calibration (root cause under F1)

`run_pipeline` built `pyorc.CameraConfig(...)` **without** `lens_position` and
called `set_lens_position()` afterwards. In pyorc 0.9.6, `__init__` runs
`calibrate()` immediately; the later setter only assigns an attribute that
nothing but a plotting helper reads. So the focal-length fit saw only four
coplanar GCPs and no camera-position term. On a plane, focal length and
camera distance trade off almost freely, and the optimizer landed on an
arbitrary point in a flat valley.

The optimizer is `scipy.optimize.differential_evolution` in `pyorc/cv.py:1252`,
called **with no seed**, so it reads numpy's global `RandomState` directly.
That is the RNG consumer Finding 1 could not locate: it bypasses the
module-level `np.random.*` functions that were wrapped.

Measured on `kunah_config.json`, `use_stabilization=False`:

| | unconstrained (master) | `lens_position` passed | + fixed RNG state (branch) |
|---|---|---|---|
| fx over 6 seeds | 1280 – 1290 | 1364 – 1366 | 1363.81, every run |
| fx spread | 0.77 % | 0.14 % | 0 |
| solved camera pos vs entered | 0.56 m | 0.34 m | 0.34 m |
| `mean_speed`, 3 seeds | 0.0907 – 0.1098 | 0.0978 – 0.1031 | 0.10311346, every run |
| `mean_speed` spread | 21 % | 5.3 % | 0 |

Two things follow. The old pipeline was **biased**, not just noisy: fx off by
~6 % and the camera placed half a metre from where the operator measured it.
And a 0.14 % change in fx still moved the mean by 5 %, which is Finding 3's
amplifier at work, not geometry.

## A2 — the stabilization polygon has the wrong polarity

pyorc's `stabilize` polygon must enclose the **water**; everything *outside* it
is used as rigid land for feature tracking (`pyorc/api/video.py`
`set_mask_from_exterior`). The app passes the AOI, a rectangle inside the
river, so open water outside the AOI was tracked as "stable" features by a
RANSAC homography. That, not RANSAC alone, is the likely source of the 11.6 %
swing and most of the 48 % gap between modes in Finding 4. Making both modes
agree is not enough; with this polygon stabilization is wrong in both. A
correct fix needs a separate whole-water-surface polygon from the UI.

## A3 — the `h_ref` mismatch made the water-level sensor inert

pyorc: water plane `z_a = z_0 + (h_a - h_ref)`. With the pipeline's fallback
`h_ref = h_a`, `z_a == z_0` always, so a sensor-updated `h_a` never moved the
plane. The sensor is also read **once per session** at start and frozen into
`_pipeline_config`. Static mode used `h_a = -distance_m`, stream mode
`cam_z - distance_m`; they agree only when the camera is at z = 0.

## A4 — the unported on-site commit already fixes the sub-pixel problem, by a better lever

`b98ec53` (branch `on_site_changes`, still unported; FOLLOWUPS #6 lists only
its CAP_PROP_FPS part) auto-reduces the ortho resolution to reach a 200-px
grid, clipped to 0.005..0.05 m/px. On the Kunah geometry that is 0.01 m/px:
**5x the pixel displacement at the same framestep** (p25 0.57 → ~2.9 px) and a
grid of ~2000 cells instead of 48. Finding 2's remedy of framestep 132 is a
2.2 s gap between paired frames and invites decorrelation. Porting notes:
(a) the on-site version rebuilds the CameraConfig, i.e. re-runs the fit;
pass the first build's `camera_matrix`/`dist_coeffs` into the rebuild
(pyorc returns early when both are given); (b) `piv_window` is in **ortho
pixels**, so 5x finer resolution is a 5x smaller physical interrogation
window (0.5 m → 0.1 m); rescale `piv_window_size`/`piv_overlap` with it, and
expect ~25x the PIV CPU time; (c) the advisor now takes the same
`ortho_resolution` variable; keep it that way.

## A5 — Finding 6 is mostly moot at current defaults

The pipeline reads frames 0–150: ~6 s of a 60 s batch. Any reconnect before
48 s rejects the clip (80 % rule), so back-to-back frames after a gap cannot
reach the analysed frames today; only the uniform silent RTP drop (≤ 20 %,
i.e. ≤ +25 % velocity) can. It also means 90 % of every carefully captured
batch is discarded. This becomes relevant the moment `frames` is raised.

## A6 — the time mean has no minimum count

`piv.mean(dim="time")` skips NaN. A cell that survived the quality mask in
one of six pairs counts at full weight beside one valid in all six. On the
Kunah run 3 of 48 cells are valid in fewer than half the pairs. Candidate
fix: mask cells with valid count < ceil(n_pairs/2) before averaging. Changes
numbers → golden regeneration.

## A7, A10 — non-numeric, marked only

A7: a processor timeout does not kill the worker; the cancel flag is only
checked between steps and step 5 is the long one, so `_processor_busy` is
cleared while a zombie PIV still runs and the next batch starts a second
concurrent pipeline. A10: `_drop_current_batch` is set and never read;
`warn_duration_changed` is never set; the dashboard's "batch dropped and
restarted" message is unreachable (pinned by tests/api/test_routes.py).

## A11 — with 4 GCPs, all calibration residual lands on one point

`pyorc/cv.py solvepnp` uses `cv2.SOLVEPNP_P3P` for exactly 4 GCPs: three are
fitted exactly, the fourth only disambiguates. The new "GCP reprojection"
log line shows the Kunah set at `[0.0, 0.0, 0.0, 70 px]` on master and
`[0.0, 0.0, 0.0, 92 px]` with the lens-position constraint. **The fourth GCP
(px 209.9, 715.27 → world −2.1844, 0) is inconsistent with the other three
and the measured camera position by ~90 px, i.e. ~5 % of the frame width.**
No solver choice fixes that. It needs a field action: re-click / re-survey
that point, or add a fifth GCP (pyorc then switches to iterative least
squares and spreads the residual). Also note 2D mode **drops the GCP z**;
GCPs on the bank rather than the water plane shift the whole geometry.

## What the branch changes (one commit each, oldest first)

| Commit | Change | Numbers |
|---|---|---|
| markers | `PIV-CONSISTENCY` comments everywhere; `FRAMESTEP` comment corrected | none |
| logging | per-run `<stem>_debug.json` + log: env versions, config sha1, RNG fingerprint, camera matrix / extrinsics, solved-vs-entered camera position, per-GCP reprojection error, `z_a` with inputs, pyorc Video fps/range, time-axis dt stats (dropped-frame detection), PIV validity / corr / s2n before and after the mask, raw-vs-filtered summary. Processor logs a per-batch config sha1. Capture always logs effective-vs-nominal fps. | none |
| crash guards | Modbus print degrades to ASCII on `UnicodeEncodeError` (FOLLOWUPS #7); advisor skips on fps ≤ 0; pipeline sanitises CAP_PROP_FPS (1..240, else 25 with a loud WARNING, forced onto pyorc.Video); one `ortho_resolution` for CameraConfig and advisor | none |
| advisor cap (test, then code) | `min(30, ...)` removed; notes the frame gap in seconds and points at A4 | none (log only) |
| h_ref / sensor | `resolve_h_ref`: top-level > `gcps.h_ref` > `h_a`; static mode uses `cam_z - distance_m` like stream mode | none on Kunah (h_ref == h_a) |
| stabilization | default `False` in the pipeline and set explicitly in static mode; WARNING if enabled | none (golden sets it explicitly) |
| lens_position | passed into `CameraConfig(...)` | **changes** |
| fixed RNG state | CameraConfig built inside `_seeded_numpy_rng(INTRINSICS_RNG_SEED)`, previous state restored | **changes** (removes the residual wobble) |
| golden regen | `expected.json` regenerated on the two commits above; comment in the golden test corrected | — |

New tests: `test_modbus.py` (ASCII fallback), `test_diagnostics.py` (fps=0,
cap lifted), `test_pipeline_config.py` (resolve_h_ref), `test_static_routes.py`
(sensor formula, stabilization default), `test_intrinsics_determinism.py`
(real pyorc on the Kunah GCPs, no video). Fast suite 167 passed; golden 1
passed on the regenerated numbers.

**Not changed, on purpose:** `filter_velocity_field` (F3), the time-mean
min-count (A6), `frames`/`framestep` defaults, the resolution port (A4),
`_drop_current_batch` (A10), the processor timeout (A7), the recording-fps
gate (F6). Each either changes the numbers without a way to validate them
here, or needs a decision about the site.

## What is and is not verified

* Verified: every number in this addendum was measured on the Kunah fixture
  on this machine; the fast suite and golden are green at the branch head;
  two **unseeded** production-path runs on the branch head give bit-identical
  summaries.
* Not verified: whether the new numbers are *closer to the truth*. The old
  ones were reproducible only under a seed and came from a fit that ignored
  the camera position; the new ones use it. Neither has been checked against
  a field reference. That is the golden-regeneration caveat, stated in its
  commit.
* Not run: anything against the real camera, the sensor, or the browser.

## Checklist for the site (in this order)

1. Run one batch, open `<stem>_debug.json`. Read `camera.gcp_reprojection_px`,
   `camera.lens_position_error_m`, `time_axis_*`, `piv_quality_masked`. If a
   GCP reprojects > 10 px, fix the GCPs before touching anything else (A11).
2. Add a fifth GCP if at all possible. Re-check the reprojection line.
3. Confirm `lens_position` is a measurement, not a guess; it now constrains
   the geometry (A1). The camera-position |diff| line should be ≲ 0.2 m.
4. Water level: enter waterZ once at survey time; with the sensor enabled,
   `h_a - h_ref` in the log is the level change since the survey (A3). Decide
   whether the sensor should be re-read per batch (processor.py).
5. Port A4 (resolution) **with** the window rescale, or raise `framestep`
   per the advisor, and raise `frames` well above 150; then re-check that
   the framestep sweep in Finding 2 has gone flat.
6. Only then revisit the filter (F3) and the min-count (A6); regenerate the
   golden with a field justification.
7. Once a site calibration is trusted, pin it: `use_fixed_intrinsics: true` +
   `camera_matrix` in the config. `INTRINSICS_RNG_SEED` is then irrelevant.
