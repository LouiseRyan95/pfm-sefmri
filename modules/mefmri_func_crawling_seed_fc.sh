#!/usr/bin/env bash
# Generate a crawling seed-FC QC movie from the final concatenated CIFTI.
set -euo pipefail

Subject="${1:?missing Subject}"
StudyFolder="${2:?missing StudyFolder}"
MEDIR="${3:?missing MEDIR}"
_unused_start_session="${4:?missing StartSession}"
FuncDirName="${5:-${FUNC_DIRNAME:-rest}}"
FuncFilePrefix="${6:-${FUNC_FILE_PREFIX:-Rest}}"

SubjectDir="${StudyFolder}/${Subject}"
CRAWLING_SEED_FC_PYTHON="${CRAWLING_SEED_FC_PYTHON:-${PIPELINE_PYTHON:-python3}}"
CRAWLING_SEED_FC_INPUT_CIFTI="${CRAWLING_SEED_FC_INPUT_CIFTI:-}"
CRAWLING_SEED_FC_INPUT_TAG="${CRAWLING_SEED_FC_INPUT_TAG:-${CONCAT_INPUT_TAG:-OCME+MEICA+MGTR}}"
CRAWLING_SEED_FC_CONCAT_OUT_SUBDIR="${CRAWLING_SEED_FC_CONCAT_OUT_SUBDIR:-${CONCAT_OUT_SUBDIR:-ConcatenatedCiftis}}"
CRAWLING_SEED_FC_FD_THRESHOLD="${CRAWLING_SEED_FC_FD_THRESHOLD:-${CONCAT_FD_THRESHOLD:-0.3}}"
CRAWLING_SEED_FC_OUTDIR="${CRAWLING_SEED_FC_OUTDIR:-${SubjectDir}/func/${FuncDirName}/qa/CrawlingSeedFC}"
case "$Subject" in
  sub-*) DEFAULT_CRAWLING_SEED_FC_SUBJECT="$Subject" ;;
  *) DEFAULT_CRAWLING_SEED_FC_SUBJECT="sub-${Subject}" ;;
esac
CRAWLING_SEED_FC_SUBJECT="${CRAWLING_SEED_FC_SUBJECT:-${DEFAULT_CRAWLING_SEED_FC_SUBJECT}}"
CRAWLING_SEED_FC_WB_COMMAND="${CRAWLING_SEED_FC_WB_COMMAND:-wb_command}"
CRAWLING_SEED_FC_WB_SURFER2="${CRAWLING_SEED_FC_WB_SURFER2:-}"
CRAWLING_SEED_FC_WB_SURFER2_CONDA_ENV="${CRAWLING_SEED_FC_WB_SURFER2_CONDA_ENV:-}"
CRAWLING_SEED_FC_SCENE_TEMPLATE="${CRAWLING_SEED_FC_SCENE_TEMPLATE:-${MEDIR}/res0urces/CrawlingSeedFC/FlatMaps+Inflated.scene}"
CRAWLING_SEED_FC_VERTICES="${CRAWLING_SEED_FC_VERTICES:-${MEDIR}/res0urces/CrawlingSeedFC/VerticesToSample.txt}"
CRAWLING_SEED_FC_TEMPLATE_SUBJECT="${CRAWLING_SEED_FC_TEMPLATE_SUBJECT:-sub-ME01}"
CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR="${CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR:-}"
CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX="${CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX:-}"
CRAWLING_SEED_FC_FLAT_SURFACE_RESOURCE_DIR="${CRAWLING_SEED_FC_FLAT_SURFACE_RESOURCE_DIR:-}"
CRAWLING_SEED_FC_FLAT_SURFACE_SUBJECT_PREFIX="${CRAWLING_SEED_FC_FLAT_SURFACE_SUBJECT_PREFIX:-}"
CRAWLING_SEED_FC_VERTEX_MODE="${CRAWLING_SEED_FC_VERTEX_MODE:-CORTEX_LEFT}"
CRAWLING_SEED_FC_ATLAS_SPACE="${CRAWLING_SEED_FC_ATLAS_SPACE:-${AtlasSpace:-T1w}}"
CRAWLING_SEED_FC_WIDTH="${CRAWLING_SEED_FC_WIDTH:-1280}"
CRAWLING_SEED_FC_HEIGHT="${CRAWLING_SEED_FC_HEIGHT:-720}"
CRAWLING_SEED_FC_FRAMERATE="${CRAWLING_SEED_FC_FRAMERATE:-10}"
CRAWLING_SEED_FC_NUM_CPUS_REQUESTED="${CRAWLING_SEED_FC_NUM_CPUS:-1}"
CRAWLING_SEED_FC_MAX_CPUS="${CRAWLING_SEED_FC_MAX_CPUS:-1}"
for cpu_value in "$CRAWLING_SEED_FC_NUM_CPUS_REQUESTED" "$CRAWLING_SEED_FC_MAX_CPUS"; do
  [[ "$cpu_value" =~ ^[1-9][0-9]*$ ]] || {
    echo "ERROR: crawling seed FC CPU values must be positive integers: $cpu_value"
    exit 2
  }
