# PFM-NSI Tutorial (Common Workflows)

## Workflow 1: "Is this dataset usable for PFM?"

Run NSI + usability model (default usability summary statistic: median NSI at λ=10):

```bash
pfm-nsi run \
  --cifti /data/sub-01_rest.dtseries.nii \
  --usability \
  --outdir ./out_sub01 \
  --prefix sub01
```

Inspect:

- `sub01_nsi.npz`
- `sub01_hist_nsi.png`
- `sub01_usability_curve.png`

## Workflow 2: "Given a 10-min scout, what reliability at 60 min?"

```bash
pfm-nsi run \
  --cifti /data/sub-01_10min.dtseries.nii \
  --reliability \
  --nsi-t 10 \
  --query-t 60 \
  --thresholds 0.6,0.7,0.8 \
  --outdir ./out_sub01_scout
```

Inspect:

- `pfm_nsi_reliability.json`
- reliability plot PNG (if figure saving enabled)

If the scout NSI is outside model training range, both JSON and plot title are labeled as extrapolated outside training range.

## Workflow 3: "Evaluate only an ROI (advanced)"

Use ROI as direct sparse-target mask; this overrides structure defaults and subsampling.

```bash
pfm-nsi run \
  --cifti /data/sub-01_rest.dtseries.nii \
  --roi-binary /data/roi_motor.dscalar.nii \
  --outdir ./out_sub01_roi \
  --prefix sub01_roi
```

Accepted ROI input types:

- CIFTI/NIfTI mask file
- `.mat` / `.npy` / `.npz` vector
- `.txt` / `.csv` mask vector or 1-based index list

## Workflow 4: "How does NSI distribution vary by assigned network?" (advanced)

```bash
pfm-nsi run \
  --cifti /data/sub-01_rest.dtseries.nii \
  --network-hists \
  --network-assignment-lambda 10 \
  --structure-hists \
  --structure-assignment-lambda 10 \
  --outdir ./out_sub01_networks
```

Inspect:

- `pfm_nsi_hist_nsi_by_network.png`
- `pfm_nsi_network_hist_summary.csv`
- `pfm_nsi_network_hist_summary.json`
- `pfm_nsi_hist_nsi_by_structure.png`
- `pfm_nsi_structure_hist_summary.csv`
- `pfm_nsi_structure_hist_summary.json`

Interpretation rule used:

- For each sparse target, use ridge betas at selected lambda.
- Assign target to the network with the largest beta value.
- Plot NSI (`R^2`) histogram for each assigned network.

## Workflow 5: Batch usability across many samples

From NSI values:

```bash
pfm-nsi batch --nsi-values 0.22,0.31,0.49,0.77 --outdir ./out_batch
```

From CIFTI list file:

```bash
pfm-nsi batch \
  --batch-input cifti-list-file \
  --cifti-list-file /data/cifti_paths.txt \
  --outdir ./out_batch_cifti
```

Inspect:

- `pfm_nsi_batch_summary.csv`
- `pfm_nsi_batch_summary.json`
- `pfm_nsi_usability_distribution.png`

## MATLAB Equivalents

```matlab
opts = struct;
opts.ridge_lambdas = 10;
opts.compute_morans = true;
opts.compute_slope = true;
opts.compute_network_histograms = true;
opts.network_assignment_lambda = 10;
opts.compute_structure_histograms = true;
opts.structure_assignment_lambda = 10;

% Advanced ROI-only sparse targets
opts.BinaryROI = '/data/roi_motor.dscalar.nii';
opts.BinaryROIThreshold = 0.5;

OUT = pfm_nsi(C, ...
    'Priors', Priors, ...
    'Structures', Structures, ...
    'Opts', opts);
```
