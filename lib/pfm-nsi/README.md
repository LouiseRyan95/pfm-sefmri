# PFM-NSI

Precision Functional Mapping - Network Similarity Index (PFM-NSI).

This repository ships two aligned implementations:

- Python package + CLI (`pfm_nsi`, `pfm-nsi` command)
- MATLAB reference implementation (`matlab/scripts/*.m`)

Both implementations compute the same core outputs:

- NSI (ridge-based)
- Usability projection (enabled by default in Python CLI `run`)
- Optional reliability projection (opt-in via `--reliability`)
- Usability projection uses median NSI (`R^2`, λ=10) across Python run/batch and MATLAB
- Optional contextual metrics (Moran's I, spectral slope)
- Advanced binary ROI sparse-target override
- Per-network NSI histograms (enabled by default in Python CLI `run`)
- Per-structure NSI histograms (enabled by default in Python CLI `run`)

Input mesh support:

- Default cortical input mesh: fsLR-32k
- Optional cortical input mesh: fsaverage6
  - Python CLI: `--fsaverage6`
  - MATLAB: `'Mesh', 'fsaverage6'`
  - fsaverage6 input requires Connectome Workbench (`wb_command`) for cortical resampling to packaged fsLR-32k resources

## Install (Python)

From source:

```bash
git clone https://github.com/cjl2007/pfm-nsi.git
cd pfm-nsi
python -m pip install -e .
```

The Python package expects these packaged model assets to be present under `pfm_nsi/models/`:

- `priors.npz`
- `cifti_surf_neighbors_lr_normalwall.npz`
- `nsi_usability_model.json.gz`
- `nsi_reliability_model.json.gz`

If you are working from a source checkout and need to regenerate the `.npz` assets from the MATLAB originals:

```bash
python tools/export_priors_for_python.py \
  matlab/models/priors.mat \
  pfm_nsi/models/priors.npz

python tools/export_neighbors_for_python.py \
  matlab/models/cifti_surf_neighbors_lr_normalwall.mat \
  pfm_nsi/models/cifti_surf_neighbors_lr_normalwall.npz
```

## Quick Start

Single dataset (default: NSI + usability + network/structure histograms):

```bash
pfm-nsi run --cifti /path/to/Data.dtseries.nii
```

fsaverage6 input:

```bash
pfm-nsi run \
  --cifti /path/to/Data.dtseries.nii \
  --fsaverage6
```

Add reliability projection (usability is already on by default):

```bash
pfm-nsi run \
  --cifti /path/to/Data.dtseries.nii \
  --reliability \
  --nsi-t 10 \
  --query-t 60
```

Advanced ROI-targeted NSI (no subsampling, structures overridden):

```bash
pfm-nsi run \
  --cifti /path/to/Data.dtseries.nii \
  --roi-binary /path/to/roi_mask.dscalar.nii
```

Sparse target guidance:

- `--sparse-frac` reduces the number of sparse targets after sparse parcellation.
- Recommended defaults by timepoints (`T`):
  - `T <= 2000`: `--sparse-frac 0.25`
  - `T > 2000`: `--sparse-frac 0.10`
- `--roi-binary` bypasses sparse subsampling.

## MATLAB Reference Implementation

See [matlab/README.md](matlab/README.md) for setup and examples.

Core entry points:

- `matlab/scripts/pfm_nsi.m`
- `matlab/scripts/pfm_nsi_core.m`
- `matlab/scripts/pfm_nsi_plots.m`
- `matlab/scripts/conditional_reliability_from_nsi.m`

For fsaverage6 input in MATLAB:

```matlab
OUT = pfm_nsi('/path/to/Data.dtseries.nii', 'Mesh', 'fsaverage6');
```

## Documentation

- [User Guide](docs/USER_GUIDE.md)
- [Tutorial](docs/TUTORIAL.md)
- [MATLAB README](matlab/README.md)

## Workbench Requirement For fsaverage6

fsaverage6 input uses packaged surface templates plus Connectome Workbench for cortical resampling. The default fsLR-32k path does not require Workbench.

Install Workbench from:

- https://www.humanconnectome.org/software/get-connectome-workbench

Then ensure `wb_command` is available on `PATH`, or pass an explicit path in Python with `--wb-command /path/to/wb_command`.

## Outputs

Python `run` writes:

- `<prefix>_nsi.npz`
- `<prefix>_hist_nsi.png`
- `<prefix>_usability.json` (when usability is enabled)
- `<prefix>_hist_nsi_by_network.png` (default in `run`; disable with `--no-network-hists`)
- `<prefix>_network_hist_summary.csv/.json` (default in `run`)
- `<prefix>_hist_nsi_by_structure.png` (default in `run`; disable with `--no-structure-hists`)
- `<prefix>_structure_hist_summary.csv/.json` (default in `run`)
- `<prefix>_reliability.json` (when `--reliability`)

MATLAB writes `.mat` structures with equivalent fields (see user guide mapping table).

## Citation

Preprint: https://www.biorxiv.org/content/10.64898/2026.02.10.704857v1

## License

MIT

