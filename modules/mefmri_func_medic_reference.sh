#!/usr/bin/env bash
# Build MEDIC-unwarped run references for anatomical coregistration.

set -euo pipefail
shopt -s nullglob

if [[ "$#" -lt 7 || "$#" -gt 8 ]]; then
  echo "Usage: mefmri_func_medic_reference.sh <MEDIR> <Subject> <StudyFolder> <NTHREADS> <StartSession> <FuncDirName> <FuncFilePrefix> [ReferencePolicy]" >&2
  exit 2
fi

MEDIR="$1"
Subject="$2"
StudyFolder="$3"
NTHREADS="$4"
StartSession="$5"
FuncDirName="$6"
FuncFilePrefix="$7"
MEDIC_REFERENCE_POLICY="${8:-${MEDIC_REFERENCE_POLICY:-first}}"
SBREF_ECHO_COMBINATION="${SBREF_ECHO_COMBINATION:-${MEDIC_SBREF_COMBINATION:-mean}}"
SBREF_MAX_TE_MS="${SBREF_MAX_TE_MS:-${MEDIC_SBREF_MAX_TE_MS:-60}}"
SBREF_T2SMAP_MASK_THR="${SBREF_T2SMAP_MASK_THR:-${MEDIC_SBREF_T2SMAP_MASK_THR:-1}}"
SBREF_T2SMAP_THREADS="${SBREF_T2SMAP_THREADS:-${MEDIC_SBREF_T2SMAP_THREADS:-1}}"
SBREF_KEEP_INTERMEDIATES="${SBREF_KEEP_INTERMEDIATES:-${MEDIC_SBREF_KEEP_INTERMEDIATES:-0}}"

Subdir="$StudyFolder/$Subject"
FuncRoot="$Subdir/func/$FuncDirName"
UnprocRoot="$Subdir/func/unprocessed/$FuncDirName"

WARPKIT_ENV="${WARPKIT_ENV:-warpkit_env}"
WARPKIT_ACTIVATE_MODE="${WARPKIT_ACTIVATE_MODE:-conda_activate}"
WARPKIT_APPLY_WARP_BIN="${WARPKIT_APPLY_WARP_BIN:-wk-apply-warp}"
TEDANA_ENV="${TEDANA_ENV:-mefmri_env}"
TEDANA_ACTIVATE_MODE="${TEDANA_ACTIVATE_MODE:-conda_activate}"
T2SMAP_BIN="${T2SMAP_BIN:-t2smap}"

die() {
  echo "ERROR: $*" >&2
  exit 2
}

resolve_warpkit_bin() {
  local exe="$1"
  if [[ "$exe" == */* ]]; then
    [[ -x "$exe" ]] || die "Configured warpkit executable is not executable: $exe"
    echo "$exe"
    return 0
  fi
  case "$WARPKIT_ACTIVATE_MODE" in
    direct)
      command -v "$exe" || die "Could not find $exe on PATH with WARPKIT_ACTIVATE_MODE=direct"
      ;;
    conda_activate|conda_run)
      command -v conda >/dev/null 2>&1 || die "conda is required for WARPKIT_ACTIVATE_MODE=$WARPKIT_ACTIVATE_MODE"
      local base candidate
      base="$(conda info --base 2>/dev/null || true)"
      [[ -n "$base" ]] || die "Could not resolve conda base path"
      candidate="$base/envs/$WARPKIT_ENV/bin/$exe"
      [[ -x "$candidate" ]] || die "Missing $exe in conda env '$WARPKIT_ENV': $candidate"
      echo "$candidate"
      ;;
    *)
      die "Invalid WARPKIT_ACTIVATE_MODE=$WARPKIT_ACTIVATE_MODE"
      ;;
  esac
}

json_value() {
  local json="$1"
  local key="$2"
  python3 - "$json" "$key" <<'PY'
import json
import sys
with open(sys.argv[1]) as f:
    data = json.load(f)
print(data.get(sys.argv[2], ""))
PY
}

ms_to_s() {
  python3 - "$1" <<'PY'
import sys
print(f"{float(sys.argv[1]) / 1000.0:.8g}")
PY
}

resolve_tedana_bin() {
  local exe="$1"
  if [[ "$exe" == */* ]]; then
    [[ -x "$exe" ]] || die "Configured tedana executable is not executable: $exe"
    echo "$exe"
    return 0
  fi
  case "$TEDANA_ACTIVATE_MODE" in
    direct)
      command -v "$exe" || die "Could not find $exe on PATH with TEDANA_ACTIVATE_MODE=direct"
      ;;
    conda_activate|conda_run)
      command -v conda >/dev/null 2>&1 || die "conda is required for TEDANA_ACTIVATE_MODE=$TEDANA_ACTIVATE_MODE"
      local base candidate
      base="$(conda info --base 2>/dev/null || true)"
      [[ -n "$base" ]] || die "Could not resolve conda base path"
      candidate="$base/envs/$TEDANA_ENV/bin/$exe"
      [[ -x "$candidate" ]] || die "Missing $exe in conda env '$TEDANA_ENV': $candidate"
      echo "$candidate"
      ;;
    *)
      die "Invalid TEDANA_ACTIVATE_MODE=$TEDANA_ACTIVATE_MODE"
      ;;
  esac
}

