#!/usr/bin/env bash
# No-MATLAB fieldmap module.
# Call signature:
#   mefmri_func_fieldmaps.sh <MEDIR> <Subject> <StudyFolder> <NTHREADS> <StartSession> [FuncDirName]

set -euo pipefail
IFS=$'\n\t'

MEDIR="${1:?missing MEDIR}"
Subject="${2:?missing Subject}"
StudyFolder="${3:?missing StudyFolder}"
NTHREADS="${4:?missing NTHREADS}"
StartSession="${5:-1}"
FuncDirName="${6:-${FUNC_DIRNAME:-rest}}"

Subdir="$StudyFolder/$Subject"
[[ -d "$Subdir" ]] || { echo "ERROR: missing subject dir: $Subdir" >&2; exit 2; }

# Optional knobs from wrapper config.
FM_RAW_DIR_REL="${FM_RAW_DIR_REL:-func/unprocessed/${FuncDirName}/field_maps}"
FM_OUT_DIR_REL="${FM_OUT_DIR_REL:-func/${FuncDirName}/field_maps}"
FM_QA_DIR_REL="${FM_QA_DIR_REL:-func/${FuncDirName}/qa}"
TOPUP_CONFIG="${TOPUP_CONFIG:-b02b0.cnf}"
FM_BET_FRAC="${FM_BET_FRAC:-0.35}"
FM_SMOOTH_SIGMA_MM="${FM_SMOOTH_SIGMA_MM:-2}"
USE_WB_SMOOTHING="${USE_WB_SMOOTHING:-1}"
CLEAN_INTERMEDIATE="${CLEAN_INTERMEDIATE:-1}"
FIELDMAPS_PYTHON="${FIELDMAPS_PYTHON:-${PIPELINE_PYTHON:-python3}}"
FUNC_NOFIELDMAP_MODE="${FUNC_NOFIELDMAP_MODE:-0}"
DISTORTION_CORRECTION_MODE="${DISTORTION_CORRECTION_MODE:-topup}"
PHASEDIFF_GDCOEFFS="${PHASEDIFF_GDCOEFFS:-NONE}"
FIELD_MAP_PREPROCESSING_SCRIPT="${FIELD_MAP_PREPROCESSING_SCRIPT:-$MEDIR/HCPpipelines-master/global/scripts/FieldMapPreprocessingAll.sh}"

# Phase encoding handling:
# - infer from JSON by default
# - allow user override via BIDS string (i/j/k with optional -)
FM_PE_MODE="${FM_PE_MODE:-infer}"          # infer|config
FM_AP_PE_DIR="${FM_AP_PE_DIR:-}"           # e.g. j-
FM_PA_PE_DIR="${FM_PA_PE_DIR:-}"           # e.g. j
FM_DEFAULT_AP_VEC="${FM_DEFAULT_AP_VEC:-0 -1 0}"
FM_DEFAULT_PA_VEC="${FM_DEFAULT_PA_VEC:-0 1 0}"

RAW_FM_DIR="$Subdir/$FM_RAW_DIR_REL"
FM_DIR="$Subdir/$FM_OUT_DIR_REL"
QA_DIR="$Subdir/$FM_QA_DIR_REL"
ALL_DIR="$FM_DIR/AllFMs"
TOPUP_DIR="$ALL_DIR/topup"
PHASEDIFF_DIR="$ALL_DIR/phasediff"
LOG_DIR="$FM_DIR/logs"
ACQ="$FM_DIR/acqparams.txt"
FM_MODE_TXT="$FM_DIR/FIELDMAP_MODE.txt"
FM_QA_TXT="$QA_DIR/FieldMapFallback.txt"

mkdir -p "$FM_DIR" "$ALL_DIR" "$TOPUP_DIR" "$LOG_DIR" "$QA_DIR"

