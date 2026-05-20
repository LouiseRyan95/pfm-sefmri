#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "Usage: $0 <SubjectDir> [ConfigFile]"
  echo "Example: $0 /path/to/study/ME01"
  exit 2
fi

SubjectDir="$1"
ConfigFileArg="${2:-}"

if [ "${SubjectDir: -1}" = "/" ]; then
  SubjectDir="${SubjectDir%?}"
fi
if [ ! -d "$SubjectDir" ]; then
  echo "ERROR: subject directory does not exist: $SubjectDir"
  exit 2
fi

Subject="$(basename "$SubjectDir")"
StudyFolder="$(dirname "$SubjectDir")"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_CONFIG="$SCRIPT_DIR/../config/mefmri_wrapper_config.sh"
ConfigFile="${ConfigFileArg:-${CONFIG_FILE:-$DEFAULT_CONFIG}}"

if [ ! -f "$ConfigFile" ]; then
  echo "ERROR: missing config file: $ConfigFile"
  exit 2
fi

set -a
source "$ConfigFile"
set +a

if [[ -n "${PIPELINE_TASK_OVERRIDE:-}" ]]; then
  FUNC_DIRNAME="$PIPELINE_TASK_OVERRIDE"
fi
if [[ -n "${PIPELINE_TASK_XFMS_OVERRIDE:-}" ]]; then
  FUNC_XFMS_DIRNAME="$PIPELINE_TASK_XFMS_OVERRIDE"
fi

# Optional config-specified FreeSurfer license path.
if [[ -n "${FS_LICENSE_FILE:-}" ]]; then
  export FS_LICENSE="$FS_LICENSE_FILE"
fi

# Core paths and wrapper controls.
: "${MEDIR:=$(cd "$SCRIPT_DIR/.." && pwd)}"
: "${EnvironmentScript:=$MEDIR/HCPpipelines-master/Examples/Scripts/SetUpHCPPipeline.sh}"
: "${START_SESSION:=1}"
: "${START_FROM_MODULE:=validate}" # validate|anat_hcp|anat_charm|fieldmaps|coreg|headmotion|meica|mgtr|vol2surf|concat|nsi|pfm
: "${STOP_AFTER_MODULE:=}" # validate|anat_hcp|anat_charm|fieldmaps|coreg|headmotion|meica|mgtr|vol2surf|concat|nsi|pfm
: "${PIPELINE_SKIP_ANAT:=0}" # 0|1 (used by FUNC_DIRNAME=All parent loop to avoid rerunning anatomy per task)

# Optional post-config overrides (used internally by the All-tasks driver).
: "${PIPELINE_START_FROM_MODULE_OVERRIDE:=}"
: "${PIPELINE_STOP_AFTER_MODULE_OVERRIDE:=}"

# Module entrypoints.
: "${VALIDATE_MODULE:=$MEDIR/modules/mefmri_validate_inputs.sh}"
: "${ANAT_HCP_MODULE:=$MEDIR/modules/mefmri_anat_hcp.sh}"
: "${ANAT_CHARM_MODULE:=$MEDIR/modules/mefmri_anat_charm.sh}"
: "${FUNC_FIELDMAPS_MODULE:=$MEDIR/modules/mefmri_func_fieldmaps.sh}"
: "${FUNC_COREG_MODULE:=$MEDIR/modules/mefmri_func_coreg.sh}"
: "${FUNC_HEADMOTION_MODULE:=$MEDIR/modules/mefmri_func_headmotion.sh}"
: "${FUNC_MEICA_MODULE:=$MEDIR/modules/mefmri_func_meica.sh}"
: "${FUNC_SINGLEECHO_MODULE:=$MEDIR/modules/mefmri_func_singleecho.sh}"
: "${FUNC_AROMA_MODULE:=$MEDIR/modules/mefmri_func_aroma.sh}"
: "${FUNC_MGTR_MODULE:=$MEDIR/modules/mefmri_func_mgtr.sh}"
: "${FUNC_VOL2SURF_MODULE:=$MEDIR/modules/mefmri_func_vol2surf.sh}"
: "${FUNC_CONCAT_MODULE:=$MEDIR/modules/mefmri_func_concat.sh}"
: "${FUNC_NSI_MODULE:=$MEDIR/modules/mefmri_func_nsi.sh}"
: "${FUNC_PFM_MODULE:=$MEDIR/modules/mefmri_func_pfm.sh}"

# Global processing knobs.
: "${CHARM_BIN:=}" # optional explicit path passed to CHARM module
: "${DOF:=6}"
: "${AtlasTemplate:=$MEDIR/res0urces/MNI152_T1_2mm.nii.gz}"
: "${AtlasSpace:=T1w}"
: "${MEPCA:=kundu}"
: "${MaxIterations:=500}"
: "${MaxRestarts:=5}"
: "${CONCAT_ENABLE:=1}" # 0|1
: "${NSI_ENABLE:=1}" # 0|1
: "${PFM_ENABLE:=1}" # 0|1
: "${RUN_CONFIG_SNAPSHOT:=1}" # 0|1
: "${FUNC_NOFIELDMAP_MODE:=0}" # 0|1
: "${PROCESSING_MODE:=auto}" # auto|multi_echo|single_echo
: "${MULTI_ECHO_DENOISE_METHOD:=meica}" # meica|aroma|acompcor
: "${SINGLE_ECHO_DENOISE_METHOD:=acompcor}" # aroma|acompcor
: "${SINGLE_ECHO_ECHO_INDEX:=1}"
: "${AROMA_NSI_THRESHOLD:=0.05}"

