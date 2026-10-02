import math
import pathlib
from typing import Optional

import numpy as np

from streaming.config import cv2
from streaming.models.fitness_verdict import FitnessVerdict

PAIR_COUNT = 12
FRAME_GAP = 10
WINDOW_PX = 64
MIN_WINDOW_INSIDE = 0.75
FLAT_STD = 3.0
SATURATED_GREY = 250

START_SCORE = 10.0
WEAK_TEXTURE_STD = 5.0
MODEST_TEXTURE_STD = 10.0
WEAK_TEXTURE_PENALTY = 4.0
MODEST_TEXTURE_PENALTY = 2.0
FLAT_PENALTY_PER_FRACTION = 16.0
MAX_FLAT_PENALTY = 4.0
MIN_REPORTED_PENALTY = 0.5
HEAVY_GLARE_FRACTION = 0.05
LIGHT_GLARE_FRACTION = 0.01
HEAVY_GLARE_PENALTY = 3.0
LIGHT_GLARE_PENALTY = 1.0
VERY_STATIONARY_CORRELATION = 0.9
STATIONARY_CORRELATION = 0.7
VERY_STATIONARY_PENALTY = 4.0
STATIONARY_PENALTY = 2.0
DARK_BRIGHTNESS = 30.0
DARK_PENALTY = 3.0
LOW_CONFIDENCE_SCORE = 6.0

MAX_CAMERA_SHIFT_PX = 3.0


def assess_clip_fitness(clip_path: pathlib.Path, pipeline_config: dict,
                        reference_frame_path: Optional[pathlib.Path]) -> FitnessVerdict:
    pairs = _read_frame_pairs(clip_path)
    if not pairs:
        return FitnessVerdict(score=0.0, status="low_confidence",
                              reasons=["clip could not be read"], metrics={})

    mask = _aoi_mask(pairs[0][0].shape, pipeline_config.get("aoi_corners"))
    metrics = _surface_metrics(pairs, mask)
    score, reasons = _score_surface(metrics)

    metrics["camera_shift_px"] = None
    camera_moved = False
    if not pipeline_config.get("aoi_corners"):
        reasons.append("no area of interest — cannot check camera position")
    elif reference_frame_path is not None and pathlib.Path(reference_frame_path).exists():
        shift_px, reason = _camera_shift_px(pairs[0][0], reference_frame_path, mask)
        metrics["camera_shift_px"] = shift_px
        if reason:
            reasons.append(reason)
        if shift_px is not None and shift_px > MAX_CAMERA_SHIFT_PX:
            camera_moved = True
            reasons.append(f"camera has moved by {shift_px:.1f} px since the GCPs "
                           "were marked — recalibrate")

    if camera_moved:
        status = "invalid"
    elif score <= LOW_CONFIDENCE_SCORE:
        status = "low_confidence"
    else:
        status = "ok"
    return FitnessVerdict(score=score, status=status, reasons=reasons, metrics=metrics)


def _read_frame_pairs(clip_path):
    cap = cv2.VideoCapture(str(clip_path))
    try:
        if not cap.isOpened():
            return []
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= FRAME_GAP:
            return []
        starts = sorted(set(np.linspace(0, total - 1 - FRAME_GAP, PAIR_COUNT)
                            .round().astype(int).tolist()))
        wanted = set(starts) | {start + FRAME_GAP for start in starts}
        grey = {}
        for index in range(max(wanted) + 1):
            if index in wanted:
                ok, frame = cap.read()
                if not ok:
                    break
                grey[index] = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            elif not cap.grab():
                break
        return [(grey[start], grey[start + FRAME_GAP])
                for start in starts if start + FRAME_GAP in grey]
    finally:
        cap.release()


def _aoi_mask(shape, aoi_corners):
    if not aoi_corners:
        return np.full(shape, 255, np.uint8)
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.asarray(aoi_corners, np.int32).reshape(-1, 1, 2)], 255)
    return mask


