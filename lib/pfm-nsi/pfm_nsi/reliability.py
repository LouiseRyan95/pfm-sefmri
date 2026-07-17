import math
import json
import gzip
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import scipy.io as sio
from scipy.stats import t as tdist
try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None

try:
    from scipy.io.matlab.mio5_params import MatlabOpaque
except Exception:  # pragma: no cover
    MatlabOpaque = None


def _is_matlab_opaque(x: Any) -> bool:
    if MatlabOpaque is None:
        return False
    return isinstance(x, MatlabOpaque)


def _to_dict(obj: Any) -> Any:
    """Recursively convert scipy.io MATLAB structs to dicts/lists."""
    if hasattr(obj, "_fieldnames"):
        return {name: _to_dict(getattr(obj, name)) for name in obj._fieldnames}
    if isinstance(obj, np.ndarray) and obj.dtype == object:
        return [_to_dict(x) for x in obj.ravel()]
    if isinstance(obj, np.void) and obj.dtype.names:
        return {name: _to_dict(obj[name]) for name in obj.dtype.names}
    return obj


def load_nsi_reliability_model(path: str) -> Dict[str, Any]:
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    if path.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    m = sio.loadmat(path, squeeze_me=True, struct_as_record=False)
    if "NSI_reliability_model" not in m:
        raise ValueError("NSI_reliability_model not found in .mat")
    return _to_dict(m["NSI_reliability_model"])


def _predict_linear_model(mdl: Dict[str, Any], x: float) -> Tuple[float, float, Tuple[float, float], float]:
    """Predict mean/SE/CI and residual sigma for exported linear model.

    Expects fields: beta, cov, rmse, dfe, and optional form.
    """
    beta = np.asarray(mdl["beta"]).reshape(-1)
    cov = np.asarray(mdl["cov"]).astype(float)
    rmse = float(np.asarray(mdl.get("rmse", 0.0)).squeeze())
    dfe = int(np.asarray(mdl.get("dfe", max(1, cov.shape[0]))).squeeze())
    form = str(mdl.get("form", "linear"))

    if form == "linear":
        xvec = np.array([1.0, x], dtype=float)
    elif form == "quadratic":
        xvec = np.array([1.0, x, x ** 2], dtype=float)
    else:
        raise ValueError("Unsupported model form")

    mu = float(xvec @ beta)
    se = float(np.sqrt(xvec @ cov @ xvec.T)) if cov.size else 0.0
    tval = float(tdist.ppf(0.975, dfe)) if dfe > 0 else 1.96
    ci = (mu - tval * se, mu + tval * se)
    return mu, se, ci, rmse


def _predict_glm_prob(mdl: Dict[str, Any], nsi: float) -> float:
    beta = np.asarray(mdl.get("beta", [])).reshape(-1)
    coef_names = mdl.get("coef_names", [])
    if beta.size == 0 or not coef_names:
        raise ValueError("Empty GLM coefficients")

    terms = []
    for name in coef_names:
        if isinstance(name, np.ndarray):
            name = str(name.squeeze())
        if name == "(Intercept)":
            terms.append(1.0)
        elif name.startswith("NSI"):
            if "^" in name:
                try:
                    power = int(name.split("^")[1])
                except Exception:
                    power = 1
            else:
                power = 1
            terms.append(nsi ** power)
        else:
            raise ValueError(f"Unsupported GLM term: {name}")

    xvec = np.asarray(terms, dtype=float)
    eta = float(xvec @ beta)
    # logit link
    p = 1.0 / (1.0 + np.exp(-eta))
    return p


def _format_extrapolation_status(nsi_qc: float, nsi_range: Sequence[float]) -> str:
    lo = float(nsi_range[0])
    hi = float(nsi_range[1])
    if not np.all(np.isfinite(np.asarray([lo, hi], dtype=float))):
        return "EXTRAPOLATED: OUTSIDE TRAINING RANGE"
    if nsi_qc < lo:
        return f"EXTRAPOLATED BELOW TRAINING RANGE [{lo:.3f}, {hi:.3f}]"
    if nsi_qc > hi:
        return f"EXTRAPOLATED ABOVE TRAINING RANGE [{lo:.3f}, {hi:.3f}]"
    return "IN-RANGE"