T1="$Subdir/anat/T1w/T1w_acpc_dc_restore.nii.gz"
T1B="$Subdir/anat/T1w/T1w_acpc_dc_restore_brain.nii.gz"
ASEG="$Subdir/anat/T1w/$Subject/mri/aparc+aseg.mgz"
export SUBJECTS_DIR="$Subdir/anat/T1w"

EPI_REG_DOF="$MEDIR/res0urces/epi_reg_dof"
EYE_DAT="$MEDIR/res0urces/eye.dat"

log() { echo "[$(date '+%F %T')] $*"; }
die() { echo "ERROR: $*" >&2; exit 2; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }
cleanup_legacy_txt_artifacts() {
  # Legacy pipeline runs may leave these text files; remove them automatically.
  find "$Subdir" -type f \( -name "AllFM.txt" -o -name "AllFMs.txt" \) -delete 2>/dev/null || true
}
trap cleanup_legacy_txt_artifacts EXIT
[[ "$FUNC_NOFIELDMAP_MODE" == "0" || "$FUNC_NOFIELDMAP_MODE" == "1" ]] || die "FUNC_NOFIELDMAP_MODE must be 0 or 1"
case "$DISTORTION_CORRECTION_MODE" in
  topup|phasediff) ;;
  none) FUNC_NOFIELDMAP_MODE=1 ;;
  *) die "DISTORTION_CORRECTION_MODE must be topup, phasediff, or none in this module (got '$DISTORTION_CORRECTION_MODE')" ;;
esac
log "Functional task: ${FuncDirName}"
log "Raw fieldmap dir: ${RAW_FM_DIR}"
log "Processed fieldmap dir: ${FM_DIR}"
log "Distortion correction mode: ${DISTORTION_CORRECTION_MODE}"

for c in "$FIELDMAPS_PYTHON" fslmaths; do need_cmd "$c"; done
WB_OK=0
if [[ "$FUNC_NOFIELDMAP_MODE" == "0" ]]; then
  for c in fslmerge flirt bet convert_xfm; do need_cmd "$c"; done
  if [[ "$DISTORTION_CORRECTION_MODE" == "topup" ]]; then
    for c in topup mcflirt fslnvols parallel; do need_cmd "$c"; done
  else
    if ! command -v fsl_prepare_fieldmap >/dev/null 2>&1 && [[ ! -x "${FSLDIR:-}/bin/fsl_prepare_fieldmap" ]]; then
      die "Missing fsl_prepare_fieldmap on PATH or under FSLDIR/bin"
    fi
    [[ -f "$FIELD_MAP_PREPROCESSING_SCRIPT" ]] || die "Missing HCP FieldMapPreprocessingAll.sh: $FIELD_MAP_PREPROCESSING_SCRIPT"
  fi
  for c in mri_binarize mri_convert bbregister tkregister2; do need_cmd "$c"; done
  if command -v wb_command >/dev/null 2>&1 && [[ "$USE_WB_SMOOTHING" == "1" ]]; then
    WB_OK=1
  fi
fi

[[ -f "$T1" ]] || die "Missing: $T1"
[[ -f "$T1B" ]] || die "Missing: $T1B"

write_no_fieldmap_outputs() {
  local reason="$1"
  rm -rf "$ALL_DIR" "$TOPUP_DIR"
  mkdir -p "$ALL_DIR" "$TOPUP_DIR" "$QA_DIR"
  printf 'none\n' > "$FM_MODE_TXT"
  cat > "$FM_QA_TXT" <<EOF
No-fieldmap functional mode was used for this subject.
Reason: $reason
Susceptibility distortion correction was skipped.
Avg_FM_rads_acpc.nii.gz is a zero-valued placeholder in T1w/ACPC space.
Avg_FM_mag_acpc.nii.gz and Avg_FM_mag_acpc_brain.nii.gz are anatomical compatibility images.
EOF
  fslmaths "$T1B" -mul 0 "$FM_DIR/Avg_FM_rads_acpc.nii.gz" >/dev/null 2>&1
  cp -f "$T1" "$FM_DIR/Avg_FM_mag_acpc.nii.gz"
  cp -f "$T1B" "$FM_DIR/Avg_FM_mag_acpc_brain.nii.gz"
  : > "$LOG_DIR/topup_parallel.log"
  log "Fieldmap module complete in no-fieldmap mode."
  exit 0
}