def _surface_metrics(pairs, mask):
    x, y, w, h = cv2.boundingRect(mask)
    inside = mask[y:y + h, x:x + w] > 0

    windows = []
    for top in range(0, h - WINDOW_PX + 1, WINDOW_PX):
        for left in range(0, w - WINDOW_PX + 1, WINDOW_PX):
            window_inside = inside[top:top + WINDOW_PX, left:left + WINDOW_PX]
            if window_inside.mean() >= MIN_WINDOW_INSIDE:
                windows.append((slice(top, top + WINDOW_PX),
                                slice(left, left + WINDOW_PX), window_inside))

    stds = []
    correlations = []
    brightness = []
    saturated = []
    for first, second in pairs:
        first_aoi = first[y:y + h, x:x + w].astype(np.float32)
        second_aoi = second[y:y + h, x:x + w].astype(np.float32)
        water = first_aoi[inside]
        brightness.append(float(water.mean()))
        saturated.append(float(np.mean(water >= SATURATED_GREY)))
        for rows, cols, window_inside in windows:
            a = first_aoi[rows, cols][window_inside]
            std = float(a.std())
            stds.append(std)
            if std < FLAT_STD:
                continue
            b = second_aoi[rows, cols][window_inside]
            correlations.append(float(np.corrcoef(a, b)[0, 1]) if b.std() > 0 else 0.0)

    return {
        "sample_pairs": len(pairs),
        "window_count": len(stds),
        "texture_std": float(np.median(stds)) if stds else None,
        "flat_fraction": float(np.mean(np.array(stds) < FLAT_STD)) if stds else None,
        "saturated_fraction": float(np.mean(saturated)),
        "mean_brightness": float(np.mean(brightness)),
        "stationary_correlation": float(np.median(correlations)) if correlations else None,
    }


def _score_surface(metrics):
    score = START_SCORE
    reasons = []

    texture_std = metrics["texture_std"]
    if texture_std is None:
        reasons.append(f"area of interest smaller than one {WINDOW_PX}x{WINDOW_PX} "
                       "window — texture not assessed")
    elif texture_std < WEAK_TEXTURE_STD:
        score -= WEAK_TEXTURE_PENALTY
        reasons.append(f"weak surface texture (median contrast {texture_std:.1f})")
    elif texture_std < MODEST_TEXTURE_STD:
        score -= MODEST_TEXTURE_PENALTY
        reasons.append(f"modest surface texture (median contrast {texture_std:.1f})")

    flat_fraction = metrics["flat_fraction"]
    if flat_fraction is not None:
        flat_penalty = min(MAX_FLAT_PENALTY, FLAT_PENALTY_PER_FRACTION * flat_fraction)
        score -= flat_penalty
        if flat_penalty >= MIN_REPORTED_PENALTY:
            reasons.append(f"featureless water: {100 * flat_fraction:.0f} % of the "
                           "area has no visible pattern")

    saturated_fraction = metrics["saturated_fraction"]
    if saturated_fraction > HEAVY_GLARE_FRACTION:
        score -= HEAVY_GLARE_PENALTY
    elif saturated_fraction > LIGHT_GLARE_FRACTION:
        score -= LIGHT_GLARE_PENALTY
    if saturated_fraction > LIGHT_GLARE_FRACTION:
        reasons.append(f"glare: {100 * saturated_fraction:.1f} % of the water is pure white")

    correlation = metrics["stationary_correlation"]
    if correlation is not None and correlation > STATIONARY_CORRELATION:
        score -= (VERY_STATIONARY_PENALTY if correlation > VERY_STATIONARY_CORRELATION
                  else STATIONARY_PENALTY)
        reasons.append("surface pattern barely moves — likely reflections or calm water "
                       f"(frame-to-frame correlation {correlation:.2f})")

    if metrics["mean_brightness"] < DARK_BRIGHTNESS:
        score -= DARK_PENALTY
        reasons.append(f"too dark (mean brightness {metrics['mean_brightness']:.0f})")

    return round(min(START_SCORE, max(0.0, score)), 1), reasons


def _camera_shift_px(first_grey, reference_frame_path, mask):
    reference = cv2.imread(str(reference_frame_path), cv2.IMREAD_GRAYSCALE)
    if reference is None:
        return None, None
    if reference.shape != first_grey.shape:
        return None, "reference frame size differs — cannot check camera position"
    water = mask > 0
    reference = reference.astype(np.float32)
    current = first_grey.astype(np.float32)
    reference[water] = reference.mean()
    current[water] = current.mean()
    height, width = current.shape
    window = cv2.createHanningWindow((width, height), cv2.CV_32F)
    (dx, dy), _ = cv2.phaseCorrelate(reference, current, window)
    shift_px = math.hypot(dx, dy)
    return (None, None) if math.isnan(shift_px) else (round(shift_px, 2), None)
