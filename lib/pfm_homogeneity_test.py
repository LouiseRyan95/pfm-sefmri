#!/usr/bin/env python3
"""PFM community homogeneity diagnostics with optional spin/null rotations."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import nibabel as nib
import numpy as np


def parse_num_list(expr: str) -> List[float]:
    expr = str(expr).strip()
    if not expr:
        return []
    if ":" in expr and "," not in expr:
        start, step, stop = [float(x.strip()) for x in expr.split(":")]
        out = []
        x = start
        eps = abs(step) * 1e-9
        if step > 0:
            while x <= stop + eps:
                out.append(x)
                x += step
        else:
            while x >= stop - eps:
                out.append(x)
                x += step
        return out
    return [float(x.strip()) for x in expr.split(",") if x.strip()]


def cortical_grayordinates(axis) -> np.ndarray:
    idx = []
    for name, slc, _ in axis.iter_structures():
        if name in ("CIFTI_STRUCTURE_CORTEX_LEFT", "CIFTI_STRUCTURE_CORTEX_RIGHT"):
            stop = slc.stop if slc.stop is not None else axis.size
            idx.extend(range(slc.start, stop))
    return np.asarray(idx, dtype=np.int64)


def zscore_rows(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    x = x - np.nanmean(x, axis=1, keepdims=True)
    sd = np.nanstd(x, axis=1, keepdims=True)
    sd = np.where(np.isfinite(sd) & (sd > 1e-8), sd, 1.0)
    return np.nan_to_num(x / sd)


def pc1_variance_percent(mat: np.ndarray) -> float:
    mat = np.asarray(mat, dtype=np.float64)
    if mat.shape[0] < 2 or mat.shape[1] < 2:
        return np.nan
    mat = mat - np.nanmean(mat, axis=0, keepdims=True)
    try:
        s = np.linalg.svd(np.nan_to_num(mat), compute_uv=False)
    except np.linalg.LinAlgError:
        return np.nan
    var = s * s
    den = float(var.sum())
    if den <= 0:
        return np.nan
    return float(var[0] / den * 100.0)


def homogeneity_for_labels(
    x_nodes_time: np.ndarray,
    labels: np.ndarray,
    min_size: int,
    max_members: int,
    seed: int,
) -> float:
    rng = np.random.default_rng(int(seed))
    labels = np.asarray(labels, dtype=np.int64)
    ids = np.unique(labels[labels > 0])
    total = int(np.count_nonzero(labels > 0))
    if total == 0 or ids.size == 0:
        return np.nan
    weighted = 0.0
    weight_sum = 0.0
    for cid in ids:
        members = np.where(labels == int(cid))[0]
        if members.size < int(min_size):
            continue
        weight = members.size / total
        if int(max_members) > 0 and members.size > int(max_members):
            members = rng.choice(members, size=int(max_members), replace=False)
        xm = x_nodes_time[members, :]
        fc = (xm @ xm.T) / max(xm.shape[1] - 1, 1)
        np.fill_diagonal(fc, 0.0)
        h = pc1_variance_percent(fc)
        if np.isfinite(h):
            weighted += weight * h
            weight_sum += weight
    return float(weighted / weight_sum) if weight_sum > 0 else np.nan


def load_rotation_indices(path: Optional[Path], cortex_n: int, n_rot: int) -> Optional[np.ndarray]:
    if path is None or not path.exists() or n_rot <= 0:
        return None
    img = nib.load(str(path))
    arr = np.asarray(img.get_fdata(dtype=np.float32))
    if arr.ndim != 2:
        return None
    rot = np.rint(arr[: min(arr.shape[0], n_rot), :cortex_n]).astype(np.int64)
    if rot.shape[0] < rot.shape[1]:
        # CIFTI dtseries loads as maps x grayordinates; old MATLAB data often
        # represents rotations as grayordinates x rotations after ft_read.
        pass
    if rot.shape[1] != cortex_n and arr.shape[0] >= cortex_n:
        rot = np.rint(arr[:cortex_n, : min(arr.shape[1], n_rot)]).astype(np.int64).T
    if rot.shape[1] != cortex_n:
        return None
    return rot[:n_rot, :]


def apply_rotation(labels: np.ndarray, rot_idx_1based: np.ndarray) -> np.ndarray:
    out = np.zeros_like(labels)
    valid = rot_idx_1based > 0
    src = rot_idx_1based[valid] - 1
    src_ok = (src >= 0) & (src < labels.size)
    dst = np.where(valid)[0][src_ok]
    out[dst] = labels[src[src_ok]]
    return out


def write_summary(path: Path, rows: Sequence[dict]) -> None:
    fields = [
        "column_index",
        "density_value",
        "observed_homogeneity",
        "null_mean",
        "null_sd",
        "z",
        "p_greater",
        "effect_observed_minus_null",
        "n_null",
        "selected_best",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def plot_summary(path: Path, rows: Sequence[dict], nulls: np.ndarray, title: str) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    x = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(max(7, len(rows) * 0.8), 4.5), dpi=160)
    if nulls.size:
        rng = np.random.default_rng(7)
        for i in range(nulls.shape[1]):
            vals = nulls[:, i]
            vals = vals[np.isfinite(vals)]
            if vals.size:
                ax.scatter(
                    np.full(vals.size, i) + rng.normal(0, 0.045, size=vals.size),
                    vals,
                    s=8,
                    color="0.70",
                    alpha=0.45,
                    linewidths=0,
                )
    obs = np.array([float(r["observed_homogeneity"]) for r in rows])
    ax.scatter(x, obs, s=64, facecolor="#c51b29", edgecolor="black", linewidth=0.6, zorder=3)
    best = [i for i, r in enumerate(rows) if int(r["selected_best"]) == 1]
    if best:
        ax.scatter(best, obs[best], marker="*", s=190, color="#f6c945", edgecolor="black", linewidth=0.7, zorder=4)
    labels = [str(r["density_value"] or r["column_index"]) for r in rows]
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.set_xlabel("Graph density / map column, dense to sparse")
    ax.set_ylabel("Size-weighted homogeneity (% PC1 variance)")
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description="PFM homogeneity/spin-null diagnostics")
    ap.add_argument("--in-cifti", required=True)
    ap.add_argument("--labels-cifti", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--density-values", default="")
    ap.add_argument("--rotations-cifti", default="")
    ap.add_argument("--n-rotations", type=int, default=0)
    ap.add_argument("--min-community-size", type=int, default=5)
    ap.add_argument("--max-members-per-community", type=int, default=1000)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--outfile-prefix", default="Homogeneity")
    ap.add_argument("--title", default="PFM Homogeneity Spin Test")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    img = nib.load(args.in_cifti)
    lab_img = nib.load(args.labels_cifti)
    data = np.asarray(img.get_fdata(dtype=np.float32))
    labels_data = np.asarray(lab_img.get_fdata(dtype=np.float32))
    if data.ndim != 2 or labels_data.ndim != 2:
        raise ValueError("Input CIFTI and labels CIFTI must be 2D")
    axis = img.header.get_axis(1)
    cortex_idx = cortical_grayordinates(axis)
    x = zscore_rows(data[:, cortex_idx].T)
    labels_cort = np.rint(labels_data[:, cortex_idx]).astype(np.int64)
    density_values = parse_num_list(args.density_values)
    if density_values and len(density_values) != labels_cort.shape[0]:
        density_values = []

    rotations = load_rotation_indices(
        Path(args.rotations_cifti) if args.rotations_cifti else None,
        cortex_idx.size,
        int(args.n_rotations),
    )
    n_rot = 0 if rotations is None else rotations.shape[0]
    observed = []
    nulls = np.full((n_rot, labels_cort.shape[0]), np.nan, dtype=np.float32)
    for col in range(labels_cort.shape[0]):
        labels = labels_cort[col, :]
        observed.append(
            homogeneity_for_labels(
                x,
                labels,
                int(args.min_community_size),
                int(args.max_members_per_community),
                seed=1000 + col,
            )
        )
        if rotations is not None:
            for r in range(n_rot):
                nulls[r, col] = homogeneity_for_labels(
                    x,
                    apply_rotation(labels, rotations[r, :]),
                    int(args.min_community_size),
                    int(args.max_members_per_community),
                    seed=100000 + col * 1000 + r,
                )

    observed_arr = np.asarray(observed, dtype=np.float64)
    null_mean = np.nanmean(nulls, axis=0) if n_rot else np.full_like(observed_arr, np.nan)
    null_sd = np.nanstd(nulls, axis=0) if n_rot else np.full_like(observed_arr, np.nan)
    effect = observed_arr - null_mean
    p = np.full_like(observed_arr, np.nan)
    z = np.full_like(observed_arr, np.nan)
    if n_rot:
        for i in range(observed_arr.size):
            vals = nulls[:, i]
            vals = vals[np.isfinite(vals)]
            if vals.size:
                p[i] = (np.count_nonzero(vals >= observed_arr[i]) + 1) / (vals.size + 1)
                z[i] = (observed_arr[i] - float(np.mean(vals))) / (float(np.std(vals)) + 1e-8)
    eligible = np.isfinite(effect)
    if n_rot:
        eligible &= p <= float(args.alpha)
    best = int(np.nanargmax(np.where(eligible, effect, -np.inf))) if np.any(eligible) else int(np.nanargmax(observed_arr))

    rows = []
    for i in range(labels_cort.shape[0]):
        rows.append(
            {
                "column_index": i + 1,
                "density_value": density_values[i] if i < len(density_values) else "",
                "observed_homogeneity": observed_arr[i],
                "null_mean": null_mean[i],
                "null_sd": null_sd[i],
                "z": z[i],
                "p_greater": p[i],
                "effect_observed_minus_null": effect[i],
                "n_null": n_rot,
                "selected_best": int(i == best),
            }
        )
    write_summary(outdir / f"{args.outfile_prefix}_summary.csv", rows)
    if n_rot:
        np.save(outdir / f"{args.outfile_prefix}_nulls.npy", nulls)
    plot_summary(outdir / f"{args.outfile_prefix}_summary.png", rows, nulls, args.title)
    print(f"[homogeneity] wrote {outdir / f'{args.outfile_prefix}_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
