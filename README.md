# pfm-mefmri

This repository contains a modular, config-driven multi-echo fMRI preprocessing pipeline for subject directories organized in the expected local project layout.

## Release Defaults

The main pipeline config is `config/mefmri_wrapper_config.sh`.

Current release notes:

- `PROCESSING_MODE="auto"` switches single-echo runs into the single-echo branch automatically when the input layout only contains one echo per run.
- `MULTI_ECHO_DENOISE_METHOD` supports `meica`, `acompcor`, and ICA-AROMA branches; `acompcor` will generate OCME and run aCompCor on it instead of ME-ICA.
- In `single_echo` mode, the pipeline uses `E1` as the source image and writes `*_E1+aCompCor`.
- In `multi_echo` mode with `acompcor`, the pipeline uses `OCME` as the source image and writes `*_OCME+aCompCor`.
- `START_FROM_MODULE` and `STOP_AFTER_MODULE` use `denoise` for the denoising stage; legacy `meica` is still accepted as an alias.
- `MGTR_ENABLE="auto"` skips MGTR after aCompCor because aCompCor already includes the cortical-ribbon mean signal and derivative in its nuisance model. Set `MGTR_ENABLE=1` to force MGTR.
- `FUNC_NOFIELDMAP_MODE=1` enables the no-fieldmap fallback path with zero-unwarp placeholders.
- `DISTORTION_CORRECTION_MODE="medic"` enables the experimental MEDIC/warpkit distortion-correction path.
- QA outputs now live under `func/<FUNC_DIRNAME>/qa/`; coregistration QA is written to `func/<FUNC_DIRNAME>/qa/Coreg/`.
- Infomap PFM density outputs now use the actual density value in filenames and include `InfomapNetworkLabels_Density<value>_FC.dscalar.nii` community-average FC summaries.

## Setup

Before first run on a new machine:

1. Clone the repository and initialize submodules:

```bash
git clone https://github.com/cjl2007/pfm-mefmri.git
cd pfm-mefmri
git submodule update --init --recursive
```

2. Install the software listed in `SOFTWARE_DEPENDENCIES.txt`.
3. Ensure FSL, FreeSurfer, Connectome Workbench, GNU Parallel, and Python are available on `PATH`.
4. Review `config/mefmri_wrapper_config.sh` and fill in any machine-specific settings.
5. Set `FS_LICENSE` or `FS_LICENSE_FILE` to a readable FreeSurfer `license.txt`.
6. If CHARM is not on `PATH`, set `CHARM_BIN` in the config.
7. If using ICA-AROMA or experimental MEDIC/warpkit, confirm the relevant conda environments or executable overrides in the config.

## Distortion Correction

The default distortion-correction mode is the TOPUP/field-map path:

```bash
DISTORTION_CORRECTION_MODE="topup"
```

Other modes:

- `DISTORTION_CORRECTION_MODE="none"` uses the no-fieldmap fallback path and creates zero-unwarp placeholders.
- `DISTORTION_CORRECTION_MODE="medic"` uses the experimental MEDIC/warpkit path. This requires phase images alongside magnitude echoes and working `wk-medic`, `wk-apply-warp`, and `wk-compute-jacobian` executables.

## pfm-nsi

This release includes `pfm-nsi` as a bundled git submodule at `lib/pfm-nsi`.

Default behavior:

- `NSI_USE_EXTERNAL_CLI=1`
- `NSI_EXTERNAL_ROOT="$MEDIR/lib/pfm-nsi"`

This means a standard clone plus `git submodule update --init --recursive` is enough to use the bundled release-pinned `pfm-nsi`.

If you want to use a different local `pfm-nsi` checkout instead of the bundled one, edit `config/mefmri_wrapper_config.sh` and set:

```bash
NSI_EXTERNAL_ROOT="/full/path/to/your/pfm-nsi"
```

## PFM Strategies

PFM supports two strategies through `PFM_STRATEGY`.

