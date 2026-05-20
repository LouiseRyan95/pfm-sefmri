#!/usr/bin/env bash
# Config for RevisedMe-fMRIPipeline/mefmri_pipeline.sh
#
# Wrapper call:
#   mefmri_pipeline.sh <SubjectDir> [ConfigFile]
#
# Organization:
#   1) Core paths and environment
#   2) Commonly used global knobs
#   3) Module-specific knobs
#   4) Advanced / rarely changed knobs

# =============================================================================
# 1) Core Paths and Environment
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEDIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EnvironmentScript="$MEDIR/HCPpipelines-master/Examples/Scripts/SetUpHCPPipeline.sh"
CHARM_BIN="/home/charleslynch/SimNIBS-4.5/bin/charm"

# Shared resource roots used by downstream modules.
PFM_NETWORK_PRIORS_CORTICAL_MAT="$MEDIR/res0urces/Priors.mat"
PFM_NETWORK_PRIORS_SUBCORTICAL_NII="$MEDIR/res0urces/SubcorticalPriors.nii.gz"
PIPELINE_PYTHON="python3"

# =============================================================================
# 2) Commonly Used Global Knobs
# =============================================================================
# Resume / routing
START_SESSION=1
START_FROM_MODULE="anat_charm"   # validate|anat_hcp|anat_charm|fieldmaps|coreg|headmotion|meica|mgtr|vol2surf|concat|nsi|pfm
STOP_AFTER_MODULE="pfm"          # "" to run full chain

# Functional naming and reference space
FUNC_DIRNAME="rest"              # task folder name under func/unprocessed/ (rest is conventional; any task name is valid)
FUNC_FILE_PREFIX="Rest"
FUNC_XFMS_DIRNAME=""             # empty => follow FUNC_DIRNAME; set explicitly only for shared xfm namespaces
DOF=6
AtlasTemplate="$MEDIR/res0urces/MNI152_T1_2mm.nii.gz"
AtlasSpace="T1w"                 # T1w|MNINonlinear
APPLY_N4_BIAS=0                  # 0|1 ; usually leave off if prescan normalize was enabled

# Global pipeline behavior
RUN_CONFIG_SNAPSHOT=1            # 1 writes effective run metadata snapshot into subject func/qa
VALIDATE_ECHO_DIM4_POLICY="error" # error|warn
FUNC_NOFIELDMAP_MODE=0           # 0|1: functional-only fallback mode with zero-unwarp placeholders
PROCESSING_MODE="auto"           # auto|multi_echo|single_echo
MULTI_ECHO_DENOISE_METHOD="meica" # meica|acompcor
SINGLE_ECHO_DENOISE_METHOD="acompcor" # acompcor
SINGLE_ECHO_ECHO_INDEX=1         # fallback/source echo used for single-echo denoising
CONCAT_ENABLE=1
NSI_ENABLE=1
PFM_ENABLE=1

# Threading
THREADS_DEFAULT=8
THREADS_ANAT_HCP="$THREADS_DEFAULT"
THREADS_FIELDMAPS="$THREADS_DEFAULT"
THREADS_COREG="$THREADS_DEFAULT"
THREADS_HEADMOTION="$THREADS_DEFAULT"
THREADS_MEICA=2

# =============================================================================
# 3) Module-Specific Knobs
# =============================================================================

# -----------------------------------------------------------------------------
# 3a) Anatomy / CHARM / HCP
# -----------------------------------------------------------------------------
HCP_ANAT_CLEAN_START=1           # 1 removes prior anat outputs before rerun
HCP_REGNAME="MSMSulc"            # MSMSulc|FS ; set FS if MSM isn't available
CHARM_REUSE_EXISTING_M2M=0       # 1 reuses existing anat/m2m_<Subject> outputs if present

# CHARM anatomical mask mode used to regenerate T1/T2 brain images.
# - charm: CHARM labeling-derived mask (<100), then dilated [default]
# - hcp: preserve pre-CHARM HCP-style whole-brain mask
CHARM_BRAIN_MASK_MODE="charm"    # charm|hcp
CHARM_BRAIN_MASK_DILATE_ITERS=1  # integer >= 0

# Cortical ribbon generation in anat module
CHARM_CORTICAL_RIBBON_EXCLUDE_LABELS=1  # 1 removes HC/Amy/CSF, 0 keeps FS ribbon-only labels
CHARM_WRITE_CORTICAL_RIBBON=1           # 1 writes anat/T1w/CorticalRibbon.nii.gz