extract_reference_displacement() {
  local source="$1"
  local output="$2"
  local policy="$3"

  case "$policy" in
    first|motion_reference)
      fslroi "$source" "$output" 0 1
      ;;
    median)
      fslmaths "$source" -Tmedian "$output"
      ;;
    mean)
      fslmaths "$source" -Tmean "$output"
      ;;
    *)
      die "Unsupported MEDIC_REFERENCE_POLICY=$policy (use first|motion_reference|median|mean)"
      ;;
  esac
}

float_lt() {
  python3 - "$1" "$2" <<'PY'
import sys
print("1" if float(sys.argv[1]) < float(sys.argv[2]) else "0")
PY
}

find_sbref_for_echo() {
  local unproc_dir="$1"
  local s="$2"
  local r="$3"
  local echo_idx="$4"
  local cand
  for cand in \
    "$unproc_dir/SBRef_S${s}_R${r}_E${echo_idx}.nii.gz" \
    "$unproc_dir/SBREF_S${s}_R${r}_E${echo_idx}.nii.gz" \
    "$unproc_dir/SBref_S${s}_R${r}_E${echo_idx}.nii.gz" \
    "$unproc_dir/sbref_S${s}_R${r}_E${echo_idx}.nii.gz"; do
    if [[ -f "$cand" ]]; then
      echo "$cand"
      return 0
    fi
  done
  return 1
}

make_4d_copy() {
  local py_bin="$1"
  local input="$2"
  local output="$3"
  "$py_bin" - "$input" "$output" <<'PY'
import sys
import nibabel as nb

img = nb.load(sys.argv[1])
data = img.get_fdata(dtype="float32")
if data.ndim == 3:
    data = data[..., None]
nb.save(nb.Nifti1Image(data, img.affine, img.header), sys.argv[2])
PY
}

combine_echo_refs_t2smap() {
  local combmode="$1"
  local out="$2"
  local tmp_dir="$3"
  shift 3
  local refs=("$@")

  [[ "${#COMBINE_TES_SECONDS[@]}" -eq "${#refs[@]}" ]] || die "T2SMAP TE/reference count mismatch"
  [[ "${#refs[@]}" -ge 2 ]] || die "T2SMAP SBRef combination requires at least two echoes"

  local t2smap_bin py_bin t2s_dir mask inputs=()
  t2smap_bin="$(resolve_tedana_bin "$T2SMAP_BIN")"
  py_bin="$(resolve_tedana_bin python)"
  t2s_dir="$tmp_dir/t2smap"
  mkdir -p "$t2s_dir" "$tmp_dir/mplconfig"

  fslmaths "${refs[0]}" -thr "$SBREF_T2SMAP_MASK_THR" -bin "$tmp_dir/t2smap_mask.nii.gz"

  local idx ref4
  for ((idx = 0; idx < ${#refs[@]}; idx++)); do
    ref4="$tmp_dir/t2smap_echo_$((idx + 1))_4d.nii.gz"
    make_4d_copy "$py_bin" "${refs[$idx]}" "$ref4"
    inputs+=("$ref4")
  done

  MPLCONFIGDIR="$tmp_dir/mplconfig" "$t2smap_bin" \
    -d "${inputs[@]}" \
    -e "${COMBINE_TES_SECONDS[@]}" \
    --out-dir "$t2s_dir" \
    --prefix sbref_ \
    --convention bids \
    --mask "$tmp_dir/t2smap_mask.nii.gz" \
    --masktype none \
    --combmode "$combmode" \
    --n-threads "$SBREF_T2SMAP_THREADS" \
    --overwrite

  [[ -f "$t2s_dir/sbref_desc-optcom_bold.nii.gz" ]] || die "t2smap did not create sbref_desc-optcom_bold.nii.gz"
  fslroi "$t2s_dir/sbref_desc-optcom_bold.nii.gz" "$out" 0 1
}

combine_echo_refs() {
  local method="$1"
  local out="$2"
  local tmp_dir="$3"
  shift 3
  local refs=("$@")

  [[ "${#refs[@]}" -gt 0 ]] || die "combine_echo_refs called with no inputs"

  case "$method" in
    mean)
      fslmerge -t "$tmp_dir/all_echo_refs.nii.gz" "${refs[@]}"
      fslmaths "$tmp_dir/all_echo_refs.nii.gz" -Tmean "$out"
      ;;
    sos)
      local sum="$tmp_dir/sos_sum.nii.gz"
      local sq="$tmp_dir/sos_sq_0.nii.gz"
      fslmaths "${refs[0]}" -sqr "$sum"
      local idx
      for ((idx = 1; idx < ${#refs[@]}; idx++)); do
        sq="$tmp_dir/sos_sq_${idx}.nii.gz"
        fslmaths "${refs[$idx]}" -sqr "$sq"
        fslmaths "$sum" -add "$sq" "$sum"
      done
      fslmaths "$sum" -sqrt "$out"
      ;;
    first)
      cp "${refs[0]}" "$out"
      ;;
    last)
      cp "${refs[$((${#refs[@]} - 1))]}" "$out"
      ;;
    t2s|paid)
      combine_echo_refs_t2smap "$method" "$out" "$tmp_dir" "${refs[@]}"
      ;;
    *)
      die "Unsupported SBREF_ECHO_COMBINATION=$method (use mean|sos|t2s|paid|first|last)"
      ;;
  esac
}