if [[ "$FUNC_NOFIELDMAP_MODE" == "1" ]]; then
  write_no_fieldmap_outputs "FUNC_NOFIELDMAP_MODE=1"
fi

[[ -d "$RAW_FM_DIR" ]] || die "Missing raw fieldmap dir: $RAW_FM_DIR"
[[ -f "$ASEG" ]] || die "Missing: $ASEG"
[[ -x "$EPI_REG_DOF" ]] || die "Missing executable: $EPI_REG_DOF"
[[ -f "$EYE_DAT" ]] || die "Missing: $EYE_DAT"
printf '%s\n' "$DISTORTION_CORRECTION_MODE" > "$FM_MODE_TXT"

register_fieldmap_to_acpc() {
  local tag="$1"
  local OUTROOT="$2"
  local ses run

  [[ -f "$OUTROOT/FM_mag_${tag}.nii.gz" ]] || die "Missing native fieldmap magnitude: $OUTROOT/FM_mag_${tag}.nii.gz"
  [[ -f "$OUTROOT/FM_rads_${tag}.nii.gz" ]] || die "Missing native fieldmap radians/sec image: $OUTROOT/FM_rads_${tag}.nii.gz"

  if [[ ! -f "$OUTROOT/FM_mag_brain_${tag}.nii.gz" ]]; then
    bet "$OUTROOT/FM_mag_${tag}.nii.gz" "$OUTROOT/FM_mag_brain_${tag}.nii.gz" -f "$FM_BET_FRAC" -R >/dev/null 2>&1
  fi

  "$EPI_REG_DOF" --epi="$OUTROOT/FM_mag_${tag}.nii.gz" \
    --t1="$T1" --t1brain="$T1B" --out="$OUTROOT/fm2acpc_${tag}" \
    --wmseg="$Subdir/anat/T1w/$Subject/mri/white.nii.gz" --dof=6 >/dev/null 2>&1

  bbregister --s freesurfer --mov "$OUTROOT/fm2acpc_${tag}.nii.gz" \
    --init-reg "$EYE_DAT" --surf white.deformed --bold \
    --reg "$OUTROOT/fm2acpc_bbr_${tag}.dat" --6 \
    --o "$OUTROOT/fm2acpc_bbr_${tag}.nii.gz" >/dev/null 2>&1
  tkregister2 --s freesurfer --noedit --reg "$OUTROOT/fm2acpc_bbr_${tag}.dat" \
    --mov "$OUTROOT/fm2acpc_${tag}.nii.gz" --targ "$T1" \
    --fslregout "$OUTROOT/fm2acpc_bbr_${tag}.mat" >/dev/null 2>&1
  convert_xfm -omat "$OUTROOT/fm2acpc_${tag}.mat" \
    -concat "$OUTROOT/fm2acpc_bbr_${tag}.mat" "$OUTROOT/fm2acpc_${tag}.mat" >/dev/null 2>&1

  flirt -dof 6 -interp spline -in "$OUTROOT/FM_mag_${tag}.nii.gz" -ref "$T1B" \
    -out "$OUTROOT/FM_mag_acpc_${tag}.nii.gz" -applyxfm -init "$OUTROOT/fm2acpc_${tag}.mat" >/dev/null 2>&1
  fslmaths "$OUTROOT/FM_mag_acpc_${tag}.nii.gz" -mas "$T1B" "$OUTROOT/FM_mag_acpc_brain_${tag}.nii.gz" >/dev/null 2>&1
  flirt -dof 6 -interp spline -in "$OUTROOT/FM_rads_${tag}.nii.gz" -ref "$T1B" \
    -out "$OUTROOT/FM_rads_acpc_${tag}.nii.gz" -applyxfm -init "$OUTROOT/fm2acpc_${tag}.mat" >/dev/null 2>&1

  if [[ "$WB_OK" == "1" ]]; then
    wb_command -volume-smoothing "$OUTROOT/FM_rads_acpc_${tag}.nii.gz" "$FM_SMOOTH_SIGMA_MM" \
      "$OUTROOT/FM_rads_acpc_${tag}.nii.gz" -fix-zeros >/dev/null 2>&1
  fi

  ses="${tag#S}"; ses="${ses%%_*}"
  run="${tag#*_R}"
  mv -f "$OUTROOT/FM_rads_acpc_${tag}.nii.gz" "$ALL_DIR/FM_rads_acpc_S${ses}_R${run}.nii.gz"
  mv -f "$OUTROOT/FM_mag_acpc_${tag}.nii.gz" "$ALL_DIR/FM_mag_acpc_S${ses}_R${run}.nii.gz"
  mv -f "$OUTROOT/FM_mag_acpc_brain_${tag}.nii.gz" "$ALL_DIR/FM_mag_acpc_brain_S${ses}_R${run}.nii.gz"
}