done
if (( CRAWLING_SEED_FC_NUM_CPUS_REQUESTED > CRAWLING_SEED_FC_MAX_CPUS )); then
  echo "[crawling_seed_fc] limiting render workers from ${CRAWLING_SEED_FC_NUM_CPUS_REQUESTED} to safety cap ${CRAWLING_SEED_FC_MAX_CPUS}"
  CRAWLING_SEED_FC_NUM_CPUS="$CRAWLING_SEED_FC_MAX_CPUS"
else
  CRAWLING_SEED_FC_NUM_CPUS="$CRAWLING_SEED_FC_NUM_CPUS_REQUESTED"
fi
CRAWLING_SEED_FC_TARGET_SIZE_MB="${CRAWLING_SEED_FC_TARGET_SIZE_MB:-10}"
CRAWLING_SEED_FC_FFMPEG="${CRAWLING_SEED_FC_FFMPEG:-ffmpeg}"
CRAWLING_SEED_FC_FFPROBE="${CRAWLING_SEED_FC_FFPROBE:-ffprobe}"
CRAWLING_SEED_FC_FORCE="${CRAWLING_SEED_FC_FORCE:-0}"
CRAWLING_SEED_FC_FORCE_DCONN="${CRAWLING_SEED_FC_FORCE_DCONN:-0}"
CRAWLING_SEED_FC_SKIP_MOVIE="${CRAWLING_SEED_FC_SKIP_MOVIE:-0}"
CRAWLING_SEED_FC_KEEP_SOURCE_MOVIE="${CRAWLING_SEED_FC_KEEP_SOURCE_MOVIE:-0}"
CRAWLING_SEED_FC_KEEP_DCONN="${CRAWLING_SEED_FC_KEEP_DCONN:-0}"
CRAWLING_SEED_FC_COPY_DTSERIES="${CRAWLING_SEED_FC_COPY_DTSERIES:-0}"

if [[ -z "$CRAWLING_SEED_FC_INPUT_CIFTI" ]]; then
  FD_TAG="${CRAWLING_SEED_FC_FD_THRESHOLD//./p}"
  CRAWLING_SEED_FC_INPUT_CIFTI="${SubjectDir}/func/${FuncDirName}/${CRAWLING_SEED_FC_CONCAT_OUT_SUBDIR}/${FuncFilePrefix}_${CRAWLING_SEED_FC_INPUT_TAG}_Concatenated+FDlt${FD_TAG}.dtseries.nii"
fi

[[ -f "$CRAWLING_SEED_FC_INPUT_CIFTI" ]] || { echo "ERROR: missing crawling seed FC input CIFTI: $CRAWLING_SEED_FC_INPUT_CIFTI"; exit 2; }
[[ -f "$CRAWLING_SEED_FC_SCENE_TEMPLATE" ]] || { echo "ERROR: missing crawling seed FC scene template: $CRAWLING_SEED_FC_SCENE_TEMPLATE"; exit 2; }
[[ -f "$CRAWLING_SEED_FC_VERTICES" ]] || { echo "ERROR: missing crawling seed FC vertex list: $CRAWLING_SEED_FC_VERTICES"; exit 2; }

