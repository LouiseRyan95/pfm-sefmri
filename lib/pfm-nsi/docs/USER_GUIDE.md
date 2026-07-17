# PFM-NSI User Guide

## 1) What This Tool Does

PFM-NSI evaluates FC map quality for precision functional mapping.

Primary metric:

- `NSI` from ridge regression (`R^2`) between subject FC maps and canonical priors

Optional metrics:

- Moran's I
- Spectral slope
- Usability projection (`P(PFM-usable | NSI)`) (enabled by default in Python CLI `run`)
  Uses median NSI (`R^2`, λ=10) as the default summary statistic across Python run/batch and MATLAB.
- Reliability projection (`P(R >= threshold | NSI, time)`)
  If NSI is outside training range for the selected early model, results are labeled as extrapolated outside training range.

Advanced options:

- Binary ROI sparse-target override (no subsampling)
- Per-network NSI histograms (network assignment from ridge betas)
- Per-structure NSI histograms (LH/RH collapsed, grayscale stacked rows)

## 2) Python CLI

Basic run (default: NSI + usability + network/structure histograms):

```bash
pfm-nsi run --cifti /path/to/Data.dtseries.nii
```

fsaverage6 input:

```bash
pfm-nsi run \
  --cifti /path/to/Data.dtseries.nii \
  --fsaverage6
```

With reliability (usability already on by default):

```bash
pfm-nsi run \
  --cifti /path/to/Data.dtseries.nii \
  --reliability \
  --nsi-t 10 \
  --query-t 30,60
```

Advanced ROI override:

```bash
pfm-nsi run \
  --cifti /path/to/Data.dtseries.nii \
  --roi-binary /path/to/roi_mask.dscalar.nii
```

Network histograms are enabled by default in `run` (disable with `--no-network-hists`).

```bash
pfm-nsi run \
  --cifti /path/to/Data.dtseries.nii \
  --network-assignment-lambda 10
```

Structure histograms are enabled by default in `run` (disable with `--no-structure-hists`).

```bash
pfm-nsi run \
  --cifti /path/to/Data.dtseries.nii \
  --structure-assignment-lambda 10
```

Notes:

- `--roi-binary` overrides structure-based sparse selection.
- When `--roi-binary` is set, additional sparse subsampling is disabled.
- Network assignment uses the ridge beta vector for each sparse target and picks `argmax(beta)`.
- Default input mesh is fsLR-32k.
- `--fsaverage6` requires Connectome Workbench (`wb_command`) and resamples cortical data to the packaged fsLR-32k resources before scoring.
- If `wb_command` is not on `PATH`, pass `--wb-command /path/to/wb_command` or set `WB_COMMAND=/path/to/wb_command`.

Sparse target guidance (`SparseFrac`):

- `SparseFrac` controls how many sparse targets are retained after sparse parcellation.
- Lower values reduce runtime substantially; RAM may drop modestly on very large concatenated runs.
- Binary ROI mode (`--roi-binary` / `opts.BinaryROI`) bypasses `SparseFrac`.

Recommended defaults by number of timepoints (`T`):

- `T <= 2000`: use `SparseFrac=0.25` (or full sparse targets for highest fidelity when resources are ample).
- `2000 < T <= 10000`: use `SparseFrac=0.10`.
- `T > 10000` (large concatenations): use `SparseFrac=0.10` as default.

Examples:

```bash
# Faster run on medium/large datasets
pfm-nsi run --cifti /path/to/Data.dtseries.nii --sparse-frac 0.10

# Higher-fidelity sparse sampling with moderate speedup
pfm-nsi run --cifti /path/to/Data.dtseries.nii --sparse-frac 0.25
```

## 3) Python API