# Functional naming/outputs.
: "${VOL2SURF_INPUTS:=}"
: "${FUNC_DIRNAME:=rest}"
: "${FUNC_FILE_PREFIX:=Rest}"
: "${PIPELINE_TASK_LOOP_CHILD:=0}"
if [[ -z "${FUNC_XFMS_DIRNAME:-}" ]]; then
  FUNC_XFMS_DIRNAME="$FUNC_DIRNAME"
fi
: "${MGTR_INPUT_TAG:=}"
: "${MGTR_OUTPUT_TAG:=}"
: "${PIPELINE_SOURCE_FUNC_TAG:=}"

# Module-specific thread controls.
: "${THREADS_DEFAULT:=8}"
: "${THREADS_ANAT_HCP:=$THREADS_DEFAULT}"
: "${THREADS_FIELDMAPS:=$THREADS_DEFAULT}"
: "${THREADS_COREG:=$THREADS_DEFAULT}"
: "${THREADS_HEADMOTION:=$THREADS_DEFAULT}"
: "${THREADS_MEICA:=$THREADS_DEFAULT}"
: "${PIPELINE_QUIET_MODULE_OUTPUT:=1}" # 0|1
: "${PIPELINE_LOG_TAIL_LINES:=40}"

stage_index() {
  case "$1" in
    validate) echo 5 ;;
    anat_hcp) echo 10 ;;
    anat_charm) echo 20 ;;
    fieldmaps) echo 30 ;;
    coreg) echo 40 ;;
    headmotion) echo 50 ;;
    meica) echo 60 ;;
    mgtr) echo 70 ;;
    vol2surf) echo 80 ;;
    concat) echo 90 ;;
    nsi) echo 100 ;;
    pfm) echo 110 ;;
    *)
      echo "ERROR: invalid module tag: $1" >&2
      return 1
      ;;
  esac
}

should_run_stage() {
  local stage="$1"
  local start_idx stage_idx
  start_idx="$(stage_index "$START_FROM_MODULE")" || return 1
  stage_idx="$(stage_index "$stage")" || return 1
  [ "$stage_idx" -ge "$start_idx" ]
}

is_all_task_selection() {
  local value="${1:-}"
  [[ "${value,,}" == "all" ]]
}

discover_task_dirs() {
  local root task_dir task
  declare -A seen=()
  for root in "$SubjectDir/func" "$SubjectDir/func/unprocessed"; do
    [[ -d "$root" ]] || continue
    while IFS= read -r task_dir; do
      task="$(basename "$task_dir")"
      [[ -n "$task" ]] || continue
      [[ -n "${seen[$task]:-}" ]] && continue
      compgen -G "$task_dir/session_*" > /dev/null || continue
      seen["$task"]=1
      printf '%s\n' "$task"
    done < <(find "$root" -mindepth 1 -maxdepth 1 -type d | sort -V)
  done
}

run_all_tasks() {
  local -a tasks=()
  local task rc=0
  mapfile -t tasks < <(discover_task_dirs)
  if [[ "${#tasks[@]}" -eq 0 ]]; then
    echo "ERROR: FUNC_DIRNAME=All but no task directories were found under $SubjectDir/func or $SubjectDir/func/unprocessed" >&2
    exit 2
  fi

  echo "Task selection: All"
  printf 'Discovered tasks (%d): %s\n' "${#tasks[@]}" "$(IFS=,; echo "${tasks[*]}")"

  local start_idx stop_idx
  local validate_idx anat_hcp_idx anat_charm_idx
  validate_idx="$(stage_index "validate")"
  anat_hcp_idx="$(stage_index "anat_hcp")"
  anat_charm_idx="$(stage_index "anat_charm")"

  start_idx="$(stage_index "$START_FROM_MODULE")" || exit 2
  if [[ -n "${STOP_AFTER_MODULE:-}" ]]; then
    stop_idx="$(stage_index "$STOP_AFTER_MODULE")" || exit 2
  else
    stop_idx=999999
  fi

  local needs_anat=0
  if (( start_idx <= anat_charm_idx && stop_idx >= anat_hcp_idx )); then
    needs_anat=1
  fi

  # Run shared (subject-level) anatomy once, then run per-task modules in child invocations.
  if (( needs_anat )); then
    local global_start="$START_FROM_MODULE"
    local global_stop="anat_charm"

    # Never run validate in the global/anat pass; validate is per-task.
    if (( start_idx <= validate_idx )); then
      global_start="anat_hcp"
    fi
    if (( start_idx > validate_idx && start_idx < anat_hcp_idx )); then
      global_start="anat_hcp"
    fi

    if (( stop_idx <= anat_charm_idx )); then
      global_stop="$STOP_AFTER_MODULE"
    fi

    echo
    echo "[task-loop] running anatomy once (start=${global_start} stop=${global_stop})"
    set +e
    env \
      PIPELINE_TASK_LOOP_CHILD=1 \
      PIPELINE_TASK_OVERRIDE="${tasks[0]}" \
      PIPELINE_TASK_XFMS_OVERRIDE="${tasks[0]}" \
      PIPELINE_SKIP_ANAT=0 \
      PIPELINE_START_FROM_MODULE_OVERRIDE="$global_start" \
      PIPELINE_STOP_AFTER_MODULE_OVERRIDE="$global_stop" \
      bash "$0" "$SubjectDir" "$ConfigFile"
    rc=$?
    set -e
    if [[ "$rc" -ne 0 ]]; then
      echo "[task-loop] FAILED anatomy pass exit=${rc}" >&2
      exit "$rc"
    fi

    if [[ -n "${STOP_AFTER_MODULE:-}" ]] && (( stop_idx <= anat_charm_idx )); then
      echo "[task-loop] stopping after ${STOP_AFTER_MODULE} (global stage); not running per-task modules"
      exit 0
    fi
  fi

  for task in "${tasks[@]}"; do
    echo
    echo "[task-loop] starting task=${task}"
    set +e
    env \
      PIPELINE_TASK_LOOP_CHILD=1 \
      PIPELINE_TASK_OVERRIDE="$task" \
      PIPELINE_TASK_XFMS_OVERRIDE="$task" \
      PIPELINE_SKIP_ANAT=1 \
      bash "$0" "$SubjectDir" "$ConfigFile"
    rc=$?
    set -e
    if [[ "$rc" -ne 0 ]]; then
      echo "[task-loop] FAILED task=${task} exit=${rc}" >&2
      exit "$rc"
    fi
    echo "[task-loop] complete task=${task}"
  done
  exit 0
}