# -----------------------------------------------------------------------------
# 3b) Functional Fieldmaps / Coreg / Headmotion
# -----------------------------------------------------------------------------
FM_PE_MODE="infer"               # infer|config
FM_AP_PE_DIR=""                  # e.g. j-
FM_PA_PE_DIR=""                  # e.g. j
EPIREG_PEDIR=""                  # empty => infer from PE.txt
SCAN_SPECIFIC_FM=1
HEADMOTION_KEEP_MCF=0

# -----------------------------------------------------------------------------
# 3c) MGTR / Vol2Surf
# -----------------------------------------------------------------------------
# MGTR cortical ribbon source
# - xfms: func/xfms/rest/CorticalRibbon_*_func_mask.nii.gz
# - legacy_rois: func/rois/CorticalRibbon.nii.gz built from FreeSurfer ribbon mgz
MGTR_RIBBON_SOURCE="xfms"        # xfms|legacy_rois

MGTR_INPUT_TAG=""                # empty => derive from effective denoising branch
MGTR_OUTPUT_TAG=""               # empty => <MGTR_INPUT_TAG>+MGTR
VOL2SURF_INPUTS=""               # empty => derive from effective denoising branch
VOL2SURF_USE_CORTICAL_RIBBON_MASK=1
VOL2SURF_CIFTI_STAMP=""          # optional non-canonical suffix for experimental comparisons

# -----------------------------------------------------------------------------
# 3d) Tedana / MEICA / Reclassify
# -----------------------------------------------------------------------------
TEDANA_ENV="mefmri_env"          # conda environment used for tedana
TEDANA_ACTIVATE_MODE="conda_activate" # conda_activate|conda_run|direct
TEDANA_COMPAT_MODE="modern"
MEPCA="350"
MaxIterations=500
MaxRestarts=5
TEDANA_VERBOSE=0
MEICA_SKIP_TEDANA_IF_EXISTS=0

MEICA_PARALLEL_JOBS=4
MEICA_RECLASSIFY_ENABLE=1
MEICA_TEDANA_SUBDIR="Tedana"
MEICA_RECLASS_SUBDIR="Reclassify"
MEICA_CLASSIFIER_MODE="nsi"      # nsi|legacy_template_rho|none
MEICA_RECLASS_NO_REPORTS=0       # 0 writes reports, 1 suppresses report generation
MEICA_QC_CIFTI_ENABLE=1
MEICA_QC_CIFTI_TAGS="betas_OC,t2sv,s0v"
MEICA_ORIG_ALIAS_ENABLE=1        # 1 creates legacy/orig filename aliases

# -----------------------------------------------------------------------------
# 3e) Concat
# -----------------------------------------------------------------------------
CONCAT_PYTHON="$PIPELINE_PYTHON"
CONCAT_INPUT_TAG=""              # empty => derive from effective denoising branch
CONCAT_OUT_SUBDIR="ConcatenatedCiftis"
CONCAT_CENSOR_BY_FD=1
CONCAT_FD_THRESHOLD=0.3

# -----------------------------------------------------------------------------
# 3f) NSI
# -----------------------------------------------------------------------------
NSI_USE_EXTERNAL_CLI=1
NSI_PYTHON="$CONCAT_PYTHON"
NSI_INPUT_TAG=""                 # empty => derive from CONCAT_INPUT_TAG
NSI_CONCAT_OUT_SUBDIR="$CONCAT_OUT_SUBDIR"
NSI_FD_THRESHOLD="$CONCAT_FD_THRESHOLD"
NSI_USABILITY_MODEL=1
NSI_RELIABILITY_MODEL=0

