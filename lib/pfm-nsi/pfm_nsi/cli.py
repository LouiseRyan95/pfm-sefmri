import argparse
import csv
import json
import os
import gzip
from pathlib import Path

try:
    from importlib import metadata as importlib_metadata
except Exception:  # pragma: no cover
    importlib_metadata = None
from typing import Any, Dict, List, Optional

import numpy as np

from .core import pfm_nsi
from .mesh import prepare_cifti_for_mesh
from .plots import pfm_nsi_plots, plot_nsi_usability_distribution
from .reliability import conditional_reliability_from_nsi, load_nsi_reliability_model

USABILITY_SUMMARY_STAT = "median"


def _parse_list(s: Optional[str], cast=float) -> Optional[List]:
    if s is None:
        return None
    if isinstance(s, list):
        return s
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return [cast(p) for p in parts]


def _default_structures() -> List[str]:
    return [
        "CORTEX_LEFT",
        "CEREBELLUM_LEFT",
        "ACCUMBENS_LEFT",
        "CAUDATE_LEFT",
        "PALLIDUM_LEFT",
        "PUTAMEN_LEFT",
        "THALAMUS_LEFT",
        "HIPPOCAMPUS_LEFT",
        "AMYGDALA_LEFT",
        "CORTEX_RIGHT",
        "CEREBELLUM_RIGHT",
        "ACCUMBENS_RIGHT",
        "CAUDATE_RIGHT",
        "PALLIDUM_RIGHT",
        "PUTAMEN_RIGHT",
        "THALAMUS_RIGHT",
        "HIPPOCAMPUS_RIGHT",
        "AMYGDALA_RIGHT",
    ]