write_phasediff_manifest() {
  local manifest="$1"
  local qa="$2"
  "$FIELDMAPS_PYTHON" - "$RAW_FM_DIR" "$manifest" "$qa" "$StartSession" <<'PY'
import json
import re
import sys
from pathlib import Path

raw = Path(sys.argv[1])
manifest = Path(sys.argv[2])
qa = Path(sys.argv[3])
start_session = int(sys.argv[4])

def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)

def load_json(p):
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        die(f"Could not read JSON {p}: {exc}")

def echo_diff_ms(phase_json, mag1_json, mag2_json):
    meta = load_json(phase_json)
    if "EchoTimeDifference" in meta:
        diff = float(meta["EchoTimeDifference"])
    elif "EchoTime1" in meta and "EchoTime2" in meta:
        diff = float(meta["EchoTime2"]) - float(meta["EchoTime1"])
    elif mag1_json and mag2_json:
        m1 = load_json(mag1_json)
        m2 = load_json(mag2_json)
        diff = float(m2["EchoTime"]) - float(m1["EchoTime"])
    else:
        die(f"Missing EchoTime1/EchoTime2 or magnitude EchoTime metadata for {phase_json}")
    if diff <= 0:
        die(f"Echo time difference must be positive for {phase_json}; got {diff}")
    return diff * 1000.0 if diff < 1.0 else diff

rows = []
qa_lines = []
for phase in sorted(raw.glob("PhaseDiff_S*_R*.nii.gz")):
    tag = phase.name[len("PhaseDiff_"):-7]
    m = re.match(r"S(\d+)_R(\d+)$", tag)
    if not m:
        die(f"Unexpected PhaseDiff tag: {tag}")
    ses = int(m.group(1))
    if ses < start_session:
        continue
    mag1 = raw / f"Magnitude1_{tag}.nii.gz"
    mag2 = raw / f"Magnitude2_{tag}.nii.gz"
    if not mag1.exists() and not mag2.exists():
        die(f"Missing Magnitude1/Magnitude2 image for {phase}")
    phase_json = raw / f"PhaseDiff_{tag}.json"
    if not phase_json.exists():
        die(f"Missing phasediff JSON: {phase_json}")
    mag1_json = raw / f"Magnitude1_{tag}.json" if mag1.exists() else None
    mag2_json = raw / f"Magnitude2_{tag}.json" if mag2.exists() else None
    delta_te = echo_diff_ms(phase_json, mag1_json, mag2_json)
    rows.append((tag, str(phase), str(mag1 if mag1.exists() else "-"), str(mag2 if mag2.exists() else "-"), f"{delta_te:.8g}"))
    qa_lines.append(f"{tag}: PhaseDiff={phase.name}, Magnitude1={mag1.name if mag1.exists() else 'missing'}, Magnitude2={mag2.name if mag2.exists() else 'missing'}, DeltaTE_ms={delta_te:.8g}")

