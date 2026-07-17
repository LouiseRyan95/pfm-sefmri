import argparse
import gzip
import json
import os
import numpy as np

from pfm_nsi import pfm_nsi
from pfm_nsi.mesh import prepare_cifti_for_mesh
from pfm_nsi.plots import pfm_nsi_plots
from pfm_nsi.reliability import (
    conditional_reliability_from_nsi,
    load_nsi_reliability_model,
)


def load_usability_model(path: str):
    if path.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    z = np.load(path, allow_pickle=True)
    out = {
        "model": {"form": str(z["model_form"]), "beta": np.asarray(z["model_beta"]), "muNSI": np.asarray(z["model_muNSI"])},
        "grid": {"x": np.asarray(z["grid_x"]), "p": np.asarray(z["grid_p"]), "ciLo": np.asarray(z["grid_ciLo"]), "ciHi": np.asarray(z["grid_ciHi"])},
        "thresholds": {"P": np.asarray(z["thresholds_P"]), "NSI": np.asarray(z["thresholds_NSI"])},
    }
    return out


def main():
    parser = argparse.ArgumentParser(description="Python ExampleUse for PFM-NSI")
    parser.add_argument("--cifti", default="ME01/Data.dtseries.nii")
    parser.add_argument("--fsaverage6", dest="mesh", action="store_const", const="fsaverage6", default="fslr32k")
    parser.add_argument("--fslr32k", dest="mesh", action="store_const", const="fslr32k")
    parser.add_argument("--wb-command", default=None, help="Optional explicit path to wb_command when using --fsaverage6")
    parser.add_argument("--priors", default="pfm_nsi/models/priors.npz")
    parser.add_argument("--usability", default="pfm_nsi/models/nsi_usability_model.json.gz")
    parser.add_argument("--reliability", default=None, help="pfm_nsi/models/nsi_reliability_model.json.gz")
    parser.add_argument("--roi-binary", default=None, help="Advanced: binary ROI mask/index file for sparse target override")
    parser.add_argument("--network-hists", dest="network_hists", action="store_true", default=True, help="Advanced: render per-network NSI histograms (default: enabled)")
    parser.add_argument("--no-network-hists", dest="network_hists", action="store_false", help="Disable per-network NSI histograms")
    parser.add_argument("--structure-hists", dest="structure_hists", action="store_true", default=True, help="Advanced: render per-structure NSI histograms (default: enabled)")
    parser.add_argument("--no-structure-hists", dest="structure_hists", action="store_false", help="Disable per-structure NSI histograms")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--save-dir", default=None, help="Directory to save figures (png)")
    parser.add_argument("--prefix", default="pfm_nsi", help="Filename prefix for saved figures")
    args = parser.parse_args()
    if args.save_dir:
        os.makedirs(args.save_dir, exist_ok=True)

    structures = [
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

    opts = {"compute_morans": True, "compute_slope": True, "ridge_lambdas": 10, "compute_network_histograms": bool(args.network_hists), "compute_structure_histograms": bool(args.structure_hists), "network_assignment_lambda": 10, "structure_assignment_lambda": 10}
    if args.roi_binary:
        opts["BinaryROI"] = args.roi_binary
        opts["SparseIdxOverrideBypassStructures"] = True
    if args.network_hists:
        opts["keep_betas"] = True

    prepared = prepare_cifti_for_mesh(
        args.cifti,
        mesh=args.mesh,
        dtype=np.float32,
        wb_command=args.wb_command,
    )
    qc, maps = pfm_nsi(prepared, structures, args.priors, opts)
    usability = load_usability_model(args.usability)
    summary = pfm_nsi_plots(
        qc,
        usability,
        show_plots=not args.no_plots,
        save_dir=args.save_dir,
        prefix=args.prefix,
        network_histograms=args.network_hists,
        network_assignment_lambda=10,
        structure_histograms=args.structure_hists,
        structure_assignment_lambda=10,
    )

    print(f"Median NSI (R^2, λ=10): {qc['NSI']['MedianScore']:.4f}")

    if args.reliability:
        model = load_nsi_reliability_model(args.reliability)
        out = conditional_reliability_from_nsi(
            qc,
            model,
            nsi_t=10,
            query_t=60,
            thresholds=(0.6, 0.7, 0.8),
            verbose=True,
            do_plot=not args.no_plots,
            save_dir=args.save_dir,
            prefix=args.prefix,
        )
        print("Reliability forecast complete.")


if __name__ == "__main__":
    main()