def conditional_reliability_from_nsi(
    qc_pfm: Dict[str, Any],
    reliability_model: Dict[str, Any],
    nsi_t: Optional[float] = None,
    query_t: Optional[Union[float, Sequence[float]]] = None,
    thresholds: Sequence[float] = (0.6, 0.7, 0.8),
    verbose: bool = True,
    do_plot: bool = True,
    deterministic_ci: bool = True,
    prospective_ci: bool = True,
    nmc: int = 5000,
    save_dir: Optional[str] = None,
    prefix: str = "pfm_nsi",
    dpi: int = 150,
) -> Dict[str, Any]:
    if nsi_t is None:
        nsi_t = 10
    if query_t is None:
        query_t = 60
    t_query = np.atleast_1d(np.asarray(query_t, dtype=float))

    nsi_qc = float(qc_pfm["NSI"]["MedianScore"])

    early_list = np.array([float(e["EARLY_MIN"]) for e in reliability_model["early"]])
    ie = int(np.argmin(np.abs(early_list - nsi_t)))
    early_mdl = reliability_model["early"][ie]

    if verbose:
        print(f"Selected EARLY_MIN model: {int(early_mdl['EARLY_MIN'])} min (requested NSI_T={nsi_t})")

    flags: Dict[str, Any] = {}
    flags["NSI_out_of_range"] = False
    flags["NSI_range"] = [float("nan"), float("nan")]
    flags["in_training_range"] = True
    flags["extrapolation_status"] = "in_training_range"
    flags["extrapolation_note"] = "NSI is within training range for selected EARLY_MIN model."
    if "NSI_range" in early_mdl and np.all(np.isfinite(np.asarray(early_mdl["NSI_range"]).ravel())):
        nsi_range = np.asarray(early_mdl["NSI_range"]).ravel()
        flags["NSI_range"] = [float(nsi_range[0]), float(nsi_range[1])]
        flags["NSI_out_of_range"] = (nsi_qc < nsi_range[0]) or (nsi_qc > nsi_range[1])
        flags["in_training_range"] = not bool(flags["NSI_out_of_range"])
        if flags["NSI_out_of_range"]:
            flags["extrapolation_status"] = "outside_training_range"
            flags["extrapolation_note"] = (
                "Deterministic and probabilistic estimates are extrapolated outside model support "
                "and should not be interpreted as in-range performance."
            )
        if verbose and flags["NSI_out_of_range"]:
            print(
                f"WARNING: NSI={nsi_qc:.3f} outside training range [{nsi_range[0]:.3f}, {nsi_range[1]:.3f}] for EARLY_MIN={int(early_mdl['EARLY_MIN'])}. Extrapolating."
            )
            print("WARNING: Reported reliability estimates are outside-training-range extrapolations, not in-range model performance.")

    backward_mask = t_query < float(early_mdl["EARLY_MIN"])
    flags["backward_query_mask"] = backward_mask
    if verbose and np.any(backward_mask):
        print(
            f"WARNING: {int(np.sum(backward_mask))}/{t_query.size} query times are < EARLY_MIN={int(early_mdl['EARLY_MIN'])} and will be returned as NaN (forward-only)."
        )

    flags["DeterministicCI"] = deterministic_ci
    flags["ProspectiveCI"] = prospective_ci
    flags["Nmc"] = nmc

    # Predict k and Rmax
    k_model = early_mdl["k_model"]
    if _is_matlab_opaque(k_model):
        raise RuntimeError(
            "k_model is a MATLAB object. Export NSI_reliability_model to a Python-friendly format first."
        )

    mu_k, se_k, ci_k, sigma_k = _predict_linear_model(k_model, nsi_qc)
    k_hat = max(mu_k, 1e-8)

    has_rmax = "Rmax_model" in early_mdl and early_mdl["Rmax_model"] is not None
    if has_rmax and not _is_matlab_opaque(early_mdl["Rmax_model"]):
        mu_r, se_r, ci_r, sigma_r = _predict_linear_model(early_mdl["Rmax_model"], nsi_qc)
        rmax_hat = mu_r
    else:
        rmax_hat = float(reliability_model.get("Rmax_global", reliability_model.get("Rmax", np.nan)))
        mu_r = rmax_hat
        se_r = 0.0
        sigma_r = 0.0
        ci_r = (rmax_hat, rmax_hat)

    rmax_hat = min(max(rmax_hat, 0.0), 0.999)

    r_hat = rmax_hat * (1.0 - np.exp(-k_hat * t_query))
    r_hat = np.clip(r_hat, 0.0, 0.999)
    r_hat[backward_mask] = np.nan

    r_ci95 = np.full((t_query.size, 2), np.nan)
    k_ci95 = np.array(ci_k, dtype=float)
    rmax_ci95 = np.array(ci_r, dtype=float)

    if deterministic_ci:
        se_k_eff = math.sqrt(se_k ** 2 + sigma_k ** 2) if prospective_ci else se_k
        se_r_eff = math.sqrt(se_r ** 2 + sigma_r ** 2) if prospective_ci else se_r

        k_samp = mu_k + se_k_eff * np.random.randn(nmc)
        rmax_samp = mu_r + se_r_eff * np.random.randn(nmc)
        k_samp = np.maximum(k_samp, 1e-8)
        rmax_samp = np.clip(rmax_samp, 0.0, 0.999)

        r_samp = rmax_samp[:, None] * (1.0 - np.exp(-k_samp[:, None] * t_query[None, :]))
        r_samp = np.clip(r_samp, 0.0, 0.999)

        r_ci95[:, 0] = np.percentile(r_samp, 2.5, axis=0)
        r_ci95[:, 1] = np.percentile(r_samp, 97.5, axis=0)
        r_ci95[backward_mask, :] = np.nan

    out: Dict[str, Any] = {}
    out["input"] = {
        "NSI": nsi_qc,
        "NSI_time": nsi_t,
        "query_time": t_query,
        "thresholds": list(thresholds),
    }
    out["model"] = {
        "EARLY_MIN_used": float(early_mdl["EARLY_MIN"]),
        "Rmax_global": float(reliability_model.get("Rmax_global", reliability_model.get("Rmax", np.nan))),
        "k_hat": k_hat,
        "Rmax_hat": rmax_hat,
    }
    out["flags"] = flags
    out["extrapolation"] = {
        "status": flags["extrapolation_status"],
        "in_training_range": bool(flags["in_training_range"]),
        "note": flags["extrapolation_note"],
        "nsi_range": flags["NSI_range"],
    }
    out["deterministic"] = {
        "T_QUERY": t_query,
        "k_hat": k_hat,
        "Rmax_hat": rmax_hat,
        "R_hat": r_hat,
        "CI_supported": deterministic_ci,
        "CI_prospective": prospective_ci,
        "k_CI95": k_ci95,
        "Rmax_CI95": rmax_ci95,
        "R_CI95": r_ci95,
        "CI_Nmc": nmc,
        "is_extrapolated": bool(flags["NSI_out_of_range"]),
    }

    # Probabilistic
    out["probabilistic"] = {"supported": True}
    for r0 in thresholds:
        tag = f"R_ge_{r0:.2f}".replace(".", "p")
        out["probabilistic"][tag] = {
            "R_thresh": r0,
            "T_query": t_query,
            "T_QUERY_used": np.full_like(t_query, np.nan),
            "P_hat": np.full_like(t_query, np.nan),
            "P_CI": np.full((t_query.size, 2), np.nan),
        }

    if "query" not in early_mdl or early_mdl["query"] is None:
        out["probabilistic"]["supported"] = False
    else:
        query_list = np.array([float(q["T_QUERY"]) for q in early_mdl["query"]])
        for tt, tq in enumerate(t_query):
            if tq < float(early_mdl["EARLY_MIN"]):
                continue
            it = int(np.argmin(np.abs(query_list - tq)))
            query_mdl = early_mdl["query"][it]
            t_used = float(query_mdl["T_QUERY"])

            if "prob_models" not in query_mdl or query_mdl["prob_models"] is None:
                out["probabilistic"]["supported"] = False
                continue

            for r0 in thresholds:
                tag = f"R_ge_{r0:.2f}".replace(".", "p")
                out["probabilistic"][tag]["T_QUERY_used"][tt] = t_used

                pm_list = [pm for pm in query_mdl["prob_models"] if float(pm["R_thresh"]) == float(r0)]
                if not pm_list:
                    continue
                pm = pm_list[0]
                grid = pm["grid"]
                x = np.asarray(grid["NSI"]).reshape(-1)
                p_med = np.asarray(grid["P_med"]).reshape(-1)
                p_lo = np.asarray(grid["P_lo"]).reshape(-1)
                p_hi = np.asarray(grid["P_hi"]).reshape(-1)

                # If mdl is MATLAB object, approximate with grid interpolation
                if _is_matlab_opaque(pm["mdl"]):
                    p_hat = float(np.interp(nsi_qc, x, p_med))
                else:
                    mdl = pm["mdl"]
                    if isinstance(mdl, dict) and "beta" in mdl:
                        try:
                            p_hat = float(_predict_glm_prob(mdl, nsi_qc))
                        except Exception:
                            p_hat = float(np.interp(nsi_qc, x, p_med))
                    else:
                        p_hat = float(np.interp(nsi_qc, x, p_med))

                out["probabilistic"][tag]["P_hat"][tt] = p_hat
                out["probabilistic"][tag]["P_CI"][tt, :] = [
                    float(np.interp(nsi_qc, x, p_lo)),
                    float(np.interp(nsi_qc, x, p_hi)),
                ]

    tq_plot = float(t_query[-1])
    plot_summary: Dict[str, Any] = {
        "query_time_plotted": tq_plot,
        "title": "",
        "status_text": "",
        "deterministic_point": {
            "x": float(nsi_qc),
            "y": float("nan"),
            "query_time": tq_plot,
            "label": f"Deterministic R^2 at {tq_plot:.0f} min",
        },
        "threshold_probability_points": [],
        "legacy_threshold_probability_points": [],
    }

    tt_plot = int(np.argmin(np.abs(t_query - tq_plot)))
    rhat_plot = float(out["deterministic"]["R_hat"][tt_plot])
    plot_summary["deterministic_point"]["y"] = rhat_plot

    if "query" in early_mdl and early_mdl["query"] is not None:
        query_list = np.array([float(q["T_QUERY"]) for q in early_mdl["query"]])
        it = int(np.argmin(np.abs(query_list - tq_plot)))
        query_mdl = early_mdl["query"][it]

        if "prob_models" in query_mdl and query_mdl["prob_models"] is not None:
            for r0 in thresholds:
                pm_list = [pm for pm in query_mdl["prob_models"] if float(pm["R_thresh"]) == float(r0)]
                if not pm_list:
                    continue
                pm = pm_list[0]
                g = pm["grid"]
                x = np.asarray(g["NSI"]).reshape(-1)
                p_med = np.asarray(g["P_med"]).reshape(-1)
                legacy_y = float(np.interp(nsi_qc, x, p_med))
                tag = f"R_ge_{r0:.2f}".replace(".", "p")
                p_hat_curve = float(out["probabilistic"][tag]["P_hat"][tt_plot])
                plot_summary["threshold_probability_points"].append(
                    {
                        "threshold": float(r0),
                        "x": float(nsi_qc),
                        "y": p_hat_curve,
                        "query_time": float(query_mdl["T_QUERY"]),
                        "label": f"P(R^2 >= {r0:.2f} at {float(query_mdl['T_QUERY']):.0f} min)",
                    }
                )
                plot_summary["legacy_threshold_probability_points"].append(
                    {
                        "threshold": float(r0),
                        "x": float(nsi_qc),
                        "y": legacy_y,
                        "query_time": float(query_mdl["T_QUERY"]),
                        "label": f"Legacy plotted point on P(R^2 >= {r0:.2f}) curve",
                    }
                )

    status_txt = _format_extrapolation_status(nsi_qc, flags["NSI_range"]) if flags["NSI_out_of_range"] else ""
    plot_summary["status_text"] = status_txt
    plot_summary["title"] = f"NSI={nsi_qc:.3f} | Deterministic R^2({tq_plot:.0f})={rhat_plot:.3f}"
    out["plot"] = plot_summary

    if do_plot:
        if plt is None:
            raise RuntimeError("matplotlib is required for plotting.")
        if verbose and t_query.size > 1:
            print(f"Plotting probabilistic curves for QueryT={tq_plot} (last element of QueryT vector).")

        if "query" in early_mdl and early_mdl["query"] is not None:
            if "prob_models" in query_mdl and query_mdl["prob_models"] is not None:
                fig_w, fig_h, fs = 5.6, 3.1, 10
                cols = np.array([[0.75, 0.75, 0.75], [0.50, 0.50, 0.50], [0.20, 0.20, 0.20]])
                line_styles = ["-", "--", "-."]
                red = (0.70, 0.0, 0.0)

                fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor="white", constrained_layout=True)
                ax.axvline(nsi_qc, color=(0.75, 0.0, 0.0), linewidth=1.4)

                for i, r0 in enumerate(list(thresholds)[:3]):
                    pm_list = [pm for pm in query_mdl["prob_models"] if float(pm["R_thresh"]) == float(r0)]
                    if not pm_list:
                        continue
                    pm = pm_list[0]
                    g = pm["grid"]
                    x = np.asarray(g["NSI"]).reshape(-1)
                    p_med = np.asarray(g["P_med"]).reshape(-1)
                    p_lo = np.asarray(g["P_lo"]).reshape(-1)
                    p_hi = np.asarray(g["P_hi"]).reshape(-1)

                    ax.fill_between(x, p_lo, p_hi, color=cols[i], alpha=0.10)
                    ax.plot(
                        x,
                        p_med,
                        color=cols[i] * 0.6,
                        linestyle=line_styles[i],
                        linewidth=2.2,
                        label=f"P(R^2 >= {r0:.2f})",
                    )

                ax.set_ylim(0, 1)
                ax.tick_params(direction="out", labelsize=fs - 1)
                ax.set_xlabel(f"NSI ({int(out['model']['EARLY_MIN_used'])} min)")
                ax.set_ylabel(f"P(R^2 >= threshold at {int(query_mdl['T_QUERY'])} min)")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)

                ax_det = ax.twinx()
                ax_det.set_ylim(0, 1)
                ax_det.spines["top"].set_visible(False)
                ax_det.spines["left"].set_visible(False)
                ax_det.spines["right"].set_color(red)
                ax_det.spines["right"].set_linewidth(0.9)
                ax_det.tick_params(direction="out", colors=red, labelsize=fs - 1, pad=2, width=0.9, length=3.5)
                ax_det.set_ylabel(
                    f"Deterministic R^2 at {int(query_mdl['T_QUERY'])} min",
                    color=red,
                    fontsize=fs,
                    labelpad=8,
                )
                ax_det.scatter(
                    nsi_qc,
                    rhat_plot,
                    s=38,
                    marker="D",
                    c=[red],
                    edgecolors="w",
                    linewidths=0.8,
                    zorder=5,
                    label=f"Deterministic R^2({tq_plot:.0f})",
                )

                if flags["NSI_out_of_range"]:
                    warn_txt = status_txt
                    ax.text(
                        0.02,
                        0.97,
                        warn_txt,
                        transform=ax.transAxes,
                        ha="left",
                        va="top",
                        fontsize=fs - 1,
                        color=red,
                        bbox={"boxstyle": "round,pad=0.22", "fc": (1.0, 0.96, 0.96), "ec": (0.82, 0.82, 0.82)},
                    )

                handles, labels = ax.get_legend_handles_labels()
                handles_det, labels_det = ax_det.get_legend_handles_labels()
                ax.legend(handles + handles_det, labels + labels_det, loc="lower right", frameon=False, fontsize=8)

                ax.set_title(plot_summary["title"], fontweight="normal", fontsize=fs + 0.5, pad=6)
                if save_dir:
                    fig.savefig(f"{save_dir}/{prefix}_reliability_prob.png", dpi=dpi, bbox_inches="tight")

    return out
