#!/usr/bin/env bash
# Alternate aCompCor dispatcher for single-echo data or OCME-on-multi-echo data.

set -euo pipefail
IFS=$'\n\t'

Subject="${1:?missing Subject}"
StudyFolder="${2:?missing StudyFolder}"
NTHREADS="${3:?missing NTHREADS}"
StartSession="${4:?missing StartSession}"
MEDIR="${5:?missing MEDIR}"

FuncDirName="${FUNC_DIRNAME:-rest}"
FuncFilePrefix="${FUNC_FILE_PREFIX:-Rest}"
SingleEchoIndex="${SINGLE_ECHO_ECHO_INDEX:-1}"
EffectiveMode="${PIPELINE_EFFECTIVE_DENOISE_MODE:-single_echo}"
SourceTag="${PIPELINE_SOURCE_FUNC_TAG:-}"
if [[ -z "$SourceTag" ]]; then
  if [[ "$EffectiveMode" == "single_echo" ]]; then
    SourceTag="E${SingleEchoIndex}"
  else
    SourceTag="OCME"
  fi
fi
DenoiseTag="${PIPELINE_DENOISE_OUTPUT_TAG:-${SourceTag}+aCompCor}"
ACOMPCOR_MODULE="${FUNC_ACOMPCOR_MODULE:-$MEDIR/modules/mefmri_func_acompcor.sh}"
Subdir="$StudyFolder/$Subject"

log() { echo "[singleecho] $*"; }
die() { echo "ERROR: $*" >&2; exit 2; }

case "$EffectiveMode" in
  single_echo|multi_echo) ;;
  *) die "Invalid PIPELINE_EFFECTIVE_DENOISE_MODE=$EffectiveMode (use single_echo|multi_echo)" ;;
esac

ensure_source_input() {
  local run_dir="$1"
  local src dst
  if [[ "$EffectiveMode" == "single_echo" ]]; then
    src="$run_dir/${FuncFilePrefix}_E${SingleEchoIndex}_acpc.nii.gz"
    dst="$run_dir/${FuncFilePrefix}_${SourceTag}.nii.gz"
  else
    src="$run_dir/${FuncFilePrefix}_${SourceTag}.nii.gz"
    dst="$src"
  fi
  [[ -f "$src" ]] || die "Missing source input: $src"
  if [[ "$src" != "$dst" ]]; then
    cp -f "$src" "$dst"
  fi
}

log "start subject=${Subject} mode=${EffectiveMode} source_tag=${SourceTag} output_tag=${DenoiseTag}"

mapfile -t RUNS < <(find -L "$Subdir/func/$FuncDirName" -mindepth 2 -maxdepth 2 -type d -name 'run_*' | sort -V)
[[ "${#RUNS[@]}" -gt 0 ]] || die "No run directories found in $Subdir/func/$FuncDirName"

for run_dir in "${RUNS[@]}"; do
  session_dir="${run_dir%/*}"
  session_num="${session_dir##*/}"
  session_num="${session_num#session_}"
  [[ "$session_num" =~ ^[0-9]+$ ]] || continue
  (( session_num >= StartSession )) || continue
  ensure_source_input "$run_dir"
done

[[ -f "$ACOMPCOR_MODULE" ]] || die "Missing aCompCor module: $ACOMPCOR_MODULE"
ACOMPCOR_INPUT_BASENAME="${FuncFilePrefix}_${SourceTag}.nii.gz" \
ACOMPCOR_OUTPUT_BASENAME="${FuncFilePrefix}_${DenoiseTag}" \
ACOMPCOR_OUTPUT_FULL_BASENAME="${FuncFilePrefix}_${DenoiseTag}_full" \
ACOMPCOR_PUBLISH_OUTPUT=1 \
ACOMPCOR_PUBLISHED_BASENAME="${FuncFilePrefix}_${DenoiseTag}" \
  bash "$ACOMPCOR_MODULE" "$Subject" "$StudyFolder" "$MEDIR" "$StartSession"

log "done subject=${Subject}"