if not rows:
    die(f"No PhaseDiff_S*_R*.nii.gz files found in {raw} at/after StartSession={start_session}")

manifest.parent.mkdir(parents=True, exist_ok=True)
manifest.write_text("tag\tphase\tmagnitude1\tmagnitude2\tdelta_te_ms\n" + "\n".join("\t".join(row) for row in rows) + "\n")
qa.parent.mkdir(parents=True, exist_ok=True)
qa.write_text("HCP-style phasediff fieldmap preprocessing inputs\n" + "\n".join(qa_lines) + "\n")
PY
}

if [[ "$DISTORTION_CORRECTION_MODE" == "topup" || "$DISTORTION_CORRECTION_MODE" == "phasediff" ]]; then
  # WM seg + temporary FreeSurfer alias used by epi_reg_dof and bbregister.
  mri_binarize --i "$ASEG" --wm --o "$Subdir/anat/T1w/$Subject/mri/white.mgz" >/dev/null 2>&1
  mri_convert -i "$Subdir/anat/T1w/$Subject/mri/white.mgz" \
    -o "$Subdir/anat/T1w/$Subject/mri/white.nii.gz" --like "$T1" >/dev/null 2>&1
  rm -rf "$Subdir/anat/T1w/freesurfer" >/dev/null 2>&1 || true
  cp -rf "$Subdir/anat/T1w/$Subject" "$Subdir/anat/T1w/freesurfer" >/dev/null 2>&1
fi

if [[ "$DISTORTION_CORRECTION_MODE" == "topup" ]]; then
# Build acqparams.txt and the QA summary from BIDS JSON sidecars.
"$FIELDMAPS_PYTHON" - "$RAW_FM_DIR" "$ACQ" "$QA_DIR/AvgFieldMap.txt" "$FM_PE_MODE" \
  "$FM_AP_PE_DIR" "$FM_PA_PE_DIR" "$FM_DEFAULT_AP_VEC" "$FM_DEFAULT_PA_VEC" <<'PY'
import collections
import json
import math
import sys
from pathlib import Path

raw = Path(sys.argv[1])
acq_out = Path(sys.argv[2])
qa_out = Path(sys.argv[3])
pe_mode = sys.argv[4].strip().lower()
ap_override = sys.argv[5].strip()
pa_override = sys.argv[6].strip()
default_ap_vec = sys.argv[7].strip()
default_pa_vec = sys.argv[8].strip()

def die(msg, code=2):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def parse_vec(v):
    parts = v.split()
    if len(parts) != 3:
        die(f"Invalid PE vector '{v}'")
    return [int(float(x)) for x in parts]

def bids_dir_to_vec(d):
    if d == "i": return [1, 0, 0]
    if d == "i-": return [-1, 0, 0]
    if d == "j": return [0, 1, 0]
    if d == "j-": return [0, -1, 0]
    if d == "k": return [0, 0, 1]
    if d == "k-": return [0, 0, -1]
    return None

def load_json(p):
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}

def readout(j):
    if "TotalReadoutTime" in j:
        return float(j["TotalReadoutTime"])
    ees = j.get("EffectiveEchoSpacing")
    rpe = j.get("ReconMatrixPE")
    if ees is not None and rpe is not None:
        return float(ees) * (int(rpe) - 1)
    return math.nan

def mean_valid(values):
    vv = [x for x in values if x == x]
    return float(sum(vv) / len(vv)) if vv else math.nan