if [[ -z "$CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR" ]]; then
  case "$CRAWLING_SEED_FC_ATLAS_SPACE" in
    T1w|t1w|Tlw|tlw)
      CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR="${SubjectDir}/anat/T1w/fsaverage_LR32k"
      CRAWLING_SEED_FC_FLAT_SURFACE_RESOURCE_DIR="${CRAWLING_SEED_FC_FLAT_SURFACE_RESOURCE_DIR:-${SubjectDir}/anat/MNINonLinear/fsaverage_LR32k}"
      ;;
    MNINonlinear|mninonlinear|MNI|mni)
      CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR="${SubjectDir}/anat/MNINonLinear/fsaverage_LR32k"
      ;;
    *)
      echo "ERROR: invalid CRAWLING_SEED_FC_ATLAS_SPACE='${CRAWLING_SEED_FC_ATLAS_SPACE}' (expected T1w or MNINonlinear)"
      exit 2
      ;;
  esac
fi

if [[ -z "$CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX" ]]; then
  shopt -s nullglob
  surface_prefix_candidates=(
    "$CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR"/*.L.midthickness.32k_fs_LR.surf.gii
  )
  shopt -u nullglob

  case "${#surface_prefix_candidates[@]}" in
    1)
      surface_prefix_filename="${surface_prefix_candidates[0]##*/}"
      CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX="${surface_prefix_filename%.L.midthickness.32k_fs_LR.surf.gii}"
      echo "[crawling_seed_fc] inferred surface prefix=${CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX}"
      ;;
    0)
      echo "ERROR: cannot infer crawling seed FC surface prefix: no '*.L.midthickness.32k_fs_LR.surf.gii' file in ${CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR}"
      echo "Set CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX explicitly."
      exit 2
      ;;
    *)
      echo "ERROR: cannot infer crawling seed FC surface prefix: found ${#surface_prefix_candidates[@]} matching files in ${CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR}"
      printf '  %s\n' "${surface_prefix_candidates[@]}"
      echo "Set CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX explicitly."
      exit 2
      ;;
  esac
fi
CRAWLING_SEED_FC_FLAT_SURFACE_SUBJECT_PREFIX="${CRAWLING_SEED_FC_FLAT_SURFACE_SUBJECT_PREFIX:-${CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX}}"

for hemi in L R; do
  for surf in inflated midthickness pial very_inflated white; do
    surface_file="${CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR}/${CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX}.${hemi}.${surf}.32k_fs_LR.surf.gii"
    [[ -f "$surface_file" ]] || {
      echo "ERROR: missing crawling seed FC surface: $surface_file"
      echo "AtlasSpace=${CRAWLING_SEED_FC_ATLAS_SPACE}; set CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR explicitly to use another surface set."
      exit 2
    }
  done
  for surf in flat sphere; do
    surface_file="${CRAWLING_SEED_FC_FLAT_SURFACE_RESOURCE_DIR:-$CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR}/${CRAWLING_SEED_FC_FLAT_SURFACE_SUBJECT_PREFIX}.${hemi}.${surf}.32k_fs_LR.surf.gii"
    [[ -f "$surface_file" ]] || {
      echo "ERROR: missing crawling seed FC flat/sphere surface: $surface_file"
      echo "AtlasSpace=${CRAWLING_SEED_FC_ATLAS_SPACE}; set CRAWLING_SEED_FC_FLAT_SURFACE_RESOURCE_DIR explicitly if flatmaps are stored elsewhere."
      exit 2
    }
  done
done

