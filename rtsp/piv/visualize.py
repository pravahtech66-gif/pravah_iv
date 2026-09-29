import pathlib

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .job_log import _log


def save_camera_overlay(job_state, video_obj, piv_ds_mean, output_path: pathlib.Path) -> None:
    try:
        try:
            ortho_frame = video_obj.get_frame(0, method="ortho")
        except Exception:
            ortho_frame = None

        x_coords = piv_ds_mean.coords["x"].values
        y_coords = piv_ds_mean.coords["y"].values
        vx = piv_ds_mean["v_x"].values
        vy = piv_ds_mean["v_y"].values
        spd = np.sqrt(vx ** 2 + vy ** 2)

        x_min, x_max = float(x_coords.min()), float(x_coords.max())
        y_min, y_max = float(y_coords.min()), float(y_coords.max())

        fig, ax = plt.subplots(figsize=(16, 9), dpi=120)

        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.set_facecolor("#e8f4f8")
        _log(job_state, "  Overlay: plain background (real-world coordinates)")

        X, Y = np.meshgrid(x_coords, y_coords)
        valid = ~np.isnan(spd)

        if valid.any():
            q = ax.quiver(
                X[valid], Y[valid],
                vx[valid], vy[valid],
                spd[valid],
                cmap="RdYlGn",
                alpha=0.85,
                scale_units="xy",
                scale=1.0,
                width=0.003,
            )
            plt.colorbar(q, ax=ax, label="Speed (m/s)", shrink=0.6, pad=0.01)

        ax.set_title("Velocity vectors (orthorectified view)")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")

        fig.savefig(str(output_path), bbox_inches="tight", pad_inches=0)
        plt.close(fig)
        _log(job_state, f"  Orthorectified overlay saved → {output_path}")

    except Exception as e:
        plt.close("all")
        _log(job_state, f"  WARNING: Orthorectified overlay failed: {e}")


def visualize(job_state, results, video_path, output_path: pathlib.Path) -> None:
    spd_raw = results.get("speed_raw", results["speed"])
    spd = results["speed"]
    v_x = results["v_x"]
    v_y = results["v_y"]
    x_coords = results["x_coords"]
    y_coords = results["y_coords"]
    has_flow = "v_along" in results

    x_min, x_max = float(x_coords.min()), float(x_coords.max())
    y_min, y_max = float(y_coords.min()), float(y_coords.max())

    X, Y = np.meshgrid(x_coords, y_coords)

    n_panels = 3 if has_flow else 2
    fig, axes = plt.subplots(1, n_panels, figsize=(7 * n_panels, 5))
    fig.suptitle(
        f"[PYORC v3] PIV - real-world calibrated (m/s)\n{video_path}",
        fontsize=9,
    )

    im = axes[0].imshow(
        spd_raw, cmap="inferno", origin="upper", aspect="equal",
        extent=[x_min, x_max, y_min, y_max],
    )
    plt.colorbar(im, ax=axes[0], label="Speed (m/s)")

    filter_mask = np.isnan(spd) & ~np.isnan(spd_raw)
    if np.any(filter_mask):
        mask_rgba = np.zeros((*spd_raw.shape, 4))
        mask_rgba[filter_mask] = [0.5, 0.5, 0.5, 0.5]
        axes[0].imshow(
            mask_rgba, origin="upper", aspect="equal",
            extent=[x_min, x_max, y_min, y_max],
        )

    axes[0].set_title("Speed heatmap (gray = filtered out)")
    axes[0].set_xlabel("x (m)")
    axes[0].set_ylabel("y (m)")

    step = max(1, spd.shape[0] // 15)
    axes[1].quiver(
        X[::step, ::step], Y[::step, ::step],
        v_x[::step, ::step], v_y[::step, ::step],
        spd[::step, ::step],
        cmap="inferno", scale_units="xy", scale=1.0, width=0.003,
    )
    axes[1].set_title("Velocity vectors (filtered)")
    axes[1].set_xlabel("x (m)")
    axes[1].set_ylabel("y (m)")
    axes[1].set_aspect("equal")

    if has_flow:
        flow_uv_main = results["flow_unit_vector"]
        cx = 0.5 * (x_min + x_max)
        cy = 0.5 * (y_min + y_max)
        big_len = 0.30 * (x_max - x_min)
        for _ax in (axes[0], axes[1]):
            _ax.annotate(
                "",
                xy=(cx + flow_uv_main[0] * big_len, cy + flow_uv_main[1] * big_len),
                xytext=(cx - flow_uv_main[0] * big_len, cy - flow_uv_main[1] * big_len),
                arrowprops=dict(arrowstyle="-|>", color="lime", lw=3.5,
                                mutation_scale=22),
            )
            _ax.text(
                cx, cy, f"  flow {results['flow_angle_deg']:.0f}°",
                color="lime", fontsize=9, fontweight="bold",
                ha="left", va="bottom",
            )

    if has_flow:
        v_along = results["v_along"]
        angle_deg = results["flow_angle_deg"]

        vmax = max(abs(np.nanmin(v_along)), abs(np.nanmax(v_along)))
        if vmax < 1e-9:
            vmax = 1.0

        im3 = axes[2].imshow(
            v_along, cmap="RdBu_r", origin="upper", aspect="equal",
            extent=[x_min, x_max, y_min, y_max],
            vmin=-vmax, vmax=vmax,
        )
        plt.colorbar(im3, ax=axes[2], label="v_along (m/s)")
        _coh = results.get("flow_coherence")
        _coh_txt = f" | coherence {_coh:.2f}" if _coh is not None else ""
        axes[2].set_title(f"Along-stream velocity (m/s)\nauto flow dir: {angle_deg:.1f} deg{_coh_txt}")
        axes[2].set_xlabel("x (m)")
        axes[2].set_ylabel("y (m)")

        flow_uv = results["flow_unit_vector"]
        arrow_x = x_min + 0.1 * (x_max - x_min)
        arrow_y = y_min + 0.1 * (y_max - y_min)
        arrow_len = 0.08 * (x_max - x_min)
        axes[2].annotate(
            "",
            xy=(arrow_x + flow_uv[0] * arrow_len, arrow_y + flow_uv[1] * arrow_len),
            xytext=(arrow_x, arrow_y),
            arrowprops=dict(arrowstyle="->", color="green", lw=3),
        )

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(output_path), dpi=130, bbox_inches="tight")
    plt.close(fig)
    _log(job_state, f"Velocity field saved -> {output_path}")