ap_niis = sorted(raw.glob("AP_S*_R*.nii.gz"))
pa_niis = sorted(raw.glob("PA_S*_R*.nii.gz"))
if not ap_niis or not pa_niis:
    die(f"Missing AP/PA nii.gz in {raw}")

ap_jsons = [raw / (p.name[:-7] + ".json") for p in ap_niis]
pa_jsons = [raw / (p.name[:-7] + ".json") for p in pa_niis]

ap_ro, pa_ro = [], []
ap_dirs, pa_dirs = [], []
lines = [
    f"Number of AP Field Maps: {len(ap_niis)}",
    f"Number of PA Field Maps: {len(pa_niis)}",
]

for apn in ap_niis:
    tag = apn.name[:-7]
    pan = raw / ("PA_" + tag[3:] + ".nii.gz")
    if not pan.exists():
        lines.append(f"Pair ?: {tag} [MISSING_PA] + PA_{tag[3:]} [MISSING]")
        continue
    apj = load_json(raw / (tag + ".json"))
    paj = load_json(raw / ("PA_" + tag[3:] + ".json"))
    apd = str(apj.get("PhaseEncodingDirection", "Unknown"))
    pad = str(paj.get("PhaseEncodingDirection", "Unknown"))
    ap_dirs.append(apd)
    pa_dirs.append(pad)
    ap_ro.append(readout(apj))
    pa_ro.append(readout(paj))
    lines.append(f"Pair {tag[2:]} : {tag} [{apd}] + PA_{tag[3:]} [{pad}]")

ap_mean = mean_valid(ap_ro)
pa_mean = mean_valid(pa_ro)

def choose_dir(dirs, label):
    c = collections.Counter([d for d in dirs if d in {"i","i-","j","j-","k","k-"}])
    if not c:
        return None
    return c.most_common(1)[0][0]

if pe_mode == "config":
    ap_dir = ap_override or None
    pa_dir = pa_override or None
else:
    ap_dir = ap_override or choose_dir(ap_dirs, "AP")
    pa_dir = pa_override or choose_dir(pa_dirs, "PA")

ap_vec = bids_dir_to_vec(ap_dir) if ap_dir else parse_vec(default_ap_vec)
pa_vec = bids_dir_to_vec(pa_dir) if pa_dir else parse_vec(default_pa_vec)

if ap_mean != ap_mean and pa_mean != pa_mean:
    die("Could not infer TotalReadoutTime from JSONs; add TotalReadoutTime or EffectiveEchoSpacing+ReconMatrixPE")
if ap_mean != ap_mean:
    ap_mean = pa_mean
if pa_mean != pa_mean:
    pa_mean = ap_mean

acq_out.parent.mkdir(parents=True, exist_ok=True)
acq_out.write_text(
    f"{ap_vec[0]} {ap_vec[1]} {ap_vec[2]} {ap_mean}\n"
    f"{pa_vec[0]} {pa_vec[1]} {pa_vec[2]} {pa_mean}\n"
)
lines.append(f"acqparams AP row: {ap_vec[0]} {ap_vec[1]} {ap_vec[2]} {ap_mean}")
lines.append(f"acqparams PA row: {pa_vec[0]} {pa_vec[1]} {pa_vec[2]} {pa_mean}")
qa_out.parent.mkdir(parents=True, exist_ok=True)
qa_out.write_text("\n".join(lines) + "\n")
print(f"Wrote {acq_out}")
print(f"Wrote {qa_out}")
PY

mapfile -t AP_FILES < <(ls -1 "$RAW_FM_DIR"/AP_S*_R*.nii.gz 2>/dev/null | sort || true)
TAGS=()
for ap in "${AP_FILES[@]}"; do
  tag="$(basename "$ap")"
  tag="${tag#AP_}"
  tag="${tag%.nii.gz}"
  pa="$RAW_FM_DIR/PA_${tag}.nii.gz"
  [[ -f "$pa" ]] || continue
  ses="${tag#S}"; ses="${ses%%_*}"
  if [[ "$ses" -ge "$StartSession" ]]; then
    TAGS+=( "$tag" )
  fi