if is_all_task_selection "$FUNC_DIRNAME" && [[ "$PIPELINE_TASK_LOOP_CHILD" != "1" ]]; then
  run_all_tasks
fi

# Apply optional post-config overrides.
if [[ -n "${PIPELINE_START_FROM_MODULE_OVERRIDE:-}" ]]; then
  START_FROM_MODULE="${PIPELINE_START_FROM_MODULE_OVERRIDE}"
fi
if [[ -n "${PIPELINE_STOP_AFTER_MODULE_OVERRIDE:-}" ]]; then
  STOP_AFTER_MODULE="${PIPELINE_STOP_AFTER_MODULE_OVERRIDE}"
fi

if [ ! -f "$EnvironmentScript" ]; then
  echo "ERROR: missing environment setup script: $EnvironmentScript"
  exit 2
fi
source "$EnvironmentScript"

ensure_tkregister_compat() {
  if command -v tkregister >/dev/null 2>&1; then
    return 0
  fi
  local tkregister2_bin
  if ! tkregister2_bin="$(command -v tkregister2 2>/dev/null)"; then
    echo "ERROR: required command 'tkregister' is missing and fallback 'tkregister2' was not found." >&2
    return 1
  fi
  local shim_dir="${TMPDIR:-/tmp}/mefmri_compat_bin"
  mkdir -p "$shim_dir"
  cat > "${shim_dir}/tkregister" <<EOF
#!/usr/bin/env bash
exec "${tkregister2_bin}" "\$@"
EOF
  chmod +x "${shim_dir}/tkregister"
  export PATH="${shim_dir}:${PATH}"
  echo "INFO: Installed tkregister compatibility shim -> ${tkregister2_bin}"
}

ensure_tkregister_compat

resolve_freesurfer_license() {
  if [[ -n "${FS_LICENSE:-}" && -f "${FS_LICENSE}" ]]; then
    echo "${FS_LICENSE}"
    return 0
  fi
  if [[ -n "${FS_LICENSE_FILE:-}" && -f "${FS_LICENSE_FILE}" ]]; then
    echo "${FS_LICENSE_FILE}"
    return 0
  fi
  if [[ -n "${FREESURFER_HOME:-}" && -f "${FREESURFER_HOME}/license.txt" ]]; then
    echo "${FREESURFER_HOME}/license.txt"
    return 0
  fi
  return 1
}

# Anatomical HCP/FreeSurfer stages require a valid license file.
if should_run_stage "anat_hcp" && [[ "${PIPELINE_SKIP_ANAT}" != "1" ]]; then
  if ! FS_LICENSE_EFFECTIVE="$(resolve_freesurfer_license)"; then
    echo "ERROR: FreeSurfer license not found." >&2
    echo "Set FS_LICENSE or FS_LICENSE_FILE to a readable license.txt path." >&2
    exit 2
  fi
  export FS_LICENSE="${FS_LICENSE_EFFECTIVE}"
fi

case "${AtlasSpace}" in
  T1w|t1w|Tlw|tlw) AtlasSpace="T1w" ;;
  MNINonlinear|mni|MNI|mninonlinear) AtlasSpace="MNINonlinear" ;;
  *)
    echo "ERROR: invalid AtlasSpace='$AtlasSpace' (supported: T1w or MNINonlinear)"
    exit 2
    ;;
esac

case "${PIPELINE_QUIET_MODULE_OUTPUT}" in
  0|1) ;;
  *)
    echo "ERROR: invalid PIPELINE_QUIET_MODULE_OUTPUT='${PIPELINE_QUIET_MODULE_OUTPUT}' (expected 0 or 1)"
    exit 2
    ;;
esac

case "${PROCESSING_MODE}" in
  auto|multi_echo|single_echo) ;;
  *)
    echo "ERROR: invalid PROCESSING_MODE='${PROCESSING_MODE}' (expected auto, multi_echo, or single_echo)"
    exit 2
    ;;
esac

case "${SINGLE_ECHO_DENOISE_METHOD}" in
  aroma|acompcor) ;;
  *)
    echo "ERROR: invalid SINGLE_ECHO_DENOISE_METHOD='${SINGLE_ECHO_DENOISE_METHOD}' (expected aroma or acompcor)"
    exit 2
    ;;
esac

case "${MULTI_ECHO_DENOISE_METHOD}" in
  meica|aroma|acompcor) ;;
  *)
    echo "ERROR: invalid MULTI_ECHO_DENOISE_METHOD='${MULTI_ECHO_DENOISE_METHOD}' (expected meica, aroma, or acompcor)"
    exit 2
    ;;
esac

if ! [[ "${SINGLE_ECHO_ECHO_INDEX}" =~ ^[0-9]+$ ]] || [[ "${SINGLE_ECHO_ECHO_INDEX}" -lt 1 ]]; then
  echo "ERROR: SINGLE_ECHO_ECHO_INDEX must be an integer >= 1 (got '${SINGLE_ECHO_ECHO_INDEX}')"
  exit 2
fi