`infomap` is the community-detection workflow previously used by our group,
including Lynch et al. 2024 Nature. The current Python path preserves that basic
approach, then optionally maps subject-specific Infomap communities onto
canonical network IDs with `PFM_INFOMAP_NETWORK_MAPPING_ENABLE=1`. This mapping
is a post-processing step: it does not force Infomap to return a fixed number of
communities, and multiple communities may receive the same canonical network
label. The labeler combines each community's functional similarity to the
network priors with its spatial overlap, writes confidence maps/tables, flags
low-confidence assignments for review, supports manual correction tables, and
builds mode/probability consensus outputs across graph densities.

`ridge_fusion` is a newer, faster PFM strategy. It estimates network assignments
with a ridge-regularized fusion of subject functional connectivity evidence and
spatial/network priors. The prior-guided formulation is intended to reduce the
runtime and improve stability on difficult or lower-quality datasets while still
allowing the subject data to drive deviations from the priors.
For inputs without GSR/MGTR-style global signal control, set
`PFM_RF_FC_DEMEAN=1` to demean each FC fingerprint before ridge fusion.

Both strategies can optionally feed the areal parcellation step
(`PFM_AREAL_ENABLE=1`), which sub-parcellates the network-level output into
smaller areal parcels.

Infomap uses the Python engine in `lib/pfm_infomap.py`. If `infomap` is not on
`PATH`, set `PFM_INFOMAP_BINARY=/full/path/to/infomap`. For bring-up,
`PFM_INFOMAP_DRY_RUN=1` validates argument wiring without running the heavy
community-detection computation.

With `PFM_INFOMAP_NETWORK_MAPPING_ENABLE=1`, the Infomap path writes:

- `Bipartite_PhysicalCommunities.dtseries.nii`
- `InfomapNetworkLabels_Density<value>.dlabel.nii`
- `InfomapNetworkLabels_Density<value>_Confidence.dscalar.nii`
- `InfomapNetworkLabels_Density<value>_FC.dscalar.nii`
- `InfomapNetworkLabels_Density<value>_CommunityTable.csv`
- `InfomapNetworkLabels_Density<value>_AmbiguousCommunities.csv`
- `InfomapNetworkLabels_ModeConsensus.dlabel.nii`
- `InfomapNetworkLabels_ProbabilityConsensus.dscalar.nii`

`Density<value>` uses the actual graph density, for example `Density0.0005`.

With areal parcellation enabled, the final areal output is named from the
network-label prefix, for example `InfomapNetworkLabels+ArealParcellation.dlabel.nii`
or `RidgeFusion_VTX+ArealParcellation.dlabel.nii`.

## Expected Subject Layout

Before preprocessing, each subject directory should be organized as follows:

```text
ME001/
  anat/
    unprocessed/
      T1w/
        T1w_1.nii.gz
        T1w_1.json
        T1w_2.nii.gz
        T1w_2.json
        ...
      T2w/
        T2w_1.nii.gz
        T2w_1.json
        T2w_2.nii.gz
        T2w_2.json
        ...
  func/
    unprocessed/
      [task_name]/
        field_maps/
          AP_S1_R1.nii.gz
          AP_S1_R1.json
          AP_S1_R2.nii.gz
          AP_S1_R2.json
          PA_S1_R1.nii.gz
          PA_S1_R1.json
          PA_S1_R2.nii.gz
          PA_S1_R2.json
        session_1/
          run_1/
            [TaskPrefix]_S1_R1_E1.nii.gz
            [TaskPrefix]_S1_R1_E1.json
            [TaskPrefix]_S1_R1_E2.nii.gz
            [TaskPrefix]_S1_R1_E2.json
            [TaskPrefix]_S1_R1_E3.nii.gz
            [TaskPrefix]_S1_R1_E3.json
            [TaskPrefix]_S1_R1_E4.nii.gz
            [TaskPrefix]_S1_R1_E4.json
          run_2/
            [TaskPrefix]_S1_R2_E1.nii.gz
            [TaskPrefix]_S1_R2_E1.json
            [TaskPrefix]_S1_R2_E2.nii.gz
            [TaskPrefix]_S1_R2_E2.json
            [TaskPrefix]_S1_R2_E3.nii.gz
            [TaskPrefix]_S1_R2_E3.json
            [TaskPrefix]_S1_R2_E4.nii.gz
            [TaskPrefix]_S1_R2_E4.json
```
## Notes

