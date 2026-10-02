# TODO — RTSP Streaming Pipeline

---

## Integrate P₃ auto-framestep from quasi-automated pipeline

**RESOLVED by the quasi-v2 pipeline swap.** The pipeline in `rtsp/piv/` is now quasi-v2
itself (Bodart 2024 quasi-automated/assisted LSPIV) — there is no separate `runners/`
folder or built-in `piv_runner.py` to port P₃ into any more; `rtsp/piv/auto_params.py`
already implements P₀/P₂/P₃ auto-tuning, and `rtsp/piv/pipeline.py` uses it directly. The
plan below is kept for historical context only.

**Priority:** High — currently using hardcoded `FRAMESTEP = 25` which
may be wrong for the actual flow conditions at a given site.

### Background

The `runners/quasi_automated_bodart2024/piv_runner_quasi_automated_v2.py`
file implements the Bodart et al. (2024) quasi-automated LSPIV framework:

> Bodart, J. et al. (2024). "A framework for quasi-automated large-scale
> particle image velocimetry (LSPIV) discharge measurements."
> *Water Resources Research.* https://doi.org/10.1029/2023WR036198

It includes four parameter-assistant tools (P₀–P₃):

| Tool | What it does | How |
|------|-------------|-----|
| **P₀** | Auto resolution (m/px) | Computed from GCP point density |
| **P₁** | Water-only grid | Masks out non-water cells from PIV grid |
| **P₂** | Auto searching area | User marks particle displacement spots; algorithm computes optimal PIV search area |
| **P₃** | Auto framestep | Mini-PIV on ~20 frames, scale displacement linearly to find optimal temporal gap |

### How P₃ works (the "smaller LSPIV on a shorter video" step)

1. Read only ~20 frames from the video (not the full clip)
2. Run a quick PIV with coarse grid (IA=40, no overlap)
3. Get velocity distribution at framestep=1 (consecutive frames)
4. Scale displacement linearly for framestep=2, 3, 4...
   (`disp(fs) = disp(1) × fs` — valid because velocity in m/s is
   independent of framestep)
5. Find the smallest framestep where 75% of cells have >3 px
   displacement (the Bodart P₃ rule)

### What's missing

**None of this runs in `rtsp/piv_runner.py`.** The streaming pipeline
uses a hardcoded `FRAMESTEP = 25` and only provides a post-hoc
recommendation after the full run completes.

### What needs to happen

- Port `compute_auto_framestep()` (P₃) from
  `runners/quasi_automated_bodart2024/piv_runner_quasi_automated_v2.py`
  into `rtsp/piv_runner.py`
- Run P₃ on the **first two clean batches** of a pipeline session
  (Step 6 — after AOI, GCPs, and all calibration are configured).
  Take the **larger** of the two framestep results — this ensures
  even the slowest-flow cells in the AOI have enough pixel
  displacement (≥3 px) for reliable PIV cross-correlation.
- **NOT** on the 3 manual snapshot videos from Step 2. Those are
  recorded before calibration (no GCPs, no AOI, no CameraConfig)
  and cannot be used for PIV parameter tuning.
- Only videos that passed all quality checks (budget countdown,
  stall rejection, early-disruption retry) are used for P₃.
  Rejected videos never reach this step.
- Lock in the computed framestep for all subsequent batches in the
  same session (no need to re-run P₃ every batch — river flow is
  stable over the session timescale)
- Use the computed framestep for the actual `get_piv()` call instead
  of the hardcoded `FRAMESTEP = 25`

### Also consider

- Porting P₀ (auto resolution) and P₁ (water-only grid)
- P₂ (displacement spots) requires user interaction and may not be
  suitable for the automated streaming pipeline