detect_run_echo_count() {
  local run_dir="$1"
  local te_file
  for te_file in "$run_dir/TE.txt" "$run_dir/te.txt"; do
    if [[ -f "$te_file" ]]; then
      awk 'NF{print NF; exit}' "$te_file"
      return 0
    fi
  done

  local count=0
  shopt -s nullglob
  local matches=( "$run_dir"/"${FUNC_FILE_PREFIX}"*_E*.nii.gz )
  shopt -u nullglob
  local f base
  count=0
  for f in "${matches[@]}"; do
    base="$(basename "$f")"
    if [[ "$base" =~ ^${FUNC_FILE_PREFIX}.*_E[0-9]+(_acpc)?\.nii\.gz$ ]]; then
      count=$((count + 1))
    fi
  done
  if [[ "$count" -gt 0 ]]; then
    echo "$count"
    return 0
  fi

  echo ""
}

detect_dataset_min_echoes() {
  local -a roots=(
    "$SubjectDir/func/$FUNC_DIRNAME"
    "$SubjectDir/func/unprocessed/$FUNC_DIRNAME"
  )
  local root run_dir count min_count=""
  for root in "${roots[@]}"; do
    [[ -d "$root" ]] || continue
    while IFS= read -r run_dir; do
      count="$(detect_run_echo_count "$run_dir")"
      [[ -n "$count" ]] || continue
      if [[ -z "$min_count" || "$count" -lt "$min_count" ]]; then
        min_count="$count"
      fi
    done < <(find "$root" -mindepth 2 -maxdepth 2 -type d -name 'run_*' | sort -V)
  done
  if [[ -z "$min_count" ]]; then
    echo "0"
  else
    echo "$min_count"
  fi
}

PIPELINE_MIN_ECHOES="$(detect_dataset_min_echoes)"
PIPELINE_DENOISE_FALLBACK_REASON=""
PIPELINE_EFFECTIVE_DENOISE_MODE="multi_echo"
if [[ "${PROCESSING_MODE}" == "single_echo" ]]; then
  PIPELINE_EFFECTIVE_DENOISE_MODE="single_echo"
  PIPELINE_DENOISE_FALLBACK_REASON="explicit_single_echo"
elif [[ "${PIPELINE_MIN_ECHOES}" -lt 3 ]]; then
  PIPELINE_EFFECTIVE_DENOISE_MODE="single_echo"
  PIPELINE_DENOISE_FALLBACK_REASON="echo_count_lt_3"
fi

PIPELINE_SOURCE_FUNC_TAG="OCME"
PIPELINE_EFFECTIVE_DENOISE_METHOD="$MULTI_ECHO_DENOISE_METHOD"
PIPELINE_DENOISE_OUTPUT_TAG="OCME+MEICA"
if [[ "${PIPELINE_EFFECTIVE_DENOISE_MODE}" == "single_echo" ]]; then
  PIPELINE_SOURCE_FUNC_TAG="E${SINGLE_ECHO_ECHO_INDEX}"
  PIPELINE_EFFECTIVE_DENOISE_METHOD="$SINGLE_ECHO_DENOISE_METHOD"
  if [[ "${SINGLE_ECHO_DENOISE_METHOD}" == "aroma" ]]; then
    PIPELINE_DENOISE_OUTPUT_TAG="${PIPELINE_SOURCE_FUNC_TAG}+AROMA"
  else
    PIPELINE_DENOISE_OUTPUT_TAG="${PIPELINE_SOURCE_FUNC_TAG}+aCompCor"
  fi
else
  case "${MULTI_ECHO_DENOISE_METHOD}" in
    meica)
      PIPELINE_DENOISE_OUTPUT_TAG="OCME+MEICA"
      ;;
    aroma)
      PIPELINE_DENOISE_OUTPUT_TAG="OCME+AROMA"
      ;;
    acompcor)
      PIPELINE_DENOISE_OUTPUT_TAG="OCME+aCompCor"
      ;;
  esac
fi
PIPELINE_MGTR_OUTPUT_TAG_DEFAULT="${PIPELINE_DENOISE_OUTPUT_TAG}+MGTR"
: "${MGTR_INPUT_TAG:=$PIPELINE_DENOISE_OUTPUT_TAG}"
: "${MGTR_OUTPUT_TAG:=$PIPELINE_MGTR_OUTPUT_TAG_DEFAULT}"
if [[ -z "${VOL2SURF_INPUTS}" ]]; then
  VOL2SURF_INPUTS="${PIPELINE_SOURCE_FUNC_TAG},${PIPELINE_DENOISE_OUTPUT_TAG},${MGTR_OUTPUT_TAG}"
fi
: "${CONCAT_INPUT_TAG:=$MGTR_OUTPUT_TAG}"
: "${NSI_INPUT_TAG:=$CONCAT_INPUT_TAG}"
: "${PFM_INPUT_TAG:=$CONCAT_INPUT_TAG}"

export PIPELINE_MIN_ECHOES
export PIPELINE_EFFECTIVE_DENOISE_MODE
export PIPELINE_DENOISE_FALLBACK_REASON
export PIPELINE_DENOISE_OUTPUT_TAG
export PIPELINE_SOURCE_FUNC_TAG
export PIPELINE_EFFECTIVE_DENOISE_METHOD
export MGTR_INPUT_TAG
export MGTR_OUTPUT_TAG