ARGS=(
  --dtseries "$CRAWLING_SEED_FC_INPUT_CIFTI"
  --subject "$CRAWLING_SEED_FC_SUBJECT"
  --out-dir "$CRAWLING_SEED_FC_OUTDIR"
  --scene-template "$CRAWLING_SEED_FC_SCENE_TEMPLATE"
  --vertices "$CRAWLING_SEED_FC_VERTICES"
  --template-subject "$CRAWLING_SEED_FC_TEMPLATE_SUBJECT"
  --wb-command "$CRAWLING_SEED_FC_WB_COMMAND"
  --vertex-mode "$CRAWLING_SEED_FC_VERTEX_MODE"
  --width "$CRAWLING_SEED_FC_WIDTH"
  --height "$CRAWLING_SEED_FC_HEIGHT"
  --framerate "$CRAWLING_SEED_FC_FRAMERATE"
  --num-cpus "$CRAWLING_SEED_FC_NUM_CPUS"
  --target-size-mb "$CRAWLING_SEED_FC_TARGET_SIZE_MB"
  --ffmpeg-bin "$CRAWLING_SEED_FC_FFMPEG"
  --ffprobe-bin "$CRAWLING_SEED_FC_FFPROBE"
)

[[ -n "$CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR" ]] && ARGS+=( --surface-resource-dir "$CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR" )
[[ -n "$CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX" ]] && ARGS+=( --surface-subject-prefix "$CRAWLING_SEED_FC_SURFACE_SUBJECT_PREFIX" )
[[ -n "$CRAWLING_SEED_FC_FLAT_SURFACE_RESOURCE_DIR" ]] && ARGS+=( --flat-surface-resource-dir "$CRAWLING_SEED_FC_FLAT_SURFACE_RESOURCE_DIR" )
[[ -n "$CRAWLING_SEED_FC_FLAT_SURFACE_SUBJECT_PREFIX" ]] && ARGS+=( --flat-surface-subject-prefix "$CRAWLING_SEED_FC_FLAT_SURFACE_SUBJECT_PREFIX" )
if [[ -n "$CRAWLING_SEED_FC_WB_SURFER2" ]]; then
  ARGS+=( --wbsurfer-bin "$CRAWLING_SEED_FC_WB_SURFER2" )
elif [[ -n "$CRAWLING_SEED_FC_WB_SURFER2_CONDA_ENV" ]]; then
  ARGS+=( --wbsurfer-conda-env "$CRAWLING_SEED_FC_WB_SURFER2_CONDA_ENV" )
fi
[[ "$CRAWLING_SEED_FC_FORCE" == "1" ]] && ARGS+=( --force )
[[ "$CRAWLING_SEED_FC_FORCE_DCONN" == "1" ]] && ARGS+=( --force-dconn )
[[ "$CRAWLING_SEED_FC_SKIP_MOVIE" == "1" ]] && ARGS+=( --skip-movie )
[[ "$CRAWLING_SEED_FC_KEEP_SOURCE_MOVIE" == "1" ]] && ARGS+=( --keep-source-movie )
[[ "$CRAWLING_SEED_FC_KEEP_DCONN" == "1" ]] && ARGS+=( --keep-dconn )
[[ "$CRAWLING_SEED_FC_COPY_DTSERIES" == "1" ]] && ARGS+=( --copy-dtseries )

echo "[crawling_seed_fc] input=${CRAWLING_SEED_FC_INPUT_CIFTI}"
echo "[crawling_seed_fc] outdir=${CRAWLING_SEED_FC_OUTDIR}"
echo "[crawling_seed_fc] subject=${CRAWLING_SEED_FC_SUBJECT}"
echo "[crawling_seed_fc] render_cpus=${CRAWLING_SEED_FC_NUM_CPUS} (requested=${CRAWLING_SEED_FC_NUM_CPUS_REQUESTED}, safety_cap=${CRAWLING_SEED_FC_MAX_CPUS})"
if [[ -n "$CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR" ]]; then
  echo "[crawling_seed_fc] surface_dir=${CRAWLING_SEED_FC_SURFACE_RESOURCE_DIR}"
fi
if [[ -n "$CRAWLING_SEED_FC_FLAT_SURFACE_RESOURCE_DIR" ]]; then
  echo "[crawling_seed_fc] flat_surface_dir=${CRAWLING_SEED_FC_FLAT_SURFACE_RESOURCE_DIR}"
fi
"$CRAWLING_SEED_FC_PYTHON" "$MEDIR/lib/crawling_seed_fc_movie.py" "${ARGS[@]}"
echo "[crawling_seed_fc] complete"
