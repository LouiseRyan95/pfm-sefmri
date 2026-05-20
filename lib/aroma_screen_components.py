#!/usr/bin/env python3
"""Screen ICA-AROMA components with cortical-surface NSI.

This is analogous to the ME-ICA NSI-based reclassification logic, but for
single-echo ICA-AROMA output. The key behavior is to *prioritize* removing
clearly-bad components (AROMA-classified motion components), and then
optionally remove a *subset* of low-NSI components while avoiding wasting
degrees of freedom on very-low-variance components.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from meica_reclassify_components import (
    _compute_nsi_from_cifti,
    _compute_subcortical_ratio_from_cifti,
)


def _z(a: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    a = np.where(np.isfinite(a), a, np.nan)
    mu = float(np.nanmean(a)) if np.any(np.isfinite(a)) else 0.0
    sd = float(np.nanstd(a)) if np.any(np.isfinite(a)) else 0.0
    if not np.isfinite(sd) or sd <= 0:
        return np.zeros_like(a, dtype=float)
    return (np.nan_to_num(a, nan=mu) - mu) / sd


def _load_aroma_overview(aroma_dir: Path, n_components: int) -> pd.DataFrame:
    """Load AROMA per-component features.

    Preference order:
    - classification_overview.txt (includes motion/noise and feature columns)
    - feature_scores.txt (features only; ordering assumed to be IC1..ICN)
    """
    p = aroma_dir / "classification_overview.txt"
    if not p.is_file():
        feat = aroma_dir / "feature_scores.txt"
        if not feat.is_file():
            return pd.DataFrame()
        arr = np.loadtxt(feat, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        if arr.shape[0] != n_components or arr.shape[1] < 4:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "component_num_1based": np.arange(1, n_components + 1, dtype=int),
                "maxRPcorr": arr[:, 0],
                "edgeFract": arr[:, 1],
                "HFC": arr[:, 2],
                "CSFFract": arr[:, 3],
            }
        )
    df = pd.read_csv(p, sep="\t")
    rename = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        if cl in {"ic", "component", "component_id", "component id"}:
            rename[c] = "component_num_1based"
        elif "motion/noise" in cl or cl in {"motion", "motion_noise"}:
            rename[c] = "aroma_motion_overview"
        elif "maximum rp correlation" in cl or "max rp" in cl or "maxrpcorr" in cl:
            rename[c] = "maxRPcorr"
        elif "edge" in cl and "fraction" in cl:
            rename[c] = "edgeFract"
        elif "high-frequency" in cl or cl in {"hfc", "highfreq"}:
            rename[c] = "HFC"
        elif "csf" in cl and "fraction" in cl:
            rename[c] = "CSFFract"
    if rename:
        df = df.rename(columns=rename)
    if "component_num_1based" not in df.columns:
        return pd.DataFrame()
    df["component_num_1based"] = pd.to_numeric(df["component_num_1based"], errors="coerce").astype("Int64")
    for c in ("maxRPcorr", "edgeFract", "HFC", "CSFFract"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "aroma_motion_overview" in df.columns:
        # Often emitted as True/False strings.
        df["aroma_motion_overview"] = df["aroma_motion_overview"].astype(str).str.strip().str.lower().map(
            {"true": True, "false": False, "1": True, "0": False}
        )
    return df


def _load_mix_variance_proxy(aroma_dir: Path, n_components: int) -> tuple[np.ndarray, np.ndarray]:
    """Variance proxy from the melodic mixing matrix (timecourses).

    This is not a literal '% variance explained' in the data, but it is a
    practical proxy for component amplitude/importance, used only to avoid
    spending DOF on extremely low-variance components.
    """
    mix_path = aroma_dir / "melodic.ica" / "melodic_mix"
    if not mix_path.is_file():
        v = np.ones(n_components, dtype=float)
        return v, v / float(np.sum(v))
    mix = np.loadtxt(mix_path, dtype=float)
    if mix.ndim == 1:
        # Single timepoint edge-case.
        mix = mix.reshape(1, -1)
    if mix.shape[1] != n_components:
        # Defensive fallback if dimensionality disagrees.
        v = np.ones(n_components, dtype=float)
        return v, v / float(np.sum(v))
    v = np.var(mix, axis=0, ddof=1)
    v = np.where(np.isfinite(v), v, 0.0)
    s = float(np.sum(v))
    if s <= 0:
        return v, np.zeros_like(v)
    return v, v / s


def _try_make_nsi_aroma_plot(
    out: pd.DataFrame,
    out_png: Path,
    *,
    nsi_threshold: float,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    if "NSI" not in out.columns or "aroma_artifact_score" not in out.columns:
        return

    x = out["aroma_artifact_score"].to_numpy(dtype=float)
    y = out["NSI"].to_numpy(dtype=float)
    keep_init = out["keep_init"].to_numpy(dtype=bool)
    aroma_motion_flag = out["aroma_motion_flag"].to_numpy(dtype=bool)
    aroma_motion_removed = out["aroma_motion_removed"].to_numpy(dtype=bool)
    kill_candidate = out.get("kill_candidate_nsi", pd.Series(False, index=out.index)).to_numpy(dtype=bool)
    killed = out.get("killed_by_nsi", pd.Series(False, index=out.index)).to_numpy(dtype=bool)

    plt.figure(figsize=(7, 4), dpi=150)
    if np.any(aroma_motion_removed):
        plt.scatter(x[aroma_motion_removed], y[aroma_motion_removed], s=14, c="tab:red", alpha=0.75, label="removed (AROMA motion)")
    if np.any(aroma_motion_flag & ~aroma_motion_removed):
        plt.scatter(
            x[aroma_motion_flag & ~aroma_motion_removed],
            y[aroma_motion_flag & ~aroma_motion_removed],
            s=24,
            facecolors="none",
            edgecolors="tab:orange",
            linewidths=0.9,
            alpha=0.9,
            label="flagged motion (kept)",
        )
    plt.scatter(x[keep_init & ~kill_candidate], y[keep_init & ~kill_candidate], s=12, c="tab:green", alpha=0.7, label="keep")
    if np.any(kill_candidate & ~killed):
        plt.scatter(
            x[kill_candidate & ~killed],
            y[kill_candidate & ~killed],
            s=20,
            facecolors="none",
            edgecolors="tab:blue",
            linewidths=0.8,
            alpha=0.8,
            label="low NSI (not removed)",
        )
    if np.any(killed):
        plt.scatter(x[killed], y[killed], s=44, c="cyan", edgecolors="k", linewidths=0.4, label="removed by NSI")

    plt.axhline(float(nsi_threshold), color="k", linestyle="--", linewidth=1.0, label="NSI threshold")
    plt.xlabel("AROMA total artifact score (z-sum)")
    plt.ylabel("NSI")
    plt.title("NSI vs AROMA artifact score")
    plt.grid(alpha=0.25)
    plt.legend(loc="best", frameon=False)
    plt.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png)
    plt.close()


def parse_component_ids_1based(path: Path) -> list[int]:
    if not path.is_file():
        return []
    text = path.read_text().strip()
    if not text:
        return []
    tokens = [tok.strip() for tok in text.replace(",", " ").split()]
    out: list[int] = []
    for tok in tokens:
        if tok:
            out.append(int(tok))
    return sorted(set(out))


def write_ids(path: Path, ids: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(str(i) for i in ids)
    path.write_text(text + ("\n" if text else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description="Screen ICA-AROMA components with NSI.")
    ap.add_argument("--aroma-dir", required=True, help="ICA-AROMA output directory")
    ap.add_argument("--betas-cifti", required=True, help="CIFTI-mapped melodic component maps")
    ap.add_argument("--priors-mat", required=True, help="Priors.mat for NSI")
    ap.add_argument(
        "--nsi-threshold",
        type=float,
        default=0.05,
        help="Define low-NSI kill candidates below this threshold",
    )
    ap.add_argument("--kill-priority-enable", type=int, default=1, help="Prioritize kills to avoid low-variance DOF loss (0|1)")
    ap.add_argument("--kill-priority-w-nsi", type=float, default=0.60, help="Weight for low NSI in kill prioritization score")
    ap.add_argument("--kill-priority-w-var", type=float, default=0.25, help="Weight for higher variance proxy in kill prioritization score")
    ap.add_argument("--kill-priority-w-aroma", type=float, default=0.15, help="Weight for higher AROMA artifact score in kill prioritization score")
    ap.add_argument("--kill-var-floor-quantile", type=float, default=0.60, help="Variance proxy floor quantile within kill candidates")
    ap.add_argument("--kill-cumvar-cap", type=float, default=0.95, help="Cumulative-variance cap within prioritized kill pool")
    ap.add_argument("--kill-max-frac", type=float, default=1.00, help="Optional cap on number of NSI-based kills (fraction of non-motion comps)")
    ap.add_argument("--kill-max-count", type=int, default=0, help="Optional cap on number of NSI-based kills (0 disables)")
    ap.add_argument("--motion-priority-enable", type=int, default=0, help="Optionally remove only a prioritized subset of AROMA motion ICs (0|1)")
    ap.add_argument("--motion-remove-frac", type=float, default=1.00, help="Fraction of AROMA motion ICs to remove when prioritizing")
    ap.add_argument("--motion-var-floor-quantile", type=float, default=0.60, help="Variance proxy floor quantile within AROMA motion ICs")
    ap.add_argument("--motion-cumvar-cap", type=float, default=1.00, help="Cumulative-variance cap within prioritized AROMA motion pool (1.0 disables)")
    ap.add_argument("--motion-priority-w-var", type=float, default=0.50, help="Weight for higher variance proxy in motion prioritization score")
    ap.add_argument("--motion-priority-w-aroma", type=float, default=0.50, help="Weight for higher AROMA artifact score in motion prioritization score")
    ap.add_argument("--make-plot", type=int, default=1, help="Write NSI-vs-AROMA plot (0|1)")
    ap.add_argument("--out-dir", required=True, help="Output directory for decisions")
    args = ap.parse_args()

    aroma_dir = Path(args.aroma_dir).resolve()
    betas_cifti = Path(args.betas_cifti).resolve()
    priors_mat = Path(args.priors_mat).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    comp_nii = aroma_dir / "melodic.ica" / "melodic_IC.nii.gz"
    if not comp_nii.is_file():
        raise FileNotFoundError(f"Missing melodic component volume: {comp_nii}")

    import nibabel as nib

    n_components = int(nib.load(str(comp_nii)).shape[3])
    motion_ids_1b = parse_component_ids_1based(aroma_dir / "classified_motion_ICs.txt")
    motion_ids_0b = sorted({i - 1 for i in motion_ids_1b if i >= 1})

    nsi = _compute_nsi_from_cifti(betas_cifti, priors_mat, n_components)
    subcort_ratio = _compute_subcortical_ratio_from_cifti(betas_cifti, n_components)
    mix_var, mix_var_norm = _load_mix_variance_proxy(aroma_dir, n_components)

    aroma_overview = _load_aroma_overview(aroma_dir, n_components)
    if not aroma_overview.empty:
        aroma_overview = aroma_overview.dropna(subset=["component_num_1based"])
        aroma_overview = aroma_overview.set_index("component_num_1based", drop=False)

    rows = []
    for cid in range(n_components):
        component_num = cid + 1
        aroma_motion_flag = component_num in motion_ids_1b
        initial_keep = not aroma_motion_flag  # may be refined later if motion-prioritization is enabled
        low_nsi_candidate = initial_keep and float(nsi[cid]) < float(args.nsi_threshold)
        accepted_final = initial_keep and not low_nsi_candidate  # refined later
        overview_row = None
        if not aroma_overview.empty and component_num in aroma_overview.index:
            overview_row = aroma_overview.loc[component_num]
        rows.append(
            {
                "component_id": cid,
                "component_num_1based": component_num,
                "classification_init": "rejected" if aroma_motion_flag else "accepted",
                "keep_init": initial_keep,
                "aroma_motion_flag": aroma_motion_flag,
                "aroma_motion_removed": aroma_motion_flag,  # may be refined below
                "NSI": float(nsi[cid]),
                "subcort_ratio": float(subcort_ratio[cid]) if np.isfinite(subcort_ratio[cid]) else np.nan,
                "mix_var": float(mix_var[cid]) if cid < len(mix_var) else np.nan,
                "mix_var_norm": float(mix_var_norm[cid]) if cid < len(mix_var_norm) else np.nan,
                "maxRPcorr": float(overview_row["maxRPcorr"]) if overview_row is not None and "maxRPcorr" in overview_row else np.nan,
                "edgeFract": float(overview_row["edgeFract"]) if overview_row is not None and "edgeFract" in overview_row else np.nan,
                "HFC": float(overview_row["HFC"]) if overview_row is not None and "HFC" in overview_row else np.nan,
                "CSFFract": float(overview_row["CSFFract"]) if overview_row is not None and "CSFFract" in overview_row else np.nan,
                "kill_candidate_nsi": low_nsi_candidate,
                "killed_by_nsi": False,  # filled below
                "accepted_final": accepted_final,  # filled below
            }
        )

    out = pd.DataFrame(rows)

    # Aggregate AROMA artifact score = z(maxRPcorr)+z(edgeFract)+z(HFC)+z(CSFFract).
    feat_cols = [c for c in ("maxRPcorr", "edgeFract", "HFC", "CSFFract") if c in out.columns]
    if feat_cols:
        zsum = np.zeros(len(out), dtype=float)
        for c in feat_cols:
            zsum += _z(out[c].to_numpy(dtype=float))
        out["aroma_artifact_score"] = zsum
    else:
        out["aroma_artifact_score"] = np.nan

    # Optional motion-component prioritization: by default remove all AROMA motion ICs,
    # but allow keeping the lowest-variance tail (or capping to a fraction).
    aroma_motion_flag = out["aroma_motion_flag"].to_numpy(dtype=bool)
    motion_removed = aroma_motion_flag.copy()
    if bool(int(args.motion_priority_enable)) and np.any(aroma_motion_flag):
        idx = np.where(aroma_motion_flag)[0]
        v = out["mix_var_norm"].to_numpy(dtype=float)
        v = np.where(np.isfinite(v), v, 0.0)
        motion_v = v[idx]
        floor = float(np.quantile(motion_v, float(args.motion_var_floor_quantile))) if len(motion_v) else 0.0
        pool_mask = motion_v >= floor
        pool_idx = idx[pool_mask]
        if len(pool_idx) == 0:
            pool_idx = idx

        var_pool = v[pool_idx]
        aroma_pool = out.loc[pool_idx, "aroma_artifact_score"].to_numpy(dtype=float)
        aroma_pool = np.where(np.isfinite(aroma_pool), aroma_pool, 0.0)
        score = (
            float(args.motion_priority_w_var) * _z(var_pool)
            + float(args.motion_priority_w_aroma) * _z(aroma_pool)
        )
        order = np.argsort(-score)
        ranked_idx = pool_idx[order]
        ranked_var = var_pool[order]

        # Remove a fraction of motion components (count cap).
        remove_frac = float(args.motion_remove_frac)
        if not np.isfinite(remove_frac) or remove_frac < 0:
            remove_frac = 1.0
        remove_frac = min(remove_frac, 1.0)
        n_remove = int(np.ceil(remove_frac * len(idx)))
        n_remove = min(n_remove, len(ranked_idx))

        selected = ranked_idx[:n_remove]

        # Optional cumulative-variance cap within the selected ranking.
        cumvar_cap = float(args.motion_cumvar_cap)
        if np.isfinite(cumvar_cap) and cumvar_cap < 1.0 and len(selected) > 0:
            total_var = float(np.sum(ranked_var))
            if total_var > 0:
                target = cumvar_cap * total_var
                cs = np.cumsum(ranked_var[:n_remove])
                n_sel = int(np.sum(cs <= target))
                if n_sel < n_remove:
                    n_sel += 1
                selected = ranked_idx[:n_sel]

        motion_removed[:] = False
        motion_removed[selected] = True

    out["aroma_motion_removed"] = motion_removed
    out["keep_init"] = ~motion_removed
    out["kill_candidate_nsi"] = out["keep_init"] & (out["NSI"] < float(args.nsi_threshold))

    # Prioritized NSI-based kills: choose a subset of low-NSI candidates, prioritizing
    # higher-variance components (and optionally higher AROMA artifact score).
    keep_init = out["keep_init"].to_numpy(dtype=bool)
    candidate = out["kill_candidate_nsi"].to_numpy(dtype=bool)
    killed = np.zeros(len(out), dtype=bool)
    if bool(int(args.kill_priority_enable)) and np.any(candidate):
        idx = np.where(candidate)[0]
        v = out["mix_var_norm"].to_numpy(dtype=float)
        v = np.where(np.isfinite(v), v, 0.0)

        cand_v = v[idx]
        floor = float(np.quantile(cand_v, float(args.kill_var_floor_quantile))) if len(cand_v) else 0.0
        pool_mask = cand_v >= floor
        pool_idx = idx[pool_mask]
        if len(pool_idx) == 0:
            pool_idx = idx

        nsi_pool = out.loc[pool_idx, "NSI"].to_numpy(dtype=float)
        var_pool = v[pool_idx]
        aroma_pool = out.loc[pool_idx, "aroma_artifact_score"].to_numpy(dtype=float)
        aroma_pool = np.where(np.isfinite(aroma_pool), aroma_pool, 0.0)

        score = (
            float(args.kill_priority_w_nsi) * _z(-nsi_pool)
            + float(args.kill_priority_w_var) * _z(var_pool)
            + float(args.kill_priority_w_aroma) * _z(aroma_pool)
        )
        order = np.argsort(-score)
        ranked_idx = pool_idx[order]
        ranked_var = var_pool[order]

        total_var = float(np.sum(ranked_var))
        if total_var <= 0:
            selected = ranked_idx
        else:
            target = float(args.kill_cumvar_cap) * total_var
            cs = np.cumsum(ranked_var)
            n_sel = int(np.sum(cs <= target))
            if n_sel < len(ranked_idx):
                n_sel += 1
            selected = ranked_idx[:n_sel]

        # Optional caps on kill count.
        max_count = int(args.kill_max_count)
        if max_count > 0:
            selected = selected[:max_count]
        max_frac = float(args.kill_max_frac)
        if np.isfinite(max_frac) and max_frac < 1.0:
            max_kill = int(np.floor(max_frac * int(np.sum(keep_init))))
            if max_kill <= 0:
                selected = np.asarray([], dtype=int)
            else:
                selected = selected[:max_kill]

        killed[selected] = True
    else:
        killed = candidate.copy()

    out["killed_by_nsi"] = killed
    out["accepted_final"] = keep_init & ~killed

    accepted_ids_0b = out.loc[out["accepted_final"], "component_id"].astype(int).tolist()
    rejected_ids_0b = out.loc[~out["accepted_final"], "component_id"].astype(int).tolist()
    accepted_ids_1b = out.loc[out["accepted_final"], "component_num_1based"].astype(int).tolist()
    rejected_ids_1b = out.loc[~out["accepted_final"], "component_num_1based"].astype(int).tolist()

    write_ids(out_dir / "AcceptedComponents.txt", accepted_ids_0b)
    write_ids(out_dir / "RejectedComponents.txt", rejected_ids_0b)
    write_ids(out_dir / "AcceptedComponents_1based.txt", accepted_ids_1b)
    write_ids(out_dir / "RejectedComponents_1based.txt", rejected_ids_1b)
    out.to_csv(out_dir / "ComponentDecisions.tsv", sep="\t", index=False)

    summary = {
        "n_components": int(n_components),
        "aroma_motion_flag_count": int(np.sum(out["aroma_motion_flag"].to_numpy(dtype=bool))),
        "aroma_motion_removed_count": int(np.sum(out["aroma_motion_removed"].to_numpy(dtype=bool))),
        "nsi_kill_count": int(np.sum(out["killed_by_nsi"].to_numpy(dtype=bool))),
        "accepted_count": int(len(accepted_ids_0b)),
        "rejected_count": int(len(rejected_ids_0b)),
        "nsi_threshold": float(args.nsi_threshold),
        "kill_priority_enable": bool(int(args.kill_priority_enable)),
        "kill_var_floor_quantile": float(args.kill_var_floor_quantile),
        "kill_cumvar_cap": float(args.kill_cumvar_cap),
        "kill_max_frac": float(args.kill_max_frac),
        "kill_max_count": int(args.kill_max_count),
        "motion_priority_enable": bool(int(args.motion_priority_enable)),
        "motion_remove_frac": float(args.motion_remove_frac),
        "motion_var_floor_quantile": float(args.motion_var_floor_quantile),
        "motion_cumvar_cap": float(args.motion_cumvar_cap),
    }
    (out_dir / "ClassificationSummary.json").write_text(json.dumps(summary, indent=2))
    (out_dir / "ClassificationSummary.txt").write_text(
        "\n".join(f"{k}: {v}" for k, v in summary.items()) + "\n"
    )

    if bool(int(args.make_plot)):
        _try_make_nsi_aroma_plot(
            out,
            out_dir / "NSI_vs_AROMAArtifact.png",
            nsi_threshold=float(args.nsi_threshold),
        )
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