echo
echo "ME-fMRI Pipeline"
echo "MEDIR: ${MEDIR}"
echo "SubjectDir: ${SubjectDir}"
echo "Subject: ${Subject}"
echo "StudyFolder: ${StudyFolder}"
echo "START_SESSION: ${START_SESSION}"
echo "START_FROM_MODULE: ${START_FROM_MODULE}"
echo "STOP_AFTER_MODULE: ${STOP_AFTER_MODULE:-<none>}"
echo "AtlasSpace: ${AtlasSpace}"
echo "Task loop child: ${PIPELINE_TASK_LOOP_CHILD}"
echo "Skip anatomy: ${PIPELINE_SKIP_ANAT}"
echo "Functional naming: func/${FUNC_DIRNAME}, prefix ${FUNC_FILE_PREFIX}_*"
echo "Functional xfm namespace: func/xfms/${FUNC_XFMS_DIRNAME}"
echo "FUNC_NOFIELDMAP_MODE: ${FUNC_NOFIELDMAP_MODE}"
echo "Processing mode: requested=${PROCESSING_MODE} effective=${PIPELINE_EFFECTIVE_DENOISE_MODE} min_echoes=${PIPELINE_MIN_ECHOES}"
if [[ "${PIPELINE_EFFECTIVE_DENOISE_MODE}" == "single_echo" ]]; then
  echo "Single-echo denoise method: ${SINGLE_ECHO_DENOISE_METHOD} (source echo E${SINGLE_ECHO_ECHO_INDEX})"
  if [[ -n "${PIPELINE_DENOISE_FALLBACK_REASON}" ]]; then
    echo "Single-echo selection reason: ${PIPELINE_DENOISE_FALLBACK_REASON}"
  fi
else
  echo "Multi-echo denoise method: ${MULTI_ECHO_DENOISE_METHOD}"
fi
echo "Threads (anat_hcp,fieldmaps,coreg,headmotion,meica): ${THREADS_ANAT_HCP},${THREADS_FIELDMAPS},${THREADS_COREG},${THREADS_HEADMOTION},${THREADS_MEICA}"
echo "MEICA defaults: tedana_env=${TEDANA_ENV:-unset}, compat=${TEDANA_COMPAT_MODE:-unset}, pca=${MEPCA}"
echo "Masking defaults: CHARM_BRAIN_MASK_MODE=${CHARM_BRAIN_MASK_MODE:-unset}, VOL2SURF_USE_CORTICAL_RIBBON_MASK=${VOL2SURF_USE_CORTICAL_RIBBON_MASK:-unset}, VOL2SURF_USE_GOOD_VOXELS_MASK=${VOL2SURF_USE_GOOD_VOXELS_MASK:-${VOL2SURF_USE_GOOD_VOXELS_MASK_FINAL:-unset}}"
echo "Reclass defaults: mode=${MEICA_CLASSIFIER_MODE:-unset}, nsi_kill=${MEICA_NSI_KILL_MODE:-unset}, reports_disabled=${MEICA_RECLASS_NO_REPORTS:-unset}"
echo "Module output mode: quiet=${PIPELINE_QUIET_MODULE_OUTPUT}"

MODULE_LOG_DIR="$SubjectDir/func/qa/ModuleLogs"
mkdir -p "$MODULE_LOG_DIR"

run_module() {
  local module="$1"
  shift

  if [[ "${PIPELINE_QUIET_MODULE_OUTPUT}" == "0" ]]; then
    "$@"
    return $?
  fi

  # Some stages share the same pipeline "module tag" for scheduling
  # (e.g., single-echo aCompCor runs under the historical "meica" stage).
  # Allow callers to override the user-facing label and logfile suffix without
  # changing scheduling semantics.
  local display_tag log_tag
  display_tag="${MODULE_DISPLAY_TAG:-$module}"
  log_tag="${MODULE_LOG_TAG:-$module}"

  local ts logfile rc
  ts="$(date +%Y%m%d_%H%M%S)"
  logfile="$MODULE_LOG_DIR/${ts}_${log_tag}.log"
  echo "[$display_tag] log: $logfile"

  # Always capture complete output to log; only stream high-level markers to terminal.
  set +e
  "$@" 2>&1 | awk -v logfile_path="$logfile" '
    {
      print >> logfile_path
      fflush(logfile_path)
      if ($0 ~ /^\[(concat|nsi|pfm)\] complete$/) {
        next
      }
      if ($0 ~ /^\[coreg\]/ || $0 ~ /^\[headmotion\]/ || $0 ~ /^\[concat\]/ || $0 ~ /^\[nsi\]/ || $0 ~ /^\[pfm\]/ ||
          $0 ~ /^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\] MEICA: start subject=/ ||
          $0 ~ /^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\] MEICA: start session_/ ||
          $0 ~ /^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\] MEICA: done session_/ ||
          $0 ~ /^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\] MEICA: all done subject=/) {
        print
      }
    }
  '
  rc=${PIPESTATUS[0]}
  set -e

  if [[ "$rc" -ne 0 ]]; then
    echo "[$display_tag] FAILED (exit $rc). Log: $logfile" >&2
    echo "[$display_tag] error summary:" >&2
    if ! tail -n 400 "$logfile" | awk '
      /Traceback \(most recent call last\):/ ||
      /^ERROR:/ ||
      /FileNotFoundError:/ ||
      /Exception:/ ||
      /FAILED/ ||
      /can'\''t open file/ { print; found=1 }
      END { exit(found?0:1) }
    ' >&2; then
      echo "[$display_tag] (no explicit traceback/error markers found; showing last ${PIPELINE_LOG_TAIL_LINES} lines)" >&2
      tail -n "$PIPELINE_LOG_TAIL_LINES" "$logfile" >&2 || true
    fi
    return "$rc"
  fi

  echo "[$display_tag] complete"
}

print_section() {
  local title="$1"
  echo
  echo "$title"
}