done
[[ "${#TAGS[@]}" -gt 0 ]] || die "No AP/PA tags found at/after StartSession=$StartSession"

log "Fieldmap tags: ${TAGS[*]}"

topup_one() {
  local raw_fm_dir="$1"
  local fm_dir="$2"
  local acq="$3"
  local tag="$4"
  local TOPUP_CONFIG="$5"
  local OUTROOT="$fm_dir/AllFMs/topup/$tag"
  mkdir -p "$OUTROOT"

  cp -f "$raw_fm_dir/AP_${tag}.nii.gz" "$OUTROOT/AP_${tag}.nii.gz"
  cp -f "$raw_fm_dir/PA_${tag}.nii.gz" "$OUTROOT/PA_${tag}.nii.gz"

  local nVols
  nVols="$(fslnvols "$OUTROOT/AP_${tag}.nii.gz")"
  if [[ "$nVols" -gt 1 ]]; then
    mcflirt -in "$OUTROOT/AP_${tag}.nii.gz" -out "$OUTROOT/AP_${tag}.nii.gz" >/dev/null 2>&1
    fslmaths "$OUTROOT/AP_${tag}.nii.gz" -Tmean "$OUTROOT/AP_${tag}.nii.gz" >/dev/null 2>&1
    mcflirt -in "$OUTROOT/PA_${tag}.nii.gz" -out "$OUTROOT/PA_${tag}.nii.gz" >/dev/null 2>&1
    fslmaths "$OUTROOT/PA_${tag}.nii.gz" -Tmean "$OUTROOT/PA_${tag}.nii.gz" >/dev/null 2>&1
  fi

  fslmerge -t "$OUTROOT/AP_PA_${tag}.nii.gz" "$OUTROOT/AP_${tag}.nii.gz" "$OUTROOT/PA_${tag}.nii.gz" >/dev/null 2>&1
  topup --imain="$OUTROOT/AP_PA_${tag}.nii.gz" \
    --datain="$acq" \
    --iout="$OUTROOT/FM_mag_${tag}.nii.gz" \
    --fout="$OUTROOT/FM_hz_${tag}.nii.gz" \
    --config="$TOPUP_CONFIG" >/dev/null 2>&1
  fslmaths "$OUTROOT/FM_hz_${tag}.nii.gz" -mul 6.283 "$OUTROOT/FM_rads_${tag}.nii.gz" >/dev/null 2>&1
  fslmaths "$OUTROOT/FM_mag_${tag}.nii.gz" -Tmean "$OUTROOT/FM_mag_${tag}.nii.gz" >/dev/null 2>&1
}
export -f topup_one

parallel --jobs "$NTHREADS" topup_one ::: "$RAW_FM_DIR" ::: "$FM_DIR" ::: "$ACQ" ::: "${TAGS[@]}" ::: "$TOPUP_CONFIG" \
  >"$LOG_DIR/topup_parallel.log" 2>&1 || die "TOPUP failed. See $LOG_DIR/topup_parallel.log"

for tag in "${TAGS[@]}"; do
  OUTROOT="$TOPUP_DIR/$tag"
  register_fieldmap_to_acpc "$tag" "$OUTROOT"
  if [[ "$CLEAN_INTERMEDIATE" == "1" ]]; then
    rm -rf "$OUTROOT"
  fi
done

