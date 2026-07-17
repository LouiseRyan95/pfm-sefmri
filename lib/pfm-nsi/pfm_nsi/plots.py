import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None


def _local_predict_binom_logit(mdl: Dict[str, Any], nsi: np.ndarray) -> np.ndarray:
    x = nsi - float(np.asarray(mdl["muNSI"]).squeeze())
    form = str(np.asarray(mdl["form"]).squeeze())
    beta = np.asarray(mdl["beta"]).reshape(-1)
    if form == "linear":
        eta = beta[0] + beta[1] * x
    elif form == "quadratic":
        eta = beta[0] + beta[1] * x + beta[2] * (x ** 2)
    else:
        raise ValueError("Bad model form")
    p = 1.0 / (1.0 + np.exp(-eta))
    return p.reshape(np.shape(nsi))


def _expert_judgement_j() -> Dict[str, float]:
    return {"min": 0.39, "mean": 0.43, "max": 0.488}


def pfm_nsi_plots(
    qc: Dict[str, Any],
    usability_mdl: Optional[Dict[str, Any]] = None,
    show_plots: bool = True,
    save_dir: Optional[str] = None,
    prefix: str = "pfm_nsi",
    dpi: int = 150,
    network_histograms: bool = False,
    network_assignment_lambda: float = 10.0,
    structure_histograms: bool = False,
    structure_assignment_lambda: float = 10.0,
) -> Dict[str, Any]:
    if show_plots and plt is None:
        raise RuntimeError("matplotlib is required for plotting.")
    out: Dict[str, Any] = {}
    headline_lambda = 10
    ridge_tag = f"Lambda{headline_lambda}"

    nsi_r2 = np.asarray(qc["NSI"]["Ridge"][ridge_tag]["R2"]).astype(float).ravel()
    mi = np.asarray(qc.get("MoransI", {}).get("mI", [])).astype(float).ravel()
    slope = np.asarray(qc.get("SpectralSlope", {}).get("slope", [])).astype(float).ravel()

    out["data"] = {"NSI_r2": nsi_r2, "MI": mi, "Slope": slope}

    has_usability = (
        isinstance(usability_mdl, dict)
        and "model" in usability_mdl
        and "grid" in usability_mdl
        and "thresholds" in usability_mdl
    )

    if has_usability:
        summary_statistic = "median"
        nsi_use = float(np.nanmedian(nsi_r2))
        p_hat = float(_local_predict_binom_logit(usability_mdl["model"], nsi_use))
        grid = usability_mdl["grid"]
        xgrid = np.asarray(grid["x"]).reshape(-1)
        ci_lo = np.interp(nsi_use, xgrid, np.asarray(grid["ciLo"]).reshape(-1))
        ci_hi = np.interp(nsi_use, xgrid, np.asarray(grid["ciHi"]).reshape(-1))

        if p_hat >= 0.8:
            label = "High (0.8-1.0)"
        elif p_hat >= 0.6:
            label = "Moderate-high (0.6-0.8)"
        elif p_hat >= 0.4:
            label = "Moderate (0.4-0.6)"
        elif p_hat >= 0.2:
            label = "Low (0.2-0.4)"
        else:
            label = "Very low (0.0-0.2)"

        out["usability"] = {
            "summary_statistic": summary_statistic,
            "summary_nsi": nsi_use,
            "NSI_median": nsi_use,
            "NSI_mean": nsi_use,
            "p_hat": p_hat,
            "ci95": [ci_lo, ci_hi],
            "decision": label,
            "thresholds": usability_mdl["thresholds"],
            "expert_judgement_j": _expert_judgement_j(),
        }

        print("\n=== Prospective PFM usability projection ===\n")
        print("Dataset summary")
        print(f"  Summary NSI ({summary_statistic}, R^2, λ={headline_lambda}): {nsi_use:.3f}\n")
        print("Predicted usability (from trained NSI model)")
        print(f"  P(PFM-usable | NSI):         {p_hat:.2f}")
        print(f"  95% confidence interval:     [{ci_lo:.2f}, {ci_hi:.2f}]")
        print(f"  Decision band:               {label}\n")
        j = _expert_judgement_j()
        print("Expert-judgement J thresholds")
        print(f"  min J:                        {j['min']:.3f}")
        print(f"  mean J:                       {j['mean']:.3f}")
        print(f"  max J:                        {j['max']:.3f}")
        print("\n===========================================\n")

        if show_plots:
            fig = _plot_nsi_usability_curve_from_model(usability_mdl, nsi_use, p_hat)
            if save_dir:
                fig.savefig(f"{save_dir}/{prefix}_usability_curve.png", dpi=dpi, bbox_inches="tight")

    if show_plots:
        if plt is None:
            raise RuntimeError("matplotlib is required for plotting.")
        fig = _plot_hist_gray(nsi_r2, "NSI")
        if save_dir:
            fig.savefig(f"{save_dir}/{prefix}_hist_nsi.png", dpi=dpi, bbox_inches="tight")
        if mi.size:
            fig = _plot_hist_gray(mi, "Moran's I")
            if save_dir:
                fig.savefig(f"{save_dir}/{prefix}_hist_moransI.png", dpi=dpi, bbox_inches="tight")
        if slope.size:
            fig = _plot_hist_gray(slope, "Spectral slope")
            if save_dir:
                fig.savefig(f"{save_dir}/{prefix}_hist_slope.png", dpi=dpi, bbox_inches="tight")

        if "SpectralSlope" in qc and "freq" in qc["SpectralSlope"] and "power" in qc["SpectralSlope"]:
            freq = np.asarray(qc["SpectralSlope"]["freq"])
            power = np.asarray(qc["SpectralSlope"]["power"])
            if freq.size and power.size and power.ndim == 2:
                fig = _plot_power_spectra(freq, power)
                if save_dir:
                    fig.savefig(f"{save_dir}/{prefix}_power_spectra.png", dpi=dpi, bbox_inches="tight")

        if network_histograms:
            ridge_tag = f"Lambda{float(network_assignment_lambda):g}"
            net = qc.get("NSI", {}).get("NetworkAssignment", {}).get(ridge_tag, {})
            net_idx = np.asarray(net.get("NetworkIndex", []), dtype=int).ravel()
            net_labels = net.get("NetworkLabels", [])
            net_colors = net.get("NetworkColors", None)
            if net_idx.size and len(net_labels):
                fig = _plot_network_nsi_histograms(
                    nsi_r2, net_idx, net_labels, net_colors=net_colors, x_limits=_finite_x_limits(nsi_r2)
                )
                if save_dir:
                    fig.savefig(f"{save_dir}/{prefix}_hist_nsi_by_network.png", dpi=dpi, bbox_inches="tight")
        if structure_histograms:
            ridge_tag = f"Lambda{float(structure_assignment_lambda):g}"
            st = qc.get("NSI", {}).get("StructureAssignment", {}).get(ridge_tag, {})
            labels_by_target = st.get("StructureLabelsByTarget", [])
            labels_unique = st.get("StructureLabelsUnique", [])
            if len(labels_by_target) and len(labels_unique):
                fig = _plot_structure_nsi_histograms(
                    nsi_r2, labels_by_target, labels_unique, x_limits=_finite_x_limits(nsi_r2)
                )
                if save_dir:
                    fig.savefig(f"{save_dir}/{prefix}_hist_nsi_by_structure.png", dpi=dpi, bbox_inches="tight")

    return out