if [[ "${RUN_CONFIG_SNAPSHOT}" == "1" ]]; then
  RUN_META_DIR="$SubjectDir/func/qa/RunMetadata"
  mkdir -p "$RUN_META_DIR"
  RUN_META_FILE="$RUN_META_DIR/pipeline_run_$(date +%Y%m%d_%H%M%S).txt"
  {
    echo "date=$(date --iso-8601=seconds)"
    echo "subject_dir=$SubjectDir"
    echo "config_file=$ConfigFile"
    echo "start_from_module=$START_FROM_MODULE"
    echo "stop_after_module=${STOP_AFTER_MODULE:-}"
    echo "atlas_space=$AtlasSpace"
    echo "task_loop_child=$PIPELINE_TASK_LOOP_CHILD"
    echo "func_dirname=$FUNC_DIRNAME"
    echo "func_file_prefix=$FUNC_FILE_PREFIX"
    echo "func_xfms_dirname=$FUNC_XFMS_DIRNAME"
    echo "processing_mode_requested=${PROCESSING_MODE}"
    echo "processing_mode_effective=${PIPELINE_EFFECTIVE_DENOISE_MODE}"
    echo "processing_mode_reason=${PIPELINE_DENOISE_FALLBACK_REASON}"
    echo "min_echoes=${PIPELINE_MIN_ECHOES}"
    echo "single_echo_method=${SINGLE_ECHO_DENOISE_METHOD}"
    echo "multi_echo_method=${MULTI_ECHO_DENOISE_METHOD}"
    echo "single_echo_echo_index=${SINGLE_ECHO_ECHO_INDEX}"
    echo "aroma_nsi_threshold=${AROMA_NSI_THRESHOLD}"
    echo "pipeline_source_func_tag=${PIPELINE_SOURCE_FUNC_TAG}"
    echo "pipeline_denoise_output_tag=${PIPELINE_DENOISE_OUTPUT_TAG}"
    echo "pipeline_effective_denoise_method=${PIPELINE_EFFECTIVE_DENOISE_METHOD}"
    echo "mgtr_input_tag=${MGTR_INPUT_TAG}"
    echo "mgtr_output_tag=${MGTR_OUTPUT_TAG}"
    echo "concat_input_tag=${CONCAT_INPUT_TAG:-}"
    echo "nsi_input_tag=${NSI_INPUT_TAG:-}"
    echo "pfm_input_tag=${PFM_INPUT_TAG:-}"
    echo "charm_brain_mask_mode=${CHARM_BRAIN_MASK_MODE:-}"
    echo "vol2surf_use_cortical_ribbon_mask=${VOL2SURF_USE_CORTICAL_RIBBON_MASK:-}"
    echo "vol2surf_use_good_voxels_mask=${VOL2SURF_USE_GOOD_VOXELS_MASK:-${VOL2SURF_USE_GOOD_VOXELS_MASK_FINAL:-}}"
    echo "vol2surf_good_voxels_factor=${VOL2SURF_GOOD_VOXELS_FACTOR:-}"
    echo "vol2surf_good_voxels_sigma_mm=${VOL2SURF_GOOD_VOXELS_SIGMA_MM:-}"
    echo "vol2surf_good_voxels_keep_intermediates=${VOL2SURF_GOOD_VOXELS_KEEP_INTERMEDIATES:-}"
    echo "tedana_env=${TEDANA_ENV:-}"
    echo "tedana_compat_mode=${TEDANA_COMPAT_MODE:-}"
    echo "mepca=$MEPCA"
    echo "meica_classifier_mode=${MEICA_CLASSIFIER_MODE:-}"
    echo "meica_nsi_kill_mode=${MEICA_NSI_KILL_MODE:-}"
    echo "meica_reclass_no_reports=${MEICA_RECLASS_NO_REPORTS:-}"
    echo "concat_enable=${CONCAT_ENABLE}"
    echo "nsi_enable=${NSI_ENABLE}"
    echo "pfm_enable=${PFM_ENABLE}"
  } > "$RUN_META_FILE"
  echo "Run metadata snapshot: $RUN_META_FILE"
fi

print_section "Running input validation"
if should_run_stage "validate"; then
  [ -f "$VALIDATE_MODULE" ] || { echo "ERROR: missing module: $VALIDATE_MODULE"; exit 2; }
  run_module "validate" bash "$VALIDATE_MODULE" "$SubjectDir" "$FUNC_DIRNAME" "$FUNC_FILE_PREFIX" "$START_SESSION"
  if [[ "$STOP_AFTER_MODULE" == "validate" ]]; then
    echo "Stopping after validate (STOP_AFTER_MODULE=validate)"
    exit 0
  fi
else
  echo "Skipping validate (START_FROM_MODULE=${START_FROM_MODULE})"
fi

print_section "Running anatomical modules"
if should_run_stage "anat_hcp"; then
  if [[ "${PIPELINE_SKIP_ANAT}" == "1" ]]; then
    echo "Skipping anat_hcp (PIPELINE_SKIP_ANAT=1)"
  else
    [ -f "$ANAT_HCP_MODULE" ] || { echo "ERROR: missing module: $ANAT_HCP_MODULE"; exit 2; }
    run_module "anat_hcp" bash "$ANAT_HCP_MODULE" "$StudyFolder" "$Subject" "$THREADS_ANAT_HCP"
  fi
  if [[ "$STOP_AFTER_MODULE" == "anat_hcp" ]]; then
    echo "Stopping after anat_hcp (STOP_AFTER_MODULE=anat_hcp)"
    exit 0
  fi
else
  echo "Skipping anat_hcp (START_FROM_MODULE=${START_FROM_MODULE})"