# -----------------------------------------------------------------------------
# 3g) PFM
# -----------------------------------------------------------------------------
PFM_STRATEGY="ridge_fusion"           # ridge_fusion | infomap
PFM_PYTHON="$PIPELINE_PYTHON"
PFM_INPUT_CIFTI=""               # empty => derive from concat outputs below
PFM_INPUT_TAG=""                 # empty => derive from CONCAT_INPUT_TAG
PFM_CONCAT_OUT_SUBDIR="$CONCAT_OUT_SUBDIR"
PFM_FD_THRESHOLD="$CONCAT_FD_THRESHOLD"
PFM_DISTANCE_MATRIX=""           # empty => <SubjectDir>/anat/T1w/fsaverage_LR32k/DistanceMatrix.npy
PFM_DISTANCE_BUILD_IF_MISSING=1
PFM_DISTANCE_CORTEX_MODE="hybrid"      # hybrid uses geodesic surface distances, with local Euclidean fallback
PFM_DISTANCE_EUCLIDEAN_OVERRIDE_MM=5   # hybrid only: use Euclidean distance for same-hemi cortical pairs this close
PFM_OUTDIR=""                    # empty => <SubjectDir>/func/<FUNC_DIRNAME>/PFM
PFM_PREP_DIR=""                  # empty => <PFM_OUTDIR>/prep

# =============================================================================
# 4) Advanced / Rarely Changed Knobs
# =============================================================================

# -----------------------------------------------------------------------------
# 4a) Module Entrypoints
# -----------------------------------------------------------------------------
VALIDATE_MODULE="$MEDIR/modules/mefmri_validate_inputs.sh"
ANAT_HCP_MODULE="$MEDIR/modules/mefmri_anat_hcp.sh"
ANAT_CHARM_MODULE="$MEDIR/modules/mefmri_anat_charm.sh"
FUNC_FIELDMAPS_MODULE="$MEDIR/modules/mefmri_func_fieldmaps.sh"
FUNC_COREG_MODULE="$MEDIR/modules/mefmri_func_coreg.sh"
FUNC_HEADMOTION_MODULE="$MEDIR/modules/mefmri_func_headmotion.sh"
FUNC_MEICA_MODULE="$MEDIR/modules/mefmri_func_meica.sh"
FUNC_SINGLEECHO_MODULE="$MEDIR/modules/mefmri_func_singleecho.sh"
FUNC_ACOMPCOR_MODULE="$MEDIR/modules/mefmri_func_acompcor.sh"
FUNC_MGTR_MODULE="$MEDIR/modules/mefmri_func_mgtr.sh"
FUNC_VOL2SURF_MODULE="$MEDIR/modules/mefmri_func_vol2surf.sh"
FUNC_CONCAT_MODULE="$MEDIR/modules/mefmri_func_concat.sh"
FUNC_NSI_MODULE="$MEDIR/modules/mefmri_func_nsi.sh"
FUNC_PFM_MODULE="$MEDIR/modules/mefmri_func_pfm.sh"

# -----------------------------------------------------------------------------
# 4b) Vol2Surf GoodVoxels / Masking Details
# -----------------------------------------------------------------------------
VOL2SURF_USE_GOOD_VOXELS_MASK=1
VOL2SURF_GOOD_VOXELS_FACTOR="0.5"
VOL2SURF_GOOD_VOXELS_SIGMA_MM="5"
VOL2SURF_GOOD_VOXELS_KEEP_INTERMEDIATES=1

# -----------------------------------------------------------------------------
# 4c) Tedana Detailed Options
# -----------------------------------------------------------------------------
TEDANA_FITTYPE="curvefit"        # curvefit|loglin
TEDANA_ICA_METHOD="fastica"      # fastica|robustica
TEDANA_N_ROBUST_RUNS=10
TEDANA_SEED=42
TEDANA_THREADS=4
TEDANA_MASKTYPE="none"           # none|dropout|decay
TEDANA_CONVENTION="orig"         # orig|bids
TEDANA_OVERWRITE=1
TEDANA_LOWMEM=0
TEDANA_USE_EXTERNAL_MIX=0
TEDANA_EXTERNAL_MIX_BASENAME=""

# -----------------------------------------------------------------------------
# 4d) MEICA / Reclassify Detailed Thresholds
# -----------------------------------------------------------------------------
MEICA_PRIORS_MAT="$PFM_NETWORK_PRIORS_CORTICAL_MAT"
MEICA_BETAS_CIFTI=""
MEICA_RHO_RESCUE=0.30
MEICA_RHO_REJECT=0.10