def plot_nsi_usability_distribution(
    nsi_values: Sequence[float],
    usability_mdl: Dict[str, Any],
    show_plot: bool = True,
    save_path: Optional[str] = None,
    dpi: int = 150,
) -> Dict[str, Any]:
    if show_plot and plt is None:
        raise RuntimeError("matplotlib is required for plotting.")

    nsi = np.asarray(nsi_values, dtype=float).ravel()
    nsi = nsi[np.isfinite(nsi)]
    if nsi.size == 0:
        raise ValueError("No finite NSI values were provided.")

    p_hat = _local_predict_binom_logit(usability_mdl["model"], nsi).astype(float).ravel()
    p_hat = np.clip(p_hat, 0.0, 1.0)

    cat_edges = np.array([0.0, 0.2, 0.4, 0.6, 0.8, 1.0], dtype=float)
    cat_names = [
        "Very low (0.0-0.2)",
        "Low (0.2-0.4)",
        "Moderate (0.4-0.6)",
        "Moderate-high (0.6-0.8)",
        "High (0.8-1.0)",
    ]

    # Include p=1.0 in the last bin.
    p_adj = np.minimum(p_hat, np.nextafter(1.0, 0.0))
    counts, _ = np.histogram(p_adj, bins=cat_edges)
    perc = 100.0 * counts / max(1, p_hat.size)

    summary_rows: List[Dict[str, Any]] = []
    for i, name in enumerate(cat_names):
        summary_rows.append(
            {
                "category": name,
                "count": int(counts[i]),
                "percent": float(perc[i]),
            }
        )

    out: Dict[str, Any] = {
        "n": int(p_hat.size),
        "mean_p_hat": float(np.nanmean(p_hat)),
        "nsi": nsi,
        "p_hat": p_hat,
        "summary": summary_rows,
    }

    if not show_plot:
        return out

    fig = plt.figure(figsize=(5.2, 3.2), facecolor="white")
    ax = fig.add_subplot(111)
    ax.set_ylim(0.0, 1.0)
    ax.set_yticks(np.arange(0.0, 1.01, 0.2))

    bands = [
        (0.0, 0.2, (0.65, 0.15, 0.15)),
        (0.2, 0.4, (0.85, 0.35, 0.35)),
        (0.4, 0.6, (0.95, 0.85, 0.30)),
        (0.6, 0.8, (0.70, 0.85, 0.45)),
        (0.8, 1.0, (0.35, 0.75, 0.45)),
    ]
    for ylo, yhi, col in bands:
        ax.axhspan(ylo, yhi, color=col, alpha=0.10, zorder=0)

    bins = np.arange(0.0, 1.0001, 0.05)
    h, edges = np.histogram(p_adj, bins=bins)
    frac = h.astype(float) / max(1, p_hat.size)
    y_ctr = edges[:-1] + np.diff(edges) / 2.0
    bar_h = np.diff(edges).mean() * 0.95

    x_max = max(1e-12, float(np.max(frac)) if frac.size else 1.0)
    ax.set_xlim(0.0, x_max * 1.12)
    ax.barh(y_ctr, frac, height=bar_h, color=(0.10, 0.10, 0.10), alpha=0.30, edgecolor="none", zorder=2)

    x_txt = ax.get_xlim()[1] * 0.985
    y_mid = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    for i, y in enumerate(y_mid):
        ax.text(
            x_txt,
            y,
            f"{perc[i]:.1f}%",
            ha="right",
            va="center",
            fontsize=10,
            color=(0.15, 0.15, 0.15),
        )

    ax.set_xlabel("Fraction of samples")
    ax.set_ylabel("P(PFM-usable)")
    ax.tick_params(direction="out")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    out["figure"] = fig
    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches="tight")
    return out

