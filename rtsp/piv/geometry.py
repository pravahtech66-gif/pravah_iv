import numpy as np


def normalize_aoi_corners(corners):
    arr = np.asarray(corners, dtype=float)
    if arr.shape != (4, 2):
        raise RuntimeError(f"aoi_corners must be shape (4,2), got {arr.shape}")
    center = arr.mean(axis=0)
    angles = np.arctan2(arr[:, 1] - center[1], arr[:, 0] - center[0])
    arr = arr[np.argsort(angles)]
    start = np.argmin(arr[:, 0] + arr[:, 1])
    arr = np.roll(arr, -start, axis=0)
    if arr[1, 1] > arr[3, 1]:
        arr = np.array([arr[0], arr[3], arr[2], arr[1]], dtype=float)
    return arr.tolist()


def sanitize_dist_coeffs(dist_coeffs):
    if dist_coeffs is None:
        return [[0.0], [0.0], [0.0], [0.0], [0.0]]
    arr = np.asarray(dist_coeffs, dtype=float).reshape(-1)
    if arr.size < 5:
        arr = np.pad(arr, (0, 5 - arr.size), mode="constant", constant_values=0.0)
    else:
        arr = arr[:5]
    return [[float(v)] for v in arr]