def _resolve_model_path(models_dir: str, filename: str, explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    candidate = os.path.join(models_dir, filename)
    if os.path.exists(candidate):
        return candidate
    if os.path.exists(filename):
        return filename
    pkg_path = os.path.join(os.path.dirname(__file__), "models", filename)
    if os.path.isfile(pkg_path):
        return pkg_path
    return candidate


def _load_usability_model(path: str) -> dict:
    if path.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    if path.endswith(".npz"):
        z = np.load(path, allow_pickle=True)
        return {
            "model": {
                "form": str(z["model_form"]),
                "beta": np.asarray(z["model_beta"]),
                "muNSI": np.asarray(z["model_muNSI"]),
            },
            "grid": {
                "x": np.asarray(z["grid_x"]),
                "p": np.asarray(z["grid_p"]),
                "ciLo": np.asarray(z["grid_ciLo"]),
                "ciHi": np.asarray(z["grid_ciHi"]),
            },
            "thresholds": {
                "P": np.asarray(z["thresholds_P"]),
                "NSI": np.asarray(z["thresholds_NSI"]),
            },
        }
    from scipy.io import loadmat

    m = loadmat(path, squeeze_me=True, struct_as_record=False)
    if "NSI_usability_model" not in m:
        raise ValueError("NSI_usability_model not found in .mat")
    mdl = m["NSI_usability_model"]

    def to_dict(x):
        if hasattr(x, "_fieldnames"):
            return {f: to_dict(getattr(x, f)) for f in x._fieldnames}
        return x

    return to_dict(mdl)


def _save_npz(outdir: str, prefix: str, qc: dict) -> str:
    path = os.path.join(outdir, f"{prefix}_nsi.npz")
    np.savez(
        path,
        median_score=qc["NSI"]["MedianScore"],
        r2=qc["NSI"]["Ridge"]["Lambda10"]["R2"],
    )
    return path


def _save_nsi_summary_json(outdir: str, prefix: str, qc: dict) -> str:
    r2 = np.asarray(qc["NSI"]["Ridge"]["Lambda10"]["R2"], dtype=float).ravel()
    summary = {
        "median_nsi": float(qc["NSI"]["MedianScore"]),
        "n_targets": int(r2.size),
        "mean_nsi": float(np.nanmean(r2)) if r2.size else float("nan"),
        "lambda": 10,
    }
    path = os.path.join(outdir, f"{prefix}_nsi_summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return path


def _compute_usability_summary_nsi_from_qc(qc: dict, statistic: str = USABILITY_SUMMARY_STAT) -> float:
    r2 = np.asarray(qc["NSI"]["Ridge"]["Lambda10"]["R2"], dtype=float).ravel()
    if statistic == "median":
        return float(np.nanmedian(r2))
    if statistic == "mean":
        return float(np.nanmean(r2))
    raise ValueError(f"Unsupported usability summary statistic: {statistic}")


def _package_version() -> str:
    if importlib_metadata is None:
        return "unknown"
    try:
        return importlib_metadata.version("pfm-nsi")
    except Exception:
        return "unknown"


def _save_usability_json(
    outdir: str,
    prefix: str,
    args: argparse.Namespace,
    qc: dict,
    plot_summary: dict,
    usability_model: dict,
    model_path: str,
) -> Optional[str]:
    usability = plot_summary.get("usability", {})
    if not usability:
        return None

    payload = {
        "subject_id": _subject_id_from_cifti_path(args.cifti, 1),
        "input_path": os.path.abspath(args.cifti),
        "summary_statistic": str(usability.get("summary_statistic", USABILITY_SUMMARY_STAT)),
        "summary_nsi": float(usability.get("summary_nsi", float("nan"))),
        "p_hat": float(usability.get("p_hat", float("nan"))),
        "ci95": usability.get("ci95", [float("nan"), float("nan")]),
        "decision": usability.get("decision", ""),
        "model": {
            "path": os.path.abspath(model_path),
            "form": str(np.asarray(usability_model.get("model", {}).get("form", "")).squeeze()),
            "beta": np.asarray(usability_model.get("model", {}).get("beta", []), dtype=float).reshape(-1).tolist(),
            "muNSI": float(np.asarray(usability_model.get("model", {}).get("muNSI", float("nan"))).squeeze()),
            "thresholds": usability.get("thresholds", usability_model.get("thresholds", {})),
            "expert_judgement_j": usability.get("expert_judgement_j", {}),
        },
        "nsi": {
            "median_nsi": float(qc["NSI"]["MedianScore"]),
            "mean_nsi": _compute_usability_summary_nsi_from_qc(qc, statistic="mean"),
            "usability_summary_nsi": _compute_usability_summary_nsi_from_qc(qc, statistic=USABILITY_SUMMARY_STAT),
            "lambda": 10,
        },
        "software": {
            "package": "pfm-nsi",
            "version": _package_version(),
        },
    }

    path = os.path.join(outdir, f"{prefix}_usability.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def _build_opts(args: argparse.Namespace) -> Dict[str, Any]:
    ridge_lambdas = _parse_list(args.ridge_lambdas, cast=float) or [10]
    lowmem = not bool(getattr(args, "fullmem", False))
    opts: Dict[str, Any] = {
        "compute_morans": bool(args.morans),
        "compute_slope": bool(args.slope),
        "ridge_lambdas": ridge_lambdas,
        "lowmem": lowmem,
        "use_float32": str(getattr(args, "dtype", "float32")).lower() == "float32",
        "block_size": int(getattr(args, "block_size", 2048)),
        "keep_allrho": bool(getattr(args, "keep_allrho", False)),
        "keep_betas": bool(getattr(args, "keep_betas", False)),
        "keep_fc_map": bool(getattr(args, "keep_fc_map", False)),
        "compute_network_histograms": bool(getattr(args, "network_hists", False)),
        "compute_structure_histograms": bool(getattr(args, "structure_hists", False)),
    }
    if opts["compute_network_histograms"]:
        opts["keep_betas"] = True
    if getattr(args, "network_assignment_lambda", None) is not None:
        opts["network_assignment_lambda"] = float(args.network_assignment_lambda)
    if getattr(args, "structure_assignment_lambda", None) is not None:
        opts["structure_assignment_lambda"] = float(args.structure_assignment_lambda)
    if args.sparse_frac is not None:
        opts["SparseFrac"] = args.sparse_frac
    if getattr(args, "roi_binary", None):
        opts["BinaryROI"] = args.roi_binary
        opts["SparseIdxOverrideBypassStructures"] = True
        if getattr(args, "roi_threshold", None) is not None:
            opts["BinaryROIThreshold"] = float(args.roi_threshold)
        # ROI override is explicit full-target selection: no extra subsampling.
        opts["SparseFrac"] = None
    if args.slope_kmax is not None:
        opts["slope_kmax"] = args.slope_kmax
    if args.slope_low_skip is not None:
        opts["slope_low_skip"] = args.slope_low_skip
    if args.slope_high_frac is not None:
        opts["slope_high_frac"] = args.slope_high_frac
    return opts


def _parse_values_from_file(path: str, cast=float) -> List[Any]:
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    text = src.read_text(encoding="utf-8")
    tokens: List[str] = []
    for ln in text.splitlines():
        line = ln.strip()
        if not line or line.startswith("#"):
            continue
        tokens.extend([t.strip() for t in line.split(",") if t.strip()])
    return [cast(t) for t in tokens]


def _subject_id_from_cifti_path(path: str, index: int) -> str:
    name = os.path.basename(path)
    for suffix in (".dtseries.nii", ".nii", ".gii"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = name.strip().replace(" ", "_")
    return name or f"sample_{index:04d}"


def run(args: argparse.Namespace) -> int:
    os.makedirs(args.outdir, exist_ok=True)

    structures = _default_structures()
    if args.structures and not args.roi_binary:
        structures = _parse_list(args.structures, cast=str)

    opts = _build_opts(args)
    calc_dtype = np.float32 if opts.get("use_float32", True) else np.float64
    prepared_c = prepare_cifti_for_mesh(
        args.cifti,
        mesh=args.mesh,
        dtype=calc_dtype,
        wb_command=getattr(args, "wb_command", None),
    )

    qc, _ = pfm_nsi(prepared_c, structures, args.priors, opts)
    qc_for_reliability = qc

    usability_model = None
    usability_model_path = None
    if args.usability:
        usability_model_path = _resolve_model_path(
            args.models_dir, "nsi_usability_model.json.gz", args.usability_model
        )
        if not os.path.exists(usability_model_path):
            raise FileNotFoundError(f"Usability model not found: {usability_model_path}")
        usability_model = _load_usability_model(usability_model_path)

    save_figs = not args.no_save_figs
    show_plots = save_figs
    prefix = args.prefix

    plot_summary = pfm_nsi_plots(
        qc,
        usability_mdl=usability_model,
        show_plots=show_plots,
        save_dir=args.outdir if save_figs else None,
        prefix=prefix,
        dpi=args.dpi,
        network_histograms=bool(args.network_hists),
        network_assignment_lambda=float(args.network_assignment_lambda),
        structure_histograms=bool(args.structure_hists),
        structure_assignment_lambda=float(args.structure_assignment_lambda),
    )

    _save_npz(args.outdir, prefix, qc)
    _save_nsi_summary_json(args.outdir, prefix, qc)
    if args.usability and usability_model is not None and usability_model_path is not None:
        _save_usability_json(
            args.outdir,
            prefix,
            args,
            qc,
            plot_summary,
            usability_model,
            usability_model_path,
        )

    if args.network_hists:
        ridge_tag = f"Lambda{float(args.network_assignment_lambda):g}"
        net = qc.get("NSI", {}).get("NetworkAssignment", {}).get(ridge_tag, {})
        summary = net.get("Summary", [])
        if summary:
            path = os.path.join(args.outdir, f"{prefix}_network_hist_summary.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                wr = csv.DictWriter(
                    f,
                    fieldnames=["network_index", "network_label", "n_targets", "median_nsi", "mean_nsi"],
                )
                wr.writeheader()
                wr.writerows(summary)
            json_path = os.path.join(args.outdir, f"{prefix}_network_hist_summary.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
    if args.structure_hists:
        ridge_tag = f"Lambda{float(args.structure_assignment_lambda):g}"
        st = qc.get("NSI", {}).get("StructureAssignment", {}).get(ridge_tag, {})
        summary = st.get("Summary", [])
        if summary:
            path = os.path.join(args.outdir, f"{prefix}_structure_hist_summary.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                wr = csv.DictWriter(
                    f,
                    fieldnames=["structure_label", "n_targets", "median_nsi", "mean_nsi"],
                )
                wr.writeheader()
                wr.writerows(summary)
            json_path = os.path.join(args.outdir, f"{prefix}_structure_hist_summary.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)

    if args.reliability:
        rel_path = _resolve_model_path(
            args.models_dir, "nsi_reliability_model.json.gz", args.reliability_model
        )
        if not os.path.exists(rel_path):
            raise FileNotFoundError(f"Reliability model not found: {rel_path}")
        model = load_nsi_reliability_model(rel_path)
        query_t = _parse_list(args.query_t, cast=float) or [60.0]
        thresholds = _parse_list(args.thresholds, cast=float) or [0.6, 0.7, 0.8]

        if args.tr is not None:
            if args.tr <= 0:
                raise ValueError("--tr must be positive.")
            c_early = dict(prepared_c)
            n_total_tp = int(c_early["data"].shape[1])
            n_early_tp = int(round((float(args.nsi_t) * 60.0) / float(args.tr)))
            n_early_tp = max(1, n_early_tp)
            n_used = min(n_total_tp, n_early_tp)
            c_early["data"] = prepared_c["data"][:, :n_used]
            qc_for_reliability, _ = pfm_nsi(c_early, structures, args.priors, opts)
            print(
                f"Reliability NSI window: using first {n_used}/{n_total_tp} timepoints "
                f"(NSI_T={args.nsi_t} min, TR={args.tr} s)."
            )
            print(f"Reliability NSI (MedianScore): {float(qc_for_reliability['NSI']['MedianScore']):.4f}")

        out = conditional_reliability_from_nsi(
            qc_for_reliability,
            model,
            nsi_t=args.nsi_t,
            query_t=query_t,
            thresholds=thresholds,
            verbose=True,
            do_plot=save_figs,
            save_dir=args.outdir if save_figs else None,
            prefix=prefix,
            dpi=args.dpi,
        )

        rel_path_json = os.path.join(args.outdir, f"{prefix}_reliability.json")
        with open(rel_path_json, "w", encoding="utf-8") as f:
            json.dump(out, f, default=lambda x: x.tolist() if hasattr(x, "tolist") else x, indent=2)

    return 0


def batch(args: argparse.Namespace) -> int:
    os.makedirs(args.outdir, exist_ok=True)

    structures = _default_structures()
    if args.structures:
        structures = _parse_list(args.structures, cast=str)
    opts = _build_opts(args)

    usability_path = _resolve_model_path(args.models_dir, "nsi_usability_model.json.gz", args.usability_model)
    if not os.path.exists(usability_path):
        raise FileNotFoundError(f"Usability model not found: {usability_path}")
    usability_model = _load_usability_model(usability_path)

    save_figs = not args.no_save_figs
    use_input = args.batch_input
    prefix = args.prefix

    rows: List[Dict[str, Any]] = []
    nsi_values: List[float] = []

    if use_input in ("cifti-list", "cifti-list-file"):
        if use_input == "cifti-list" and not args.cifti_list:
            raise ValueError("--cifti-list is required when --batch-input cifti-list")
        if use_input == "cifti-list-file" and not args.cifti_list_file:
            raise ValueError("--cifti-list-file is required when --batch-input cifti-list-file")
        if use_input == "cifti-list":
            cifti_paths = _parse_list(args.cifti_list, cast=str) or []
        else:
            cifti_paths = _parse_values_from_file(args.cifti_list_file, cast=str)
        if not cifti_paths:
            raise ValueError("No CIFTI paths were provided for batch mode.")

        for i, cifti_path in enumerate(cifti_paths, start=1):
            calc_dtype = np.float32 if opts.get("use_float32", True) else np.float64
            prepared_c = prepare_cifti_for_mesh(
                cifti_path,
                mesh=args.mesh,
                dtype=calc_dtype,
                wb_command=getattr(args, "wb_command", None),
            )
            qc, _ = pfm_nsi(prepared_c, structures, args.priors, opts)
            nsi = _compute_usability_summary_nsi_from_qc(qc, statistic=USABILITY_SUMMARY_STAT)
            sid = _subject_id_from_cifti_path(cifti_path, i)
            nsi_values.append(nsi)
            rows.append(
                {
                    "subject_id": sid,
                    "source_type": "cifti",
                    "source_value": cifti_path,
                    "nsi": nsi,
                }
            )
    else:
        if use_input == "nsi-values" and not args.nsi_values:
            raise ValueError("--nsi-values is required when --batch-input nsi-values")
        if use_input == "nsi-values-file" and not args.nsi_values_file:
            raise ValueError("--nsi-values-file is required when --batch-input nsi-values-file")
        if use_input == "nsi-values":
            nsi_values = _parse_list(args.nsi_values, cast=float) or []
        else:
            nsi_values = _parse_values_from_file(args.nsi_values_file, cast=float)
        if not nsi_values:
            raise ValueError("No NSI values were provided for batch mode.")
        for i, nsi in enumerate(nsi_values, start=1):
            rows.append(
                {
                    "subject_id": f"sample_{i:04d}",
                    "source_type": "nsi",
                    "source_value": float(nsi),
                    "nsi": float(nsi),
                }
            )

    dist_png = os.path.join(args.outdir, f"{prefix}_usability_distribution.png")
    dist = plot_nsi_usability_distribution(
        nsi_values=nsi_values,
        usability_mdl=usability_model,
        show_plot=save_figs,
        save_path=dist_png if save_figs else None,
        dpi=args.dpi,
    )

    p_hat = np.asarray(dist["p_hat"], dtype=float)
    decisions: List[str] = []
    for p in p_hat:
        if p >= 0.8:
            decisions.append("High (0.8-1.0)")
        elif p >= 0.6:
            decisions.append("Moderate-high (0.6-0.8)")
        elif p >= 0.4:
            decisions.append("Moderate (0.4-0.6)")
        elif p >= 0.2:
            decisions.append("Low (0.2-0.4)")
        else:
            decisions.append("Very low (0.0-0.2)")

    for i, row in enumerate(rows):
        row["p_hat"] = float(p_hat[i])
        row["decision"] = decisions[i]

    csv_path = os.path.join(args.outdir, f"{prefix}_batch_summary.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(
            f,
            fieldnames=["subject_id", "source_type", "source_value", "nsi", "p_hat", "decision"],
        )
        wr.writeheader()
        wr.writerows(rows)

    json_path = os.path.join(args.outdir, f"{prefix}_batch_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "input_mode": use_input,
                "n_samples": len(rows),
                "mean_p_hat": float(dist["mean_p_hat"]),
                "summary_statistic": USABILITY_SUMMARY_STAT,
                "distribution_summary": dist["summary"],
                "rows": rows,
            },
            f,
            indent=2,
        )

    print("\n=== NSI usability batch summary ===")
    print(f"Samples: {len(rows)}")
    print(f"Mean P(PFM-usable|NSI): {dist['mean_p_hat']:.3f}")
    for s in dist["summary"]:
        print(f"  {s['category']:<24} : {s['count']:5d} ({s['percent']:.1f}%)")
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    if save_figs:
        print(f"PNG:  {dist_png}")
    print("===================================\n")

    return 0


def build_parser() -> argparse.ArgumentParser:
    top_epilog = (
        "Common usage:\n"
        "  pfm-nsi run --cifti /path/to/Data.dtseries.nii\n"
        "  pfm-nsi batch --nsi-values 0.2,0.35,0.41,0.58\n"
        "  pfm-nsi run --cifti /path/to/Data.dtseries.nii --no-usability\n"
        "  pfm-nsi batch --batch-input cifti-list-file --cifti-list-file /path/to/ciftis.txt\n"
        "  pfm-nsi run --cifti /path/to/Data.dtseries.nii --reliability --nsi-t 10 --query-t 60\n"
        "  pfm-nsi run --cifti /path/to/Data.dtseries.nii --roi-binary /path/to/roi_mask.dscalar.nii\n"
        "  pfm-nsi run --cifti /path/to/Data.dtseries.nii --network-hists\n\n"
        "Notes:\n"
        "  - `run` computes NSI for one subject and writes subject-level outputs/figures.\n"
        "  - `batch` computes usability across many NSI values or CIFTIs and writes distribution outputs.\n"
        "  - Usability projection is enabled by default for `run` and uses median NSI (λ=10); reliability is opt-in via --reliability.\n"
        "  - Moran's I and spectral slope are advanced metrics (opt-in).\n"
    )
    p = argparse.ArgumentParser(
        prog="pfm-nsi",
        description="PFM-NSI quality control CLI for CIFTI dtseries data.",
        epilog=top_epilog,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    sub = p.add_subparsers(dest="command")

    run_epilog = (
        "Examples:\n"
        "  1) Default run (NSI + usability + network/structure histograms)\n"
        "     pfm-nsi run --cifti /path/to/Data.dtseries.nii\n\n"
        "  2) Disable usability projection\n"
        "     pfm-nsi run --cifti /path/to/Data.dtseries.nii --no-usability\n\n"
        "  3) Reliability projection at 60 minutes\n"
        "     pfm-nsi run --cifti /path/to/Data.dtseries.nii --reliability --nsi-t 10 --query-t 60\n\n"
        "  4) Reliability projection for multiple query times\n"
        "     pfm-nsi run --cifti /path/to/Data.dtseries.nii --reliability --nsi-t 10 --query-t 30,45,60\n\n"
        "  5) Advanced spatial metrics\n"
        "     pfm-nsi run --cifti /path/to/Data.dtseries.nii --morans --slope\n\n"
        "  6) Advanced ROI override (binary mask / index list)\n"
        "     pfm-nsi run --cifti /path/to/Data.dtseries.nii --roi-binary /path/to/roi_mask.dscalar.nii\n\n"
        "  7) Advanced per-network NSI histograms\n"
        "     pfm-nsi run --cifti /path/to/Data.dtseries.nii --network-hists\n\n"
        "  8) Advanced per-structure NSI histograms (LH/RH collapsed)\n"
        "     pfm-nsi run --cifti /path/to/Data.dtseries.nii --structure-hists\n"
    )
    run_p = sub.add_parser(
        "run",
        help="Run PFM-NSI on one dtseries file",
        description=(
            "Run PFM-NSI and optional projections.\n"
            "Default run computes NSI, usability projection, and network/structure histogram outputs.\n"
            "Reliability projection remains opt-in via --reliability."
        ),
        epilog=run_epilog,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    run_io = run_p.add_argument_group("Input/Output")
    run_usability = run_p.add_argument_group("Usability Mode")
    run_reliability = run_p.add_argument_group("Reliability Mode")
    run_plot = run_p.add_argument_group("Plotting/Reporting")
    run_perf = run_p.add_argument_group("Performance/Runtime")

    default_priors = os.path.join(os.path.dirname(__file__), "models", "priors.npz")
    run_io.add_argument("--cifti", required=True, help="Input CIFTI dtseries file (.dtseries.nii)")
    run_io.add_argument(
        "--fsaverage6",
        dest="mesh",
        action="store_const",
        const="fsaverage6",
        default="fslr32k",
        help="Treat the input cortical mesh as fsaverage6 and resample to packaged fsLR-32k resources via wb_command",
    )
    run_io.add_argument(
        "--fslr32k",
        dest="mesh",
        action="store_const",
        const="fslr32k",
        help="Treat the input cortical mesh as fsLR-32k (default)",
    )
    run_io.add_argument(
        "--wb-command",
        default=None,
        help="Optional explicit path to Connectome Workbench wb_command (used only with --fsaverage6)",
    )
    run_io.add_argument(
        "--priors",
        default=default_priors,
        help="Priors file path (default: packaged pfm_nsi/models/priors.npz)",
    )

    run_io.add_argument(
        "--models-dir",
        default="models",
        help="Model directory override (searched before packaged defaults)",
    )
    run_usability.add_argument(
        "--usability-model",
        default=None,
        help="Usability model path (default lookup: models/nsi_usability_model.json.gz)",
    )
    run_reliability.add_argument(
        "--reliability-model",
        default=None,
        help="Reliability model path (default lookup: models/nsi_reliability_model.json.gz)",
    )

    run_io.add_argument("--outdir", default="pfm_nsi_out", help="Output directory (default: pfm_nsi_out)")
    run_io.add_argument("--prefix", default="pfm_nsi", help="Output filename prefix (default: pfm_nsi)")
    run_plot.add_argument("--dpi", type=int, default=150, help="Saved figure DPI (default: 150)")
    run_plot.add_argument("--no-save-figs", action="store_true", help="Disable figure saving")

    run_usability.add_argument(
        "--usability",
        dest="usability",
        action="store_true",
        default=True,
        help="Enable NSI usability projection and usability curve (default: enabled; uses median NSI at λ=10)",
    )
    run_usability.add_argument(
        "--no-usability",
        dest="usability",
        action="store_false",
        help="Disable NSI usability projection and usability curve",
    )
    run_reliability.add_argument(
        "--reliability",
        action="store_true",
        help="Enable reliability projection from NSI",
    )

    run_reliability.add_argument(
        "--nsi-t",
        type=float,
        default=10,
        help="Early window (minutes) used for NSI in reliability projection (default: 10)",
    )
    run_reliability.add_argument(
        "--tr",
        type=float,
        default=None,
        help=(
            "Optional TR in seconds. If set with --reliability, NSI is recomputed on the "
            "first round(nsi_t*60/TR) timepoints before reliability projection."
        ),
    )
    run_reliability.add_argument(
        "--query-t",
        default=None,
        help="Reliability query duration(s), comma-separated minutes (default: 60)",
    )
    run_reliability.add_argument(
        "--thresholds",
        default=None,
        help="Reliability thresholds, comma-separated (default: 0.6,0.7,0.8)",
    )

    run_perf.add_argument("--morans", action="store_true", help="Advanced: compute Moran's I")
    run_perf.add_argument("--slope", action="store_true", help="Advanced: compute spectral slope")
    run_perf.add_argument("--fullmem", action="store_true", help="Disable low-memory mode")
    run_perf.add_argument("--dtype", choices=["float32", "float64"], default="float32", help="Computation dtype (default: float32)")
    run_perf.add_argument("--block-size", type=int, default=2048, help="Target block size for sparse-target processing")
    run_perf.add_argument("--keep-allrho", action="store_true", help="Retain full univariate rho matrix in outputs")
    run_perf.add_argument("--keep-betas", action="store_true", help="Retain ridge beta maps in outputs")
    run_perf.add_argument("--keep-fc-map", action="store_true", help="Retain FC map output in memory/output object")
    run_perf.add_argument("--slope-kmax", type=int, default=None, help="Advanced slope option: kmax")
    run_perf.add_argument("--slope-low-skip", type=int, default=None, help="Advanced slope option: low-skip")
    run_perf.add_argument("--slope-high-frac", type=float, default=None, help="Advanced slope option: high-frac")

    run_perf.add_argument("--sparse-frac", type=float, default=None, help="Optional sparse target fraction (0,1]")
    run_perf.add_argument(
        "--roi-binary",
        default=None,
        help="Advanced: binary ROI (mask or index file) used as sparse targets; overrides structures/subsampling",
    )
    run_perf.add_argument(
        "--roi-threshold",
        type=float,
        default=0.5,
        help="Advanced: threshold applied when --roi-binary provides mask values (default: 0.5)",
    )
    run_plot.add_argument(
        "--network-hists",
        dest="network_hists",
        action="store_true",
        default=True,
        help="Advanced: output per-network NSI histograms using ridge-beta network assignment (default: enabled)",
    )
    run_plot.add_argument(
        "--no-network-hists",
        dest="network_hists",
        action="store_false",
        help="Disable per-network NSI histogram outputs",
    )
    run_plot.add_argument(
        "--network-assignment-lambda",
        type=float,
        default=10.0,
        help="Ridge lambda used for beta-based network assignment (default: 10)",
    )
    run_plot.add_argument(
        "--structure-hists",
        dest="structure_hists",
        action="store_true",
        default=True,
        help="Advanced: output stacked NSI histograms by LH/RH-collapsed brain structure (default: enabled)",
    )
    run_plot.add_argument(
        "--no-structure-hists",
        dest="structure_hists",
        action="store_false",
        help="Disable per-structure NSI histogram outputs",
    )
    run_plot.add_argument(
        "--structure-assignment-lambda",
        type=float,
        default=10.0,
        help="Ridge lambda used for structure-hist NSI values (default: 10)",
    )
    run_perf.add_argument("--ridge-lambdas", default=None, help="Ridge lambdas, comma-separated (default: 10)")
    run_perf.add_argument(
        "--structures",
        default=None,
        help="Comma-separated brain structures to include (default: standard bilateral set)",
    )

    run_p.set_defaults(func=run)

    batch_epilog = (
        "Examples:\n"
        "  1) Batch from NSI values\n"
        "     pfm-nsi batch --nsi-values 0.21,0.33,0.48,0.77\n\n"
        "  2) Batch from NSI values in a text/csv file\n"
        "     pfm-nsi batch --batch-input nsi-values-file --nsi-values-file /path/to/nsi_values.txt\n\n"
        "  3) Batch from CIFTI paths (comma-separated)\n"
        "     pfm-nsi batch --batch-input cifti-list --cifti-list sub1.dtseries.nii,sub2.dtseries.nii\n\n"
        "  4) Batch from CIFTI paths in a file (one per line or comma-separated)\n"
        "     pfm-nsi batch --batch-input cifti-list-file --cifti-list-file /path/to/ciftis.txt\n"
    )
    batch_p = sub.add_parser(
        "batch",
        help="Run usability batch mode over NSI values or multiple CIFTIs",
        description=(
            "Batch mode computes P(PFM-usable|NSI) across a set of NSI values.\n"
            "Inputs can be direct NSI values or CIFTI paths (one median NSI at λ=10 computed per file).\n"
            "Outputs include batch CSV/JSON summaries and a usability distribution plot."
        ),
        epilog=batch_epilog,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    batch_io = batch_p.add_argument_group("Input/Output")
    batch_usability = batch_p.add_argument_group("Usability Mode")
    batch_plot = batch_p.add_argument_group("Plotting/Reporting")
    batch_perf = batch_p.add_argument_group("Performance/Runtime")

    batch_io.add_argument(
        "--batch-input",
        choices=["nsi-values", "nsi-values-file", "cifti-list", "cifti-list-file"],
        default="nsi-values",
        help="Batch input type (default: nsi-values)",
    )
    batch_io.add_argument(
        "--nsi-values",
        default=None,
        help="Comma-separated NSI values (used when --batch-input nsi-values)",
    )
    batch_io.add_argument(
        "--nsi-values-file",
        default=None,
        help="Path to file containing NSI values (newline or comma separated)",
    )
    batch_io.add_argument(
        "--cifti-list",
        default=None,
        help="Comma-separated CIFTI dtseries paths (used when --batch-input cifti-list)",
    )
    batch_io.add_argument(
        "--cifti-list-file",
        default=None,
        help="Path to file containing CIFTI paths (newline or comma separated)",
    )
    batch_io.add_argument(
        "--fsaverage6",
        dest="mesh",
        action="store_const",
        const="fsaverage6",
        default="fslr32k",
        help="Treat input cortical meshes as fsaverage6 and resample to packaged fsLR-32k resources via wb_command",
    )
    batch_io.add_argument(
        "--fslr32k",
        dest="mesh",
        action="store_const",
        const="fslr32k",
        help="Treat input cortical meshes as fsLR-32k (default)",
    )
    batch_io.add_argument(
        "--wb-command",
        default=None,
        help="Optional explicit path to Connectome Workbench wb_command (used only with --fsaverage6)",
    )
    batch_io.add_argument(
        "--priors",
        default=default_priors,
        help="Priors file path (required when batch input is CIFTI paths)",
    )
    batch_io.add_argument(
        "--models-dir",
        default="models",
        help="Model directory override (searched before packaged defaults)",
    )
    batch_usability.add_argument(
        "--usability-model",
        default=None,
        help="Usability model path (default lookup: models/nsi_usability_model.json.gz)",
    )
    batch_io.add_argument("--outdir", default="pfm_nsi_out", help="Output directory (default: pfm_nsi_out)")
    batch_io.add_argument("--prefix", default="pfm_nsi", help="Output filename prefix (default: pfm_nsi)")
    batch_plot.add_argument("--dpi", type=int, default=150, help="Saved figure DPI (default: 150)")
    batch_plot.add_argument("--no-save-figs", action="store_true", help="Disable figure saving")
    batch_perf.add_argument("--morans", action="store_true", help="CIFTI mode only: compute Moran's I")
    batch_perf.add_argument("--slope", action="store_true", help="CIFTI mode only: compute spectral slope")
    batch_perf.add_argument("--fullmem", action="store_true", help="Disable low-memory mode")
    batch_perf.add_argument("--dtype", choices=["float32", "float64"], default="float32", help="Computation dtype (default: float32)")
    batch_perf.add_argument("--block-size", type=int, default=2048, help="Target block size for sparse-target processing")
    batch_perf.add_argument("--keep-allrho", action="store_true", help="Retain full univariate rho matrix in outputs")
    batch_perf.add_argument("--keep-betas", action="store_true", help="Retain ridge beta maps in outputs")
    batch_perf.add_argument("--keep-fc-map", action="store_true", help="Retain FC map output in memory/output object")
    batch_perf.add_argument("--slope-kmax", type=int, default=None, help="Advanced slope option: kmax")
    batch_perf.add_argument("--slope-low-skip", type=int, default=None, help="Advanced slope option: low-skip")
    batch_perf.add_argument("--slope-high-frac", type=float, default=None, help="Advanced slope option: high-frac")
    batch_perf.add_argument("--sparse-frac", type=float, default=None, help="Optional sparse target fraction (0,1]")
    batch_perf.add_argument(
        "--roi-binary",
        default=None,
        help="Advanced CIFTI mode only: binary ROI (mask or index file) used as sparse targets",
    )
    batch_perf.add_argument(
        "--roi-threshold",
        type=float,
        default=0.5,
        help="Advanced CIFTI mode only: threshold applied when --roi-binary provides mask values",
    )
    batch_plot.add_argument(
        "--network-hists",
        action="store_true",
        help="Advanced CIFTI mode only: compute per-network NSI histogram metadata",
    )
    batch_plot.add_argument(
        "--network-assignment-lambda",
        type=float,
        default=10.0,
        help="CIFTI mode only: ridge lambda used for beta-based network assignment (default: 10)",
    )
    batch_plot.add_argument(
        "--structure-hists",
        action="store_true",
        help="Advanced CIFTI mode only: compute stacked NSI histograms by LH/RH-collapsed structure",
    )
    batch_plot.add_argument(
        "--structure-assignment-lambda",
        type=float,
        default=10.0,
        help="CIFTI mode only: ridge lambda used for structure-hist NSI values (default: 10)",
    )
    batch_perf.add_argument("--ridge-lambdas", default=None, help="Ridge lambdas, comma-separated (default: 10)")
    batch_perf.add_argument(
        "--structures",
        default=None,
        help="Comma-separated brain structures to include (CIFTI mode only)",
    )
    batch_p.set_defaults(func=batch)
    return p


def main() -> int:
    p = build_parser()
    args = p.parse_args()
    if not hasattr(args, "func"):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