build_medic_distorted_sbref() {
  local s="$1"
  local r="$2"
  local run_dir="$FuncRoot/session_${s}/run_${r}"
  local unproc_dir="$UnprocRoot/session_${s}/run_${r}"
  local ref_dir="$3"
  local out="$ref_dir/SBref_distorted.nii.gz"

  mkdir -p "$run_dir"
  mkdir -p "$ref_dir"

  local tmp_dir="$ref_dir/.sbref_tmp"
  rm -rf "$tmp_dir"
  mkdir -p "$tmp_dir"

  local te_file="$run_dir/TE.txt"
  local te_values=()
  if [[ -f "$te_file" ]]; then
    read -r -a te_values < "$te_file"
  fi

  local sources_tsv="$ref_dir/sbref_echo_sources.tsv"
  {
    echo -e "echo\tte_ms\tincluded\tsource_type\tsource_path\tworking_copy"
  } > "$sources_tsv"

  mapfile -t mags < <(find -L "$unproc_dir" -maxdepth 1 -type f -name "${FuncFilePrefix}_S${s}_R${r}_E*.nii.gz" ! -name '*_phase.nii.gz' | sort -V)
  local selected_refs=()
  local selected_tes_seconds=()
  local mag base echo_idx te include sbref one src_type reoriented
  for mag in "${mags[@]}"; do
    base="$(basename "$mag")"
    [[ "$base" =~ _E([0-9]+)\.nii\.gz$ ]] || continue
    echo_idx="${BASH_REMATCH[1]}"
    te="${te_values[$((echo_idx - 1))]:-}"
    include=1
    if [[ -n "$te" && "$SBREF_MAX_TE_MS" != "none" ]]; then
      include="$(float_lt "$te" "$SBREF_MAX_TE_MS")"
    fi

    if [[ "$include" != "1" ]]; then
      echo -e "${echo_idx}\t${te:-NA}\t0\tskipped_te_ge_${SBREF_MAX_TE_MS}\t${mag}\t" >> "$sources_tsv"
      continue
    fi

    one="$tmp_dir/echo_${echo_idx}.nii.gz"
    if sbref="$(find_sbref_for_echo "$unproc_dir" "$s" "$r" "$echo_idx")"; then
      cp "$sbref" "$one"
      src_type="imported_sbref"
    else
      fslroi "$mag" "$one" "${SBREF_FALLBACK_SKIP_TRS:-10}" 1
      echo "${SBREF_FALLBACK_SKIP_TRS:-10}" > "$run_dir/rmVols.txt"
      sbref="$mag"
      src_type="fallback_bold_frame_${SBREF_FALLBACK_SKIP_TRS:-10}"
    fi

    if [[ "${SBREF_REORIENT_TO_STD:-1}" == "1" ]]; then
      reoriented="$tmp_dir/echo_${echo_idx}_reorient.nii.gz"
      fslreorient2std "$one" "$reoriented"
      mv -f "$reoriented" "$one"
    fi

    selected_refs+=("$one")
    if [[ -n "$te" ]]; then
      selected_tes_seconds+=("$(ms_to_s "$te")")
    fi
    echo -e "${echo_idx}\t${te:-NA}\t1\t${src_type}\t${sbref}\t${one}" >> "$sources_tsv"
  done

  [[ "${#selected_refs[@]}" -gt 0 ]] || die "No echo references could be built for session_${s}/run_${r}"
  COMBINE_TES_SECONDS=("${selected_tes_seconds[@]}")
  combine_echo_refs "$SBREF_ECHO_COMBINATION" "$out" "$tmp_dir" "${selected_refs[@]}"
  if [[ "${SBREF_REORIENT_TO_STD:-1}" == "1" ]]; then
    fslreorient2std "$out" "$tmp_dir/SBref_reorient.nii.gz"
    mv -f "$tmp_dir/SBref_reorient.nii.gz" "$out"
  fi
  cp "$out" "$ref_dir/SBref_echo_combined.nii.gz"
  if [[ "$SBREF_KEEP_INTERMEDIATES" == "1" ]]; then
    echo "$tmp_dir" > "$ref_dir/sbref_intermediates_dir.txt"
  else
    rm -rf "$tmp_dir"
  fi
}