MEICA_NSI_RESCUE_THRESHOLD=0.20
MEICA_NSI_RESCUE_QUANTILE=0.10
MEICA_NSI_KILL_MODE="adaptive"   # adaptive|fixed
MEICA_NSI_KILL_THRESHOLD=0.05    # used only when kill mode=fixed
MEICA_NSI_KILL_MIN=0.04
MEICA_NSI_KILL_MAX=0.10
MEICA_NSI_KILL_INTERCEPT=0.14
MEICA_NSI_KILL_SLOPE=0.25
MEICA_NSI_GUARDRAIL_KAPPA_RHO=1
MEICA_SUBCORT_RATIO_THRESH=5.0
MEICA_KILL_PRIORITY_ENABLE=0
MEICA_KILL_PRIORITY_W_LOGRATIO=0.50
MEICA_KILL_PRIORITY_W_NSI=0.30
MEICA_KILL_PRIORITY_W_VAR=0.20
MEICA_KILL_VAR_FLOOR_QUANTILE=0.60
MEICA_KILL_CUMVAR_CAP=0.95

# -----------------------------------------------------------------------------
# 4e) Concat Detailed Options
# -----------------------------------------------------------------------------
CONCAT_DEMEAN_RUNS=1
CONCAT_VAR_NORM_RUNS=0
CONCAT_VAR_NORM_EPS=1e-8
CONCATENATE_RUNS=1
CONCAT_SAVE_FD_TXT=1
CONCAT_SAVE_SCANIDX_TXT=1

# -----------------------------------------------------------------------------
# 4f) NSI Detailed Options
# -----------------------------------------------------------------------------
NSI_RELIABILITY_NSI_T=10
NSI_RELIABILITY_QUERY_T=60
NSI_EXTERNAL_ROOT="$MEDIR/lib/pfm-nsi"
NSI_EXTERNAL_ENTRY="pfm_nsi.cli"
NSI_EXTERNAL_OUT_SUBDIR=""              # empty => write directly to func/<FUNC_DIRNAME>/qa/NSI
NSI_EXTERNAL_PREFIX="pfm_nsi"
NSI_EXTERNAL_USABILITY="$NSI_USABILITY_MODEL"
NSI_EXTERNAL_RELIABILITY="$NSI_RELIABILITY_MODEL"
NSI_EXTERNAL_NSI_T="$NSI_RELIABILITY_NSI_T"
NSI_EXTERNAL_QUERY_T="$NSI_RELIABILITY_QUERY_T"
NSI_EXTERNAL_THRESHOLDS="0.6,0.7,0.8"
NSI_EXTERNAL_STRUCTURES=""              # empty => pfm-nsi default bilateral structures
NSI_EXTERNAL_MORANS=0
NSI_EXTERNAL_SLOPE=0
NSI_EXTERNAL_RIDGE_LAMBDAS="10"
NSI_EXTERNAL_SPARSE_FRAC=""
NSI_EXTERNAL_THREADS=4
NSI_EXTERNAL_FULLMEM=0
NSI_EXTERNAL_DTYPE="float32"
NSI_EXTERNAL_BLOCK_SIZE=2048
NSI_EXTERNAL_KEEP_ALLRHO=1
NSI_EXTERNAL_KEEP_BETAS=1
NSI_EXTERNAL_KEEP_FC_MAP=0

# -----------------------------------------------------------------------------
# 4g) PFM Shared Resources
# -----------------------------------------------------------------------------
PFM_DISTANCE_VARIANT_CHUNK_ROWS=128
PFM_RESOURCES_ROOT="$MEDIR/res0urces"

# -----------------------------------------------------------------------------
# 4h) PFM Ridge-Fusion
# -----------------------------------------------------------------------------
PFM_RF_OUTFILE="RidgeFusion_VTX"
PFM_RF_FC_WEIGHT=1.0              # weight on subject functional connectivity evidence
PFM_RF_FC_DEMEAN=0             # set 1 when ridge_fusion input has not had GSR/MGTR; demeans each FC fingerprint
PFM_RF_SPATIAL_WEIGHT=0.2         # weight on spatial/network priors
PFM_RF_LAMBDA=10                  # ridge penalty; larger values shrink estimates more strongly toward priors
PFM_RF_LOCAL_EXCLUSION_MM=30      # excludes nearby vertices from FC fingerprints to avoid local smoothing bias
PFM_RF_SUBCORT_REGRESS_ENABLE=1   # regress nearby cortical signal from subcortex before PFM estimation
PFM_RF_SUBCORT_REGRESS_DISTANCE_MM=20
PFM_RF_BRAIN_STRUCTURES_CSV="CORTEX_LEFT,CEREBELLUM_LEFT,ACCUMBENS_LEFT,CAUDATE_LEFT,PUTAMEN_LEFT,THALAMUS_LEFT,HIPPOCAMPUS_LEFT,AMYGDALA_LEFT,CORTEX_RIGHT,CEREBELLUM_RIGHT,ACCUMBENS_RIGHT,CAUDATE_RIGHT,PUTAMEN_RIGHT,THALAMUS_RIGHT,HIPPOCAMPUS_RIGHT,AMYGDALA_RIGHT"
PFM_RF_SMOOTHING_KERNEL=1.7       # mm; set 0 to disable CIFTI smoothing before PFM estimation