fi
if should_run_stage "anat_charm"; then
  if [[ "${PIPELINE_SKIP_ANAT}" == "1" ]]; then
    echo "Skipping anat_charm (PIPELINE_SKIP_ANAT=1)"
  else
    [ -f "$ANAT_CHARM_MODULE" ] || { echo "ERROR: missing module: $ANAT_CHARM_MODULE"; exit 2; }
    if [ -n "$CHARM_BIN" ]; then
      run_module "anat_charm" bash "$ANAT_CHARM_MODULE" "$StudyFolder" "$Subject" "$CHARM_BIN"
    else
      run_module "anat_charm" bash "$ANAT_CHARM_MODULE" "$StudyFolder" "$Subject"
    fi
  fi
  if [[ "$STOP_AFTER_MODULE" == "anat_charm" ]]; then
    echo "Stopping after anat_charm (STOP_AFTER_MODULE=anat_charm)"
    exit 0
  fi
else
  echo "Skipping anat_charm (START_FROM_MODULE=${START_FROM_MODULE})"
fi

print_section "Processing fieldmaps"
[ -f "$FUNC_FIELDMAPS_MODULE" ] || { echo "ERROR: missing module: $FUNC_FIELDMAPS_MODULE"; exit 2; }
[ -x "$FUNC_FIELDMAPS_MODULE" ] || chmod +x "$FUNC_FIELDMAPS_MODULE"
if should_run_stage "fieldmaps"; then
  run_module "fieldmaps" bash "$FUNC_FIELDMAPS_MODULE" "$MEDIR" "$Subject" "$StudyFolder" "$THREADS_FIELDMAPS" "$START_SESSION" "$FUNC_DIRNAME"
  if [[ "$STOP_AFTER_MODULE" == "fieldmaps" ]]; then
    echo "Stopping after fieldmaps (STOP_AFTER_MODULE=fieldmaps)"
    exit 0
  fi
else
  echo "Skipping fieldmaps (START_FROM_MODULE=${START_FROM_MODULE})"
fi

print_section "Coregistering SBrefs to anatomical image"
[ -f "$FUNC_COREG_MODULE" ] || { echo "ERROR: missing module: $FUNC_COREG_MODULE"; exit 2; }
if should_run_stage "coreg"; then
  run_module "coreg" bash "$FUNC_COREG_MODULE" "$MEDIR" "$Subject" "$StudyFolder" "$AtlasTemplate" "$DOF" "$THREADS_COREG" "$START_SESSION" "$AtlasSpace" "$FUNC_DIRNAME" "$FUNC_FILE_PREFIX"
  if [[ "$STOP_AFTER_MODULE" == "coreg" ]]; then
    echo "Stopping after coreg (STOP_AFTER_MODULE=coreg)"
    exit 0
  fi
else
  echo "Skipping coreg (START_FROM_MODULE=${START_FROM_MODULE})"
fi

print_section "Applying slice-time/headmotion/distortion corrections"
[ -f "$FUNC_HEADMOTION_MODULE" ] || { echo "ERROR: missing module: $FUNC_HEADMOTION_MODULE"; exit 2; }
if should_run_stage "headmotion"; then
  run_module "headmotion" bash "$FUNC_HEADMOTION_MODULE" "$MEDIR" "$Subject" "$StudyFolder" "$AtlasTemplate" "$DOF" "$THREADS_HEADMOTION" "$START_SESSION" "$AtlasSpace" "$FUNC_DIRNAME" "$FUNC_FILE_PREFIX"
  if [[ "$STOP_AFTER_MODULE" == "headmotion" ]]; then
    echo "Stopping after headmotion (STOP_AFTER_MODULE=headmotion)"
    exit 0
  fi
else
  echo "Skipping headmotion (START_FROM_MODULE=${START_FROM_MODULE})"
fi

print_section "Running denoising"
if should_run_stage "meica"; then
  if [[ "${PIPELINE_EFFECTIVE_DENOISE_MODE}" == "single_echo" ]]; then
    if [[ "${SINGLE_ECHO_DENOISE_METHOD}" == "aroma" ]]; then
      [ -f "$FUNC_AROMA_MODULE" ] || { echo "ERROR: missing module: $FUNC_AROMA_MODULE"; exit 2; }
      MODULE_DISPLAY_TAG="${SINGLE_ECHO_DENOISE_METHOD}" MODULE_LOG_TAG="${SINGLE_ECHO_DENOISE_METHOD}" \
        run_module "meica" bash "$FUNC_AROMA_MODULE" "$Subject" "$StudyFolder" "$THREADS_MEICA" "$START_SESSION" "$MEDIR"
    else
      [ -f "$FUNC_SINGLEECHO_MODULE" ] || { echo "ERROR: missing module: $FUNC_SINGLEECHO_MODULE"; exit 2; }
      MODULE_DISPLAY_TAG="${SINGLE_ECHO_DENOISE_METHOD}" MODULE_LOG_TAG="${SINGLE_ECHO_DENOISE_METHOD}" \
        run_module "meica" bash "$FUNC_SINGLEECHO_MODULE" "$Subject" "$StudyFolder" "$THREADS_MEICA" "$START_SESSION" "$MEDIR"
    fi
  else
    [ -f "$FUNC_MEICA_MODULE" ] || { echo "ERROR: missing module: $FUNC_MEICA_MODULE"; exit 2; }
    if [[ "${MULTI_ECHO_DENOISE_METHOD}" == "meica" ]]; then
      run_module "meica" bash "$FUNC_MEICA_MODULE" "$Subject" "$StudyFolder" "$THREADS_MEICA" "$MEPCA" "$MaxIterations" "$MaxRestarts" "$START_SESSION" "$MEDIR"
    else
      run_module "meica_optcom" env MEICA_RECLASSIFY_ENABLE=0 bash "$FUNC_MEICA_MODULE" "$Subject" "$StudyFolder" "$THREADS_MEICA" "$MEPCA" "$MaxIterations" "$MaxRestarts" "$START_SESSION" "$MEDIR"
      if [[ "${MULTI_ECHO_DENOISE_METHOD}" == "aroma" ]]; then
        [ -f "$FUNC_AROMA_MODULE" ] || { echo "ERROR: missing module: $FUNC_AROMA_MODULE"; exit 2; }
        MODULE_DISPLAY_TAG="${MULTI_ECHO_DENOISE_METHOD}" MODULE_LOG_TAG="${MULTI_ECHO_DENOISE_METHOD}" \
          run_module "meica" bash "$FUNC_AROMA_MODULE" "$Subject" "$StudyFolder" "$THREADS_MEICA" "$START_SESSION" "$MEDIR"
      else
        [ -f "$FUNC_SINGLEECHO_MODULE" ] || { echo "ERROR: missing module: $FUNC_SINGLEECHO_MODULE"; exit 2; }
        MODULE_DISPLAY_TAG="${MULTI_ECHO_DENOISE_METHOD}" MODULE_LOG_TAG="${MULTI_ECHO_DENOISE_METHOD}" \
          run_module "meica" bash "$FUNC_SINGLEECHO_MODULE" "$Subject" "$StudyFolder" "$THREADS_MEICA" "$START_SESSION" "$MEDIR"
      fi
    fi
  fi
  if [[ "$STOP_AFTER_MODULE" == "meica" ]]; then
    echo "Stopping after meica (STOP_AFTER_MODULE=meica)"
    exit 0
  fi