[[ -d "$UnprocRoot" ]] || die "Missing unprocessed functional root: $UnprocRoot"
APPLY_WARP_BIN="$(resolve_warpkit_bin "$WARPKIT_APPLY_WARP_BIN")"

echo "[medic-reference] Subject=$Subject FuncDirName=$FuncDirName policy=$MEDIC_REFERENCE_POLICY sbref_combination=$SBREF_ECHO_COMBINATION sbref_max_te_ms=$SBREF_MAX_TE_MS"

mapfile -t SessionDirs < <(find -L "$UnprocRoot" -mindepth 1 -maxdepth 1 -type d -name 'session_*' | sort -V)
for SessionDir in "${SessionDirs[@]}"; do
  s="${SessionDir##*/session_}"
  [[ "$s" =~ ^[0-9]+$ ]] || continue
  (( s >= StartSession )) || continue

  mapfile -t RunDirs < <(find -L "$SessionDir" -mindepth 1 -maxdepth 1 -type d -name 'run_*' | sort -V)
  for RunDir in "${RunDirs[@]}"; do
    r="${RunDir##*/run_}"
    [[ "$r" =~ ^[0-9]+$ ]] || continue

    RunRoot="$FuncRoot/session_${s}/run_${r}"
    MedicDir="$RunRoot/MEDIC"
    RefDir="$MedicDir/reference"
    mkdir -p "$RefDir"

    DMap="$MedicDir/${FuncFilePrefix}_S${s}_R${r}_displacementmaps.nii"
    [[ -f "$DMap" ]] || die "Missing MEDIC displacement map: $DMap"

    build_medic_distorted_sbref "$s" "$r" "$RefDir"
    SBRef="$RefDir/SBref_distorted.nii.gz"

    FirstJson="$UnprocRoot/session_${s}/run_${r}/${FuncFilePrefix}_S${s}_R${r}_E1.json"
    [[ -f "$FirstJson" ]] || die "Missing first echo JSON: $FirstJson"
    PED="$(json_value "$FirstJson" PhaseEncodingDirection)"
    [[ -n "$PED" ]] || die "Missing PhaseEncodingDirection in $FirstJson"

    RefDMap="$RefDir/SBref_medic_reference_displacement.nii.gz"
    extract_reference_displacement "$DMap" "$RefDMap" "$MEDIC_REFERENCE_POLICY"

    "$APPLY_WARP_BIN" \
      --input "$SBRef" \
      --transform "$RefDMap" \
      --transform-type map \
      --phase-encoding-axis "$PED" \
      --output "$RefDir/SBref_unwarped.nii.gz"

    fslmaths "$RefDir/SBref_unwarped.nii.gz" -thr 0 "$RefDir/SBref_unwarped_brain.nii.gz"

    {
      echo -e "key\tvalue"
      echo -e "policy\t$MEDIC_REFERENCE_POLICY"
      echo -e "sbref_combination\t$SBREF_ECHO_COMBINATION"
      echo -e "sbref_max_te_ms\t$SBREF_MAX_TE_MS"
      echo -e "phase_encoding_direction\t$PED"
      echo -e "source_displacement\t$DMap"
      echo -e "reference_displacement\t$RefDMap"
      echo -e "distorted_sbref\t$SBRef"
      echo -e "unwarped_sbref\t$RefDir/SBref_unwarped.nii.gz"
    } > "$RefDir/reference_policy.tsv"

    echo "[medic-reference] created session_${s}/run_${r}: $RefDir/SBref_unwarped.nii.gz"
  done
done

echo "[medic-reference] complete"