At least one T1-weighted image is required: T1w_1.nii.gz with its matching T1w_1.json.

Additional T1w repeats are supported (T1w_2, T1w_3, etc.) and will be averaged before downstream structural processing and FreeSurfer.

T2-weighted images are optional. If provided, each image should also have a matching JSON sidecar.

Additional T2w repeats are supported and will be averaged in the same way.

Functional runs should be organized by session and run, with one NIfTI file and one matching JSON sidecar per echo.

The number of echoes is flexible. The example above shows 4 echoes, but runs may contain 3, 5, or however many echoes are present in the acquisition.

Set `FUNC_DIRNAME="[task_name]"` and `FUNC_FILE_PREFIX="[TaskPrefix]"` to match the folder and functional filename prefix used by your study.

Field maps should be placed in `func/unprocessed/<FUNC_DIRNAME>/field_maps/`, with a matching JSON sidecar for each NIfTI file. Processed field maps are written to `func/<FUNC_DIRNAME>/field_maps/`, so acquisition-specific field maps stay tied to the task that uses them.

Set `FUNC_DIRNAME="All"` to process every task folder discovered under `func/unprocessed/`. Anatomy runs once, then each task is processed separately.

AP and PA are shown for illustrative purposes only. Other phase-encoding direction pairs (for example, RL / LR) are also acceptable, provided they are named consistently and specified correctly in the pipeline configuration.

In general, every input NIfTI file is expected to have a corresponding .json sidecar containing the required acquisition metadata.

## Importers

Two helper entrypoints are provided to build the expected subject layout.

### Import Raw Scanner Exports

Use `bin/mefmri_import_raw.sh` when your input is a raw DICOM export folder.

The default raw import template is `config/mefmri_import_raw_config.sh`. Update its protocol name, expected counts, and regex rules to match your study before use.

Example:

```bash
bash bin/mefmri_import_raw.sh \
  /path/to/raw_dicom_export \
  /path/to/study/ME001 \
  config/mefmri_import_raw_config.sh \
  --session 1
```

Dry-run example:

```bash
bash bin/mefmri_import_raw.sh \
  /path/to/raw_dicom_export \
  /path/to/study/ME001 \
  config/mefmri_import_raw_config.sh \
  --session 1 \
  --dry-run
```

### Import From BIDS

Use `bin/mefmri_import_bids.sh` when your source data are already in BIDS.

This importer maps BIDS inputs into the pipeline's expected local layout and can either symlink or copy files.

Example:

```bash
bash bin/mefmri_import_bids.sh \
  /path/to/bids \
  [subject_label] \
  /path/to/study/[subject_id] \
  --task [bids_task_name] \
  --func-dirname [task_name] \
  --func-prefix [TaskPrefix] \
  --mode symlink \
  --overwrite
```

## Running The Pipeline

Default invocation:

```bash
bash bin/mefmri_pipeline.sh /path/to/study/ME001
```

Explicit config:

```bash
bash bin/mefmri_pipeline.sh \
  /path/to/study/ME001 \
  config/mefmri_wrapper_config.sh
```

The pipeline default config path is already `config/mefmri_wrapper_config.sh`, so the second argument is only needed when testing an alternate config.

## Provenance And QA

Canonical output filenames are preserved. Provenance is recorded through logs and run metadata snapshots.

When `RUN_CONFIG_SNAPSHOT=1`, each run writes:

- `func/<FUNC_DIRNAME>/qa/RunMetadata/pipeline_run_<timestamp>.txt`
- `func/<FUNC_DIRNAME>/qa/Coreg/`

When `NSI_USE_EXTERNAL_CLI=1`, NSI outputs are written under:

- `func/<FUNC_DIRNAME>/qa/NSI/`

## Author

Chuck Lynch  
cjl2007@med.cornell.edu