def _plot_network_nsi_histograms(
    nsi_vals: np.ndarray,
    net_idx: np.ndarray,
    net_labels: Sequence[str],
    net_colors: Optional[Sequence[Sequence[float]]] = None,
    x_limits: Optional[Sequence[float]] = None,
):
    nsi_vals = np.asarray(nsi_vals, dtype=float).ravel()
    net_idx = np.asarray(net_idx, dtype=int).ravel()
    n_nets = len(net_labels)

    if n_nets <= 0:
        raise ValueError("No network labels were provided.")
    if nsi_vals.size != net_idx.size:
        raise ValueError("NSI values and network assignment vectors must have equal length.")

    colors = None
    if net_colors is not None:
        arr = np.asarray(net_colors, dtype=float)
        if arr.ndim == 2 and arr.shape[0] >= n_nets and arr.shape[1] >= 3:
            colors = arr[:n_nets, :3]
    nrows = 10
    ncols = max(2, int(np.ceil(n_nets / nrows)))
    fig_h = 11.5
    fig_w = 8.8 if ncols == 2 else 4.4 * ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(fig_w, fig_h), facecolor="white", squeeze=False)
    flat_axes = axes.ravel(order="F")

    for k in range(1, n_nets + 1):
        ax = flat_axes[k - 1]
        vals = nsi_vals[net_idx == k]
        vals = vals[np.isfinite(vals)]
        if colors is not None:
            color = tuple(colors[k - 1])
        else:
            cmap = plt.get_cmap("tab20")
            color = cmap((k - 1) % 20)
        if vals.size:
            ax.hist(vals, bins=30, color=color, edgecolor="none", alpha=0.75)
            med = float(np.nanmedian(vals))
            yl = ax.get_ylim()
            ax.plot([med, med], yl, color="k", linewidth=1)
            ax.set_ylim(yl)
        if x_limits is not None:
            ax.set_xlim(float(x_limits[0]), float(x_limits[1]))
        ax.set_ylabel("Count")
        ax.set_title(f"{net_labels[k - 1]}", loc="left", fontsize=10, fontweight="normal")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out")

    for i in range(n_nets, len(flat_axes)):
        flat_axes[i].axis("off")

    for c in range(ncols):
        axes[-1, c].set_xlabel("NSI (R^2)")
    fig.tight_layout(h_pad=0.8, w_pad=0.9)
    return fig