elif [[ "$DISTORTION_CORRECTION_MODE" == "phasediff" ]]; then
  PHASEDIFF_MANIFEST="$FM_DIR/phasediff_inputs.tsv"
  write_phasediff_manifest "$PHASEDIFF_MANIFEST" "$QA_DIR/PhasediffFieldMap.txt"
  : > "$LOG_DIR/phasediff.log"

  while IFS=$'\t' read -r tag phase mag1 mag2 delta_te_ms; do
    [[ "$tag" == "tag" ]] && continue
    OUTROOT="$PHASEDIFF_DIR/$tag"
    mkdir -p "$OUTROOT"
    MAG_INPUT="$OUTROOT/Magnitude_${tag}.nii.gz"
    if [[ "$mag1" != "-" && "$mag2" != "-" ]]; then
      fslmerge -t "$MAG_INPUT" "$mag1" "$mag2" >>"$LOG_DIR/phasediff.log" 2>&1
    elif [[ "$mag1" != "-" ]]; then
      cp -f "$mag1" "$MAG_INPUT"
    else
      cp -f "$mag2" "$MAG_INPUT"
    fi

    log "HCP FieldMapPreprocessingAll phasediff tag ${tag} (DeltaTE=${delta_te_ms} ms)"
    bash "$FIELD_MAP_PREPROCESSING_SCRIPT" \
      --workingdir="$OUTROOT/FieldMap" \
      --method="SiemensFieldMap" \
      --fmapmag="$MAG_INPUT" \
      --fmapphase="$phase" \
      --echodiff="$delta_te_ms" \
      --ofmapmag="$OUTROOT/FM_mag_${tag}" \
      --ofmapmagbrain="$OUTROOT/FM_mag_brain_${tag}" \
      --ofmap="$OUTROOT/FM_rads_${tag}" \
      --gdcoeffs="$PHASEDIFF_GDCOEFFS" >>"$LOG_DIR/phasediff.log" 2>&1

    register_fieldmap_to_acpc "$tag" "$OUTROOT"
    if [[ "$CLEAN_INTERMEDIATE" == "1" ]]; then
      rm -rf "$OUTROOT"
    fi
  done < "$PHASEDIFF_MANIFEST"
fi

mapfile -t RADS < <(ls -1 "$ALL_DIR"/FM_rads_acpc_S*_R*.nii.gz 2>/dev/null | sort || true)
mapfile -t MAG < <(ls -1 "$ALL_DIR"/FM_mag_acpc_S*_R*.nii.gz 2>/dev/null | sort || true)
mapfile -t MAGB < <(ls -1 "$ALL_DIR"/FM_mag_acpc_brain_S*_R*.nii.gz 2>/dev/null | sort || true)
[[ "${#RADS[@]}" -ge 1 && "${#MAG[@]}" -ge 1 ]] || die "No scan-specific FM outputs generated"

fslmerge -t "$FM_DIR/Avg_FM_rads_acpc.nii.gz" "${RADS[@]}" >/dev/null 2>&1
fslmaths "$FM_DIR/Avg_FM_rads_acpc.nii.gz" -Tmean "$FM_DIR/Avg_FM_rads_acpc.nii.gz" >/dev/null 2>&1
fslmerge -t "$FM_DIR/Avg_FM_mag_acpc.nii.gz" "${MAG[@]}" >/dev/null 2>&1
fslmaths "$FM_DIR/Avg_FM_mag_acpc.nii.gz" -Tmean "$FM_DIR/Avg_FM_mag_acpc.nii.gz" >/dev/null 2>&1

if [[ "${#MAGB[@]}" -ge 1 ]]; then
  fslmerge -t "$FM_DIR/Avg_FM_mag_acpc_brain.nii.gz" "${MAGB[@]}" >/dev/null 2>&1
  fslmaths "$FM_DIR/Avg_FM_mag_acpc_brain.nii.gz" -Tmean "$FM_DIR/Avg_FM_mag_acpc_brain.nii.gz" >/dev/null 2>&1
else
  fslmaths "$FM_DIR/Avg_FM_mag_acpc.nii.gz" -mas "$T1B" "$FM_DIR/Avg_FM_mag_acpc_brain.nii.gz" >/dev/null 2>&1
fi

rm -rf "$Subdir/anat/T1w/freesurfer" >/dev/null 2>&1 || true
log "Fieldmap module complete."