# Optional areal parcellation of the network-level PFM output.
PFM_AREAL_ENABLE=1
PFM_AREAL_OUTFILE=""              # empty => auto: <network-label-output>+ArealParcellation
PFM_AREAL_MIN_SIZE=30             # minimum parcel size in grayordinates
PFM_PRIORS_MAT="$PFM_NETWORK_PRIORS_CORTICAL_MAT"
PFM_SUBCORT_PRIORS_NII="$PFM_NETWORK_PRIORS_SUBCORTICAL_NII"
PFM_NEIGHBORS_MAT="$PFM_RESOURCES_ROOT/Cifti_surf_neighbors_LR_normalwall.mat"

# -----------------------------------------------------------------------------
# 4i) PFM Infomap
# -----------------------------------------------------------------------------
PFM_INFOMAP_DISTANCE_MATRIX=""          # empty => PFM_DISTANCE_MATRIX (.npy; auto-built when missing)
PFM_INFOMAP_GRAPH_DENSITIES_EXPR="0.01,0.005,0.002,0.001,0.0005,0.0002,0.0001" # graph densities, from dense to sparse
PFM_INFOMAP_NUM_REPS_EXPR="5,10,20,30,50,75,100"                              # one repeat count per density
PFM_INFOMAP_MIN_DISTANCE=10       # mm; suppresses local edges before community detection
PFM_INFOMAP_BAD_VERTS_CSV=""      # optional comma-separated 0-based grayordinate indices to exclude
PFM_INFOMAP_STRUCTURES_CSV="CORTEX_LEFT,CEREBELLUM_LEFT,ACCUMBENS_LEFT,CAUDATE_LEFT,PUTAMEN_LEFT,THALAMUS_LEFT,HIPPOCAMPUS_LEFT,CORTEX_RIGHT,CEREBELLUM_RIGHT,ACCUMBENS_RIGHT,CAUDATE_RIGHT,PUTAMEN_RIGHT,THALAMUS_RIGHT,HIPPOCAMPUS_RIGHT"
PFM_INFOMAP_NUM_CORES=1
PFM_INFOMAP_BINARY=""                   # set explicit path if infomap is not already on PATH
PFM_INFOMAP_DRY_RUN=0                   # 1=validate arguments/wiring without running computation
PFM_INFOMAP_NETWORK_MAPPING_ENABLE=1    # 1 labels communities with canonical prior network IDs
PFM_INFOMAP_LABEL_OUTFILE="InfomapNetworkLabels"
PFM_INFOMAP_LABEL_FC_WEIGHT=1.0         # community-to-prior functional similarity weight
PFM_INFOMAP_LABEL_SPATIAL_WEIGHT=1.0    # community-to-prior spatial overlap weight
PFM_INFOMAP_LABEL_CONFIDENCE_THRESHOLD=0.15 # below this margin, labels are written but flagged for review
PFM_INFOMAP_LABEL_MIN_FC_SIMILARITY=0.33
PFM_INFOMAP_LABEL_MIN_COMMUNITY_SIZE=10
PFM_INFOMAP_LABEL_UNASSIGNED_VALUE=21   # label ID for communities too small or too weak to assign
PFM_INFOMAP_LABEL_STRICT_THRESHOLDING=0  # 1 converts low-confidence communities to unassigned
PFM_INFOMAP_LABEL_DENSITY_INDEX=-1       # -1 labels all density columns; positive values are 1-based
PFM_INFOMAP_MANUAL_LABEL_APPLY_ENABLE=0
PFM_INFOMAP_MANUAL_LABEL_TABLE=""        # empty => <PFM_OUTDIR>/<PFM_INFOMAP_LABEL_OUTFILE>_ManualCorrections.csv
PFM_INFOMAP_MANUAL_LABEL_OUTFILE="InfomapNetworkLabels_ManualAdjusted"