def _plot_structure_nsi_histograms(
    nsi_vals: np.ndarray,
    structure_labels_by_target: Sequence[str],
    structure_labels_unique: Sequence[str],
    x_limits: Optional[Sequence[float]] = None,
):
    nsi_vals = np.asarray(nsi_vals, dtype=float).ravel()
    labels = np.asarray([str(s) for s in structure_labels_by_target], dtype=object).ravel()
    uniq = [str(s) for s in structure_labels_unique]
    if nsi_vals.size != labels.size:
        raise ValueError("NSI values and structure label vectors must have equal length.")
    counts = {name: int(np.sum(labels == name)) for name in uniq}
    uniq = sorted(uniq, key=lambda n: counts.get(n, 0), reverse=True)
    n_struct = len(uniq)
    if n_struct <= 0:
        raise ValueError("No structure labels were provided.")

    gray_levels = np.linspace(0.25, 0.75, max(n_struct, 2))
    nrows = 10
    ncols = max(2, int(np.ceil(n_struct / nrows)))
    fig_h = 11.5
    fig_w = 8.8 if ncols == 2 else 4.4 * ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(fig_w, fig_h), facecolor="white", squeeze=False)
    flat_axes = axes.ravel(order="F")
    for i, name in enumerate(uniq):
        ax = flat_axes[i]
        vals = nsi_vals[labels == name]
        vals = vals[np.isfinite(vals)]
        g = float(gray_levels[i])
        if vals.size:
            ax.hist(vals, bins=30, color=(g, g, g), edgecolor="none", alpha=0.85)
            med = float(np.nanmedian(vals))
            yl = ax.get_ylim()
            ax.plot([med, med], yl, color="k", linewidth=1)
            ax.set_ylim(yl)
        if x_limits is not None:
            ax.set_xlim(float(x_limits[0]), float(x_limits[1]))
        ax.set_ylabel("Count")
        ax.set_title(f"{name}", loc="left", fontsize=10, fontweight="normal")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(direction="out")

    for i in range(n_struct, len(flat_axes)):
        flat_axes[i].axis("off")

    for c in range(ncols):
        axes[-1, c].set_xlabel("NSI (R^2)")
    fig.tight_layout(h_pad=0.8, w_pad=0.9)
    return fig


def _finite_x_limits(vals: np.ndarray) -> Optional[np.ndarray]:
    x = np.asarray(vals, dtype=float).ravel()
    x = x[np.isfinite(x)]
    if x.size == 0:
        return None
    lo = float(np.min(x))
    hi = float(np.max(x))
    if hi <= lo:
        hi = lo + 1e-6
    pad = 0.02 * (hi - lo)
    return np.array([lo - pad, hi + pad], dtype=float)


def _plot_hist_gray(vals: np.ndarray, ttl: str):
    vals = np.asarray(vals)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return
    fig = plt.figure(figsize=(3.2, 2.2), facecolor="white")
    plt.hist(vals, bins=40, color=(0.75, 0.75, 0.75), edgecolor="none")
    m = np.median(vals)
    yl = plt.ylim()
    plt.plot([m, m], yl, "k-", linewidth=1)
    plt.title(ttl, fontweight="normal")
    plt.ylabel("Count")
    plt.gca().tick_params(direction="out")
    plt.box(False)
    return fig


