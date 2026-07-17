# MATLAB Implementation (PFM-NSI)

This folder provides a MATLAB entrypoint aligned to the Python CLI/API.

## Contents

- `scripts/pfm_nsi.m`
- `scripts/pfm_nsi_plots.m`
- `scripts/pfm_nsi_core.m`
- `scripts/conditional_reliability_from_nsi.m`
- `scripts/local_predict_binom_logit.m`
- `models/priors.mat`
- `models/nsi_usability_model.mat`
- `models/nsi_reliability_model.mat`
- `models/cifti_surf_neighbors_lr_normalwall.mat`
- `examples/example_use.m`

## Requirements

- MATLAB
- MSC CIFTI I/O utilities (`ft_read_cifti_mod`)
  - https://github.com/MidnightScanClub/MSCcodebase

## Setup

```matlab
repo_root = '/path/to/pfm-nsi';
addpath(fullfile(repo_root, 'matlab', 'scripts'));
addpath(genpath('/path/to/MSCcodebase/Utilities/read_write_cifti'));
```

## Basic Usage

```matlab
load(fullfile(repo_root, 'matlab', 'models', 'priors.mat'));
C = ft_read_cifti_mod('/path/to/Data.dtseries.nii');

opts = struct;
opts.ridge_lambdas = 10;
opts.compute_morans = false;
opts.compute_slope = false;
opts.SparseFrac = 0.25; % recommended default for shorter runs

Structures = {'CORTEX_LEFT','CORTEX_RIGHT'};
OUT = pfm_nsi(C, ...
    'Priors', Priors, ...
    'Structures', Structures, ...
    'Opts', opts, ...
    'OutDir', fullfile(repo_root, 'pfm_nsi_out'), ...
    'Prefix', 'pfm_nsi');
```

This writes MATLAB outputs with Python-style basenames such as:

- `pfm_nsi_nsi.mat`
- `pfm_nsi_nsi.json`
- `pfm_nsi_hist_nsi.png`
- `pfm_nsi_hist_moransI.png`
- `pfm_nsi_hist_slope.png`
- `pfm_nsi_power_spectra.png`

## Advanced Options

Binary ROI sparse-target override (advanced, non-default):

```matlab
opts.BinaryROI = '/path/to/roi_mask.dscalar.nii';
opts.BinaryROIThreshold = 0.5;
```

Sparse target guidance (`opts.SparseFrac`):

- `opts.SparseFrac` is applied after sparse parcellation and structure filtering.
- Lower values reduce runtime substantially; RAM reductions are stronger on very large concatenated datasets.
- If `opts.BinaryROI` is set, sparse subsampling is bypassed.

Recommended defaults by number of timepoints (`T`):

- `T <= 2000`: `opts.SparseFrac = 0.25` (or omit for full sparse-target set if resources are ample)
- `2000 < T <= 10000`: `opts.SparseFrac = 0.10`
- `T > 10000`: `opts.SparseFrac = 0.10`

Per-network NSI histograms (advanced):

```matlab
opts.compute_network_histograms = true;
opts.network_assignment_lambda = 10;
opts.compute_structure_histograms = true;
opts.structure_assignment_lambda = 10;
```

When enabled, `QcPfm.NSI.NetworkAssignment.Lambda10` includes:

- `NetworkIndex` (assigned network for each sparse target)
- `NetworkLabels`
- `Summary` (`n_targets`, `median_nsi`, `mean_nsi` per network)

Structure histograms use `QcPfm.NSI.StructureAssignment.Lambda10` with:

- `StructureLabelsByTarget`
- `StructureLabelsUnique`
- `Summary` (`n_targets`, `median_nsi`, `mean_nsi` per structure)

Usability and reliability projections are opt-in, like Python:

```matlab
OUT = pfm_nsi('/path/to/Data.dtseries.nii', ...
    'Usability', true, ...
    'Reliability', true, ...
    'NSI_T', 10, ...
    'QueryT', [30 45 60], ...
    'OutDir', 'pfm_nsi_out', ...
    'Prefix', 'pfm_nsi');
```

This additionally writes:

- `pfm_nsi_usability_curve.png`
- `pfm_nsi_usability.json`
- `pfm_nsi_reliability.mat`
- `pfm_nsi_reliability.json`
- `pfm_nsi_reliability_prob.png`

## Alignment Notes (Python vs MATLAB)

Core fields are aligned:

- `NSI.Ridge.LambdaXX.R2`
- `NSI.Ridge.LambdaXX.Betas` (optional / memory-saving off by default)
- `NSI.MedianScore`
- `NSI.NetworkAssignment.LambdaXX.*` (advanced)
- `MoransI.mI`
- `SpectralSlope.slope`

`pfm_nsi.m` is the user-facing MATLAB entrypoint. `pfm_nsi_core.m` is the internal metric engine used underneath it.