```python
from pfm_nsi import pfm_nsi
from pfm_nsi.mesh import prepare_cifti_for_mesh
from pfm_nsi.plots import pfm_nsi_plots

structures = [
    "CORTEX_LEFT", "CEREBELLUM_LEFT", "ACCUMBENS_LEFT", "CAUDATE_LEFT",
    "PALLIDUM_LEFT", "PUTAMEN_LEFT",
        "THALAMUS_LEFT",
        "HIPPOCAMPUS_LEFT", "AMYGDALA_LEFT",
    "CORTEX_RIGHT", "CEREBELLUM_RIGHT", "ACCUMBENS_RIGHT", "CAUDATE_RIGHT",
    "PALLIDUM_RIGHT", "PUTAMEN_RIGHT",
        "THALAMUS_RIGHT",
        "HIPPOCAMPUS_RIGHT", "AMYGDALA_RIGHT",
]

opts = {
    "ridge_lambdas": [10],
    "compute_morans": True,
    "compute_slope": True,
    "compute_network_histograms": True,
    "network_assignment_lambda": 10,
}

prepared = prepare_cifti_for_mesh("/path/to/Data.dtseries.nii", mesh="fslr32k")
qc, maps = pfm_nsi(prepared, structures, "pfm_nsi/models/priors.npz", opts)
pfm_nsi_plots(qc, show_plots=True, network_histograms=True, network_assignment_lambda=10)
```

Python API with fsaverage6 input:

```python
prepared = prepare_cifti_for_mesh(
    "/path/to/Data.dtseries.nii",
    mesh="fsaverage6",
    wb_command="/path/to/wb_command",  # optional if wb_command is already on PATH
)
qc, maps = pfm_nsi(prepared, structures, "pfm_nsi/models/priors.npz", opts)
```

The Python implementation also expects the packaged cortical neighbor table at
`pfm_nsi/models/cifti_surf_neighbors_lr_normalwall.npz` unless you override
`opts["neighbor_mat_path"]`.

ROI override in API:

```python
opts["BinaryROI"] = "/path/to/roi_mask.dscalar.nii"
opts["SparseIdxOverrideBypassStructures"] = True
```

## 4) MATLAB Reference Implementation

```matlab
addpath('/path/to/pfm-nsi/matlab/scripts');
addpath(genpath('/path/to/MSCcodebase/Utilities/read_write_cifti'));

load('/path/to/pfm-nsi/matlab/models/priors.mat');
C = ft_read_cifti_mod('/path/to/Data.dtseries.nii');

opts = struct;
opts.ridge_lambdas = 10;
opts.compute_morans = true;
opts.compute_slope = true;
opts.compute_network_histograms = true;
opts.network_assignment_lambda = 10;

Structures = {'CORTEX_LEFT','CORTEX_RIGHT'};
OUT = pfm_nsi(C, ...
    'Priors', Priors, ...
    'Structures', Structures, ...
    'Opts', opts);
```

MATLAB with fsaverage6 input:

```matlab
OUT = pfm_nsi('/path/to/Data.dtseries.nii', ...
    'Priors', Priors, ...
    'Structures', Structures, ...
    'Opts', opts, ...
    'Mesh', 'fsaverage6', ...
    'WBCommand', '/path/to/wb_command');
```

MATLAB ROI override:

```matlab
opts.BinaryROI = '/path/to/roi_mask.dscalar.nii';
opts.BinaryROIThreshold = 0.5;
```

## 5) Python vs MATLAB Alignment

Options aligned:

- `ridge_lambdas`
- `compute_morans`
- `compute_slope`
- `SparseFrac`
- `SparseIdxOverride`
- `BinaryROI` / binary ROI override behavior
- `compute_network_histograms`
- `network_assignment_lambda`
- `compute_structure_histograms`
- `structure_assignment_lambda`
- input mesh selection (`fslr32k` default, `fsaverage6` optional)

Core output alignment:

- `NSI.Ridge.LambdaXX.R2`
- `NSI.Ridge.LambdaXX.Betas` (optional / memory-saving off by default)
- `NSI.MedianScore`
- `NSI.NetworkAssignment.LambdaXX.NetworkIndex`
- `NSI.NetworkAssignment.LambdaXX.NetworkLabels`
- `NSI.StructureAssignment.LambdaXX.StructureLabelsByTarget`
- `NSI.StructureAssignment.LambdaXX.StructureLabelsUnique`
- `MoransI.mI`
- `SpectralSlope.slope`

## 6) Release Checklist

- Verify CLI help: `pfm-nsi run -h`
- Run one Python + one MATLAB sample and compare `NSI.MedianScore`
- Confirm advanced outputs with ROI and network hist flags
- Tag release and publish README/docs/tutorial