else
  echo "Skipping meica (START_FROM_MODULE=${START_FROM_MODULE})"
fi

print_section "Running MGTR"
[ -f "$FUNC_MGTR_MODULE" ] || { echo "ERROR: missing module: $FUNC_MGTR_MODULE"; exit 2; }
if should_run_stage "mgtr"; then
  run_module "mgtr" bash "$FUNC_MGTR_MODULE" "$Subject" "$StudyFolder" "$MEDIR" "$START_SESSION"
  if [[ "$STOP_AFTER_MODULE" == "mgtr" ]]; then
    echo "Stopping after mgtr (STOP_AFTER_MODULE=mgtr)"
    exit 0
  fi
else
  echo "Skipping mgtr (START_FROM_MODULE=${START_FROM_MODULE})"
fi

print_section "Mapping denoised data to surface"
[ -f "$FUNC_VOL2SURF_MODULE" ] || { echo "ERROR: missing module: $FUNC_VOL2SURF_MODULE"; exit 2; }
if [ -z "${VOL2SURF_INPUTS:-}" ]; then
  echo "ERROR: VOL2SURF_INPUTS is empty. Set a comma-separated list (e.g., OCME,OCME+MEICA,OCME+MEICA+MGTR)."
  exit 2
fi
Vol2SurfSpec="$VOL2SURF_INPUTS"
if should_run_stage "vol2surf"; then
  run_module "vol2surf" bash "$FUNC_VOL2SURF_MODULE" "$Subject" "$StudyFolder" "$MEDIR" "$Vol2SurfSpec" "$START_SESSION" "$AtlasSpace" "$FUNC_DIRNAME" "$FUNC_FILE_PREFIX"
  if [[ "$STOP_AFTER_MODULE" == "vol2surf" ]]; then
    echo "Stopping after vol2surf (STOP_AFTER_MODULE=vol2surf)"
    exit 0
  fi
else
  echo "Skipping vol2surf (START_FROM_MODULE=${START_FROM_MODULE})"
fi

if [[ "${CONCAT_ENABLE}" == "1" ]]; then
  if should_run_stage "concat"; then
    print_section "Running concat module"
    [ -f "$FUNC_CONCAT_MODULE" ] || { echo "ERROR: missing module: $FUNC_CONCAT_MODULE"; exit 2; }
    run_module "concat" bash "$FUNC_CONCAT_MODULE" "$Subject" "$StudyFolder" "$MEDIR" "$START_SESSION" "$FUNC_DIRNAME" "$FUNC_FILE_PREFIX"
    if [[ "$STOP_AFTER_MODULE" == "concat" ]]; then
      echo "Stopping after concat (STOP_AFTER_MODULE=concat)"
      exit 0
    fi
  else
    echo "Skipping concat (START_FROM_MODULE=${START_FROM_MODULE})"
  fi
fi

if [[ "${NSI_ENABLE}" == "1" ]]; then
  if should_run_stage "nsi"; then
    print_section "Running NSI module"
    [ -f "$FUNC_NSI_MODULE" ] || { echo "ERROR: missing module: $FUNC_NSI_MODULE"; exit 2; }
    run_module "nsi" bash "$FUNC_NSI_MODULE" "$Subject" "$StudyFolder" "$MEDIR" "$START_SESSION" "$FUNC_DIRNAME" "$FUNC_FILE_PREFIX"
    if [[ "$STOP_AFTER_MODULE" == "nsi" ]]; then
      echo "Stopping after nsi (STOP_AFTER_MODULE=nsi)"
      exit 0
    fi
  else
    echo "Skipping nsi (START_FROM_MODULE=${START_FROM_MODULE})"
  fi
fi

if [[ "${PFM_ENABLE}" == "1" ]]; then
  if should_run_stage "pfm"; then
    print_section "Running PFM module"
    [ -f "$FUNC_PFM_MODULE" ] || { echo "ERROR: missing module: $FUNC_PFM_MODULE"; exit 2; }
    run_module "pfm" bash "$FUNC_PFM_MODULE" "$Subject" "$StudyFolder" "$MEDIR" "$START_SESSION" "$FUNC_DIRNAME" "$FUNC_FILE_PREFIX"
    if [[ "$STOP_AFTER_MODULE" == "pfm" ]]; then
      echo "Stopping after pfm (STOP_AFTER_MODULE=pfm)"
      exit 0
    fi
  else
    echo "Skipping pfm (START_FROM_MODULE=${START_FROM_MODULE})"
  fi
fi