def _plot_power_spectra(freq: np.ndarray, power: np.ndarray):
    freq = np.asarray(freq).reshape(-1)
    power = np.asarray(power)
    k, nt = power.shape
    smooth_win = 5

    def smooth_vec(y: np.ndarray, win: int = 5) -> np.ndarray:
        y = y.reshape(-1)
        if win <= 1 or y.size <= win:
            return y
        k = np.ones(win) / win
        return np.convolve(y, k, mode="same")

    power_sm = np.zeros_like(power)
    for j in range(nt):
        power_sm[:, j] = smooth_vec(power[:, j], smooth_win)
    mean_power_sm = np.nanmean(power_sm, axis=1)

    fig = plt.figure(figsize=(3.6, 2.6), facecolor="white")
    for j in range(nt):
        plt.loglog(freq, power_sm[:, j], color=(0.85, 0.85, 0.85), linewidth=0.5)
    plt.loglog(freq, mean_power_sm, color="k", linewidth=2)

    vals = power_sm.ravel()
    vals = vals[(vals > 0) & np.isfinite(vals)]
    if vals.size:
        logvals = np.log10(vals)
        plt.ylim([10 ** np.percentile(logvals, 1), 10 ** np.percentile(logvals, 99)])

    plt.xlabel("Graph frequency (Laplacian eigenvalue)")
    plt.ylabel("Power")
    plt.title("Spatial power spectra")
    return fig


def _plot_nsi_usability_curve_from_model(mdl: Dict[str, Any], point_nsi: float, point_p: float):
    xgrid = np.asarray(mdl["grid"]["x"]).reshape(-1)
    p_hat = np.asarray(mdl["grid"]["p"]).reshape(-1)
    ci_lo = np.asarray(mdl["grid"]["ciLo"]).reshape(-1)
    ci_hi = np.asarray(mdl["grid"]["ciHi"]).reshape(-1)

    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    ax.set_xlabel("NSI")
    ax.set_ylabel("P(PFM-usable)")
    ax.set_ylim(0, 1)

    xl = (xgrid.min(), xgrid.max())
    pad = 0.03 * (xl[1] - xl[0])
    ax.set_xlim(xl[0] - pad, xl[1] + pad)

    # soft traffic-light gradient (red -> yellow -> green)
    xL = ax.get_xlim()
    y0, y1 = 0.0, 1.0
    h = 300
    grad = np.linspace(0.0, 1.0, h).reshape(h, 1)
    # custom gradient: red -> yellow -> green
    red = np.array([0.85, 0.30, 0.30])
    yellow = np.array([0.95, 0.85, 0.30])
    green = np.array([0.35, 0.75, 0.45])
    mid = 0.55
    grad_rgb = np.zeros((h, 1, 3))
    for i, t in enumerate(np.linspace(0.0, 1.0, h)):
        if t <= mid:
            a = t / mid
            col = (1 - a) * red + a * yellow
        else:
            a = (t - mid) / (1 - mid)
            col = (1 - a) * yellow + a * green
        grad_rgb[i, 0, :] = col
    ax.imshow(grad_rgb, aspect="auto", extent=[xL[0], xL[1], y0, y1], origin="lower", alpha=0.18)

    # subtle band overlays for five decision ranges
    bands = [
        (0.0, 0.2, (0.65, 0.15, 0.15)),  # dark red
        (0.2, 0.4, (0.85, 0.35, 0.35)),  # light red
        (0.4, 0.6, (0.95, 0.85, 0.30)),  # yellow
        (0.6, 0.8, (0.70, 0.85, 0.45)),  # light green
        (0.8, 1.0, (0.35, 0.75, 0.45)),  # green
    ]
    for ylo, yhi, col in bands:
        ax.fill_between([xL[0], xL[1]], [ylo, ylo], [yhi, yhi], color=col, alpha=0.08)

    ax.fill_between(xgrid, ci_lo, ci_hi, color=(0.8, 0.8, 0.8), alpha=0.35)
    ax.plot(xgrid, p_hat, "k-", linewidth=1.8)
    ax.scatter([point_nsi], [point_p], s=45, c="k")

    j = _expert_judgement_j()
    ax.axvline(j["min"], color=(0.55, 0.55, 0.55), linestyle="-", linewidth=1.0, alpha=0.6)
    ax.axvline(j["max"], color=(0.55, 0.55, 0.55), linestyle="-", linewidth=1.0, alpha=0.6)
    ax.axvline(j["mean"], color="k", linestyle="-", linewidth=1.8, alpha=0.7)

    ax.tick_params(direction="out")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return fig
