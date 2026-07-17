#!/usr/bin/env python3
"""Import the NVD BIDS-like dataset into the pfm-mefmri raw layout.

The source dataset encodes run identity in the BIDS task label and spreads one
logical acquisition group over several ses-<group>xx directories.  This
importer applies the fixed study mapping requested for NVD:

  ses-1xx task-s1..s11       -> session_1/run_1..run_11
  ses-2xx task-s1..s11       -> session_2/run_12..run_22
  ses-3xx task-s1..s11       -> session_3/run_23..run_33
  ses-4xx task-floc1..floc12 -> session_4/run_34..run_45
  ses-5xx task-prf931, prf932, prf933, prf941, prf942, prf943
                              -> session_5/run_46..run_51

Only Python's standard library is required.  Source files are never modified.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


class ImportAbort(RuntimeError):
    """Raised for an input ambiguity that must not be resolved silently."""


PRF_TASKS: Sequence[str] = ("prf931", "prf932", "prf933", "prf941", "prf942", "prf943")
NII_SUFFIXES: Sequence[str] = (".nii.gz", ".nii")


@dataclass(frozen=True)
class RunRecord:
    source_session: str
    source_task: str
    pipeline_session: int
    pipeline_run: int
    bold: Path
    bold_json: Path


def strip_nii_suffix(path: Path) -> Path:
    name = path.name
    if name.endswith(".nii.gz"):
        return path.with_name(name[:-7])
    if name.endswith(".nii"):
        return path.with_name(name[:-4])
    raise ImportAbort(f"Not a NIfTI filename: {path}")


def json_sidecar(path: Path) -> Path:
    return strip_nii_suffix(path).with_suffix(".json")


def normalized_subject(value: str) -> str:
    return value if value.startswith("sub-") else f"sub-{value}"


def parse_bold_name(path: Path) -> Tuple[str, str]:
    match = re.search(r"_ses-([^_]+)_task-([^_]+)_bold\.nii(?:\.gz)?$", path.name)
    if not match:
        raise ImportAbort(f"Cannot parse NVD BOLD filename: {path}")
    return match.group(1), match.group(2)


def nvd_run_mapping(session_label: str, task: str) -> Optional[Tuple[int, int]]:
    if not session_label.isdigit():
        return None
    group = int(session_label) // 100
    if group in (1, 2, 3):
        match = re.fullmatch(r"s([1-9]|1[01])", task)
        if not match:
            return None
        task_index = int(match.group(1))
        return group, (group - 1) * 11 + task_index
    if group == 4:
        match = re.fullmatch(r"floc([1-9]|1[0-2])", task)
        if not match:
            return None
        return 4, 33 + int(match.group(1))
    if group == 5 and task in PRF_TASKS:
        return 5, 46 + PRF_TASKS.index(task)
    return None


def iter_nifti(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.nii.gz"):
        if path.is_file():
            yield path
    for path in root.rglob("*.nii"):
        if path.is_file():
            yield path


def collect_runs(subject_dir: Path) -> Tuple[List[RunRecord], List[Path]]:
    records: Dict[Tuple[int, int], RunRecord] = {}
    ignored: List[Path] = []
    for bold in sorted(iter_nifti(subject_dir)):
        if bold.parent.name != "func" or "_bold.nii" not in bold.name:
            continue
        source_session, task = parse_bold_name(bold)
        mapped = nvd_run_mapping(source_session, task)
        if mapped is None:
            ignored.append(bold)
            continue
        sidecar = json_sidecar(bold)
        if not sidecar.is_file():
            raise ImportAbort(f"Missing BOLD JSON sidecar: {sidecar}")
        key = mapped
        record = RunRecord(source_session, task, mapped[0], mapped[1], bold, sidecar)
        if key in records:
            previous = records[key]
            raise ImportAbort(
                "Duplicate NVD mapping for "
                f"session_{key[0]}/run_{key[1]}: {previous.bold} and {bold}"
            )
        records[key] = record
    if not records:
        raise ImportAbort(f"No NVD-mapped BOLD files found under {subject_dir}")
    return sorted(records.values(), key=lambda r: (r.pipeline_session, r.pipeline_run)), ignored


def ensure_target(dst: Path, overwrite: bool, dry_run: bool) -> None:
    if not dst.exists() and not dst.is_symlink():
        return
    if not overwrite:
        raise ImportAbort(f"Destination exists (use --overwrite): {dst}")
    if dry_run:
        return
    if dst.is_dir() and not dst.is_symlink():
        shutil.rmtree(dst)
    else:
        dst.unlink()


def transfer(src: Path, dst: Path, mode: str, overwrite: bool, dry_run: bool) -> None:
    ensure_target(dst, overwrite, dry_run)
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "copy":
        shutil.copy2(src, dst)
    else:
        os.symlink(src.resolve(), dst)


def transfer_nifti_with_json(
    src: Path, dst: Path, mode: str, overwrite: bool, dry_run: bool, require_json: bool = True
) -> None:
    transfer(src, dst, mode, overwrite, dry_run)
    src_json = json_sidecar(src)
    dst_json = json_sidecar(dst)
    if src_json.is_file():
        transfer(src_json, dst_json, mode, overwrite, dry_run)
    elif require_json:
        raise ImportAbort(f"Missing JSON sidecar: {src_json}")


def import_anatomy(
    subject_dir: Path, out_subject_dir: Path, mode: str, overwrite: bool, dry_run: bool
) -> int:
    t1_files = sorted(
        p for p in iter_nifti(subject_dir) if p.parent.name == "anat" and "_T1w.nii" in p.name
    )
    for index, src in enumerate(t1_files, start=1):
        dst = out_subject_dir / "anat" / "unprocessed" / "T1w" / f"T1w_{index}.nii.gz"
        transfer_nifti_with_json(src, dst, mode, overwrite, dry_run)
    return len(t1_files)


def import_bold(
    records: Sequence[RunRecord],
    out_subject_dir: Path,
    func_dirname: str,
    func_prefix: str,
    mode: str,
    overwrite: bool,
    dry_run: bool,
) -> None:
    root = out_subject_dir / "func" / "unprocessed" / func_dirname
    for record in records:
        dst = (
            root
            / f"session_{record.pipeline_session}"
            / f"run_{record.pipeline_run}"
            / f"{func_prefix}_S{record.pipeline_session}_R{record.pipeline_run}_E1.nii.gz"
        )
        transfer_nifti_with_json(record.bold, dst, mode, overwrite, dry_run)


def fmap_candidates(subject_dir: Path, source_session: str, suffix: str) -> List[Path]:
    ses_dir = subject_dir / f"ses-{source_session}" / "fmap"
    if not ses_dir.is_dir():
        return []
    return sorted(p for p in iter_nifti(ses_dir) if p.name.endswith(f"_{suffix}.nii.gz") or p.name.endswith(f"_{suffix}.nii"))


def intended_for_contains(fmap: Path, bold: Path, subject_dir: Path) -> bool:
    sidecar = json_sidecar(fmap)
    if not sidecar.is_file():
        return False
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImportAbort(f"Cannot read field-map JSON {sidecar}: {exc}") from exc
    intended = payload.get("IntendedFor", [])
    if isinstance(intended, str):
        intended = [intended]
    try:
        rel = bold.relative_to(subject_dir).as_posix()
    except ValueError:
        rel = bold.name
    keys = {bold.name, rel, f"bids::{rel}"}
    return any(str(item).replace("\\", "/").removeprefix("bids::") in keys for item in intended)


def choose_fmap(subject_dir: Path, record: RunRecord, suffix: str) -> Path:
    candidates = fmap_candidates(subject_dir, record.source_session, suffix)
    if not candidates:
        raise ImportAbort(
            f"Missing {suffix} field map for {record.bold} in ses-{record.source_session}/fmap"
        )
    intended = [p for p in candidates if intended_for_contains(p, record.bold, subject_dir)]
    if len(intended) == 1:
        return intended[0]
    if len(candidates) == 1:
        return candidates[0]
    if len(intended) > 1:
        raise ImportAbort(f"Multiple {suffix} field maps IntendedFor {record.bold}: {intended}")
    raise ImportAbort(f"Ambiguous {suffix} field maps for {record.bold}: {candidates}")


def import_phasediff(
    subject_dir: Path,
    records: Sequence[RunRecord],
    out_subject_dir: Path,
    func_dirname: str,
    mode: str,
    overwrite: bool,
    dry_run: bool,
) -> Dict[Tuple[int, int], Path]:
    out_root = out_subject_dir / "func" / "unprocessed" / func_dirname / "field_maps"
    used: Dict[Tuple[int, int], Path] = {}
    names = {"phasediff": "PhaseDiff", "magnitude1": "Magnitude1", "magnitude2": "Magnitude2"}
    for record in records:
        for suffix, prefix in names.items():
            candidates = fmap_candidates(subject_dir, record.source_session, suffix)
            if suffix == "magnitude2" and not candidates:
                continue
            src = choose_fmap(subject_dir, record, suffix)
            dst = out_root / f"{prefix}_S{record.pipeline_session}_R{record.pipeline_run}.nii.gz"
            transfer_nifti_with_json(src, dst, mode, overwrite, dry_run)
            if suffix == "phasediff":
                used[(record.pipeline_session, record.pipeline_run)] = src
    return used


def write_manifest(
    out_subject_dir: Path,
    records: Sequence[RunRecord],
    fmaps: Dict[Tuple[int, int], Path],
    dry_run: bool,
) -> Path:
    path = out_subject_dir / "nvd_import_manifest.tsv"
    if dry_run:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            ["source_session", "source_task", "pipeline_session", "pipeline_run", "source_bold", "source_phasediff"]
        )
        for record in records:
            writer.writerow(
                [
                    f"ses-{record.source_session}",
                    f"task-{record.source_task}",
                    record.pipeline_session,
                    record.pipeline_run,
                    str(record.bold),
                    str(fmaps.get((record.pipeline_session, record.pipeline_run), "")),
                ]
            )
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import NVD task-as-run data into pfm-mefmri layout")
    parser.add_argument("bids_root", help="NVD source root containing sub-* directories")
    parser.add_argument("subject", help="Subject label, e.g. sub-001 or 001")
    parser.add_argument("out_subject_dir", help="Destination subject directory")
    parser.add_argument("--func-dirname", default="nvd", help="Pipeline functional directory name (default: nvd)")
    parser.add_argument("--func-prefix", default="NVD", help="Pipeline functional file prefix (default: NVD)")
    parser.add_argument("--fieldmap-mode", choices=("phasediff", "none"), default="phasediff")
    parser.add_argument("--mode", choices=("symlink", "copy"), default="symlink")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the mapping without writing")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    bids_root = Path(args.bids_root).expanduser().resolve()
    subject = normalized_subject(args.subject)
    subject_dir = bids_root / subject
    out_subject_dir = Path(args.out_subject_dir).expanduser().resolve()
    if not subject_dir.is_dir():
        print(f"ERROR: missing source subject directory: {subject_dir}", file=sys.stderr)
        return 2

    try:
        records, ignored = collect_runs(subject_dir)
        t1_count = import_anatomy(subject_dir, out_subject_dir, args.mode, args.overwrite, args.dry_run)
        import_bold(
            records,
            out_subject_dir,
            args.func_dirname,
            args.func_prefix,
            args.mode,
            args.overwrite,
            args.dry_run,
        )
        if args.fieldmap_mode == "phasediff":
            fmaps = import_phasediff(
                subject_dir,
                records,
                out_subject_dir,
                args.func_dirname,
                args.mode,
                args.overwrite,
                args.dry_run,
            )
        else:
            fmaps = {}
        manifest = write_manifest(out_subject_dir, records, fmaps, args.dry_run)
    except ImportAbort as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("NVD import validation complete." if args.dry_run else "NVD import complete.")
    print(f"  Subject: {subject}")
    print(f"  Source: {subject_dir}")
    print(f"  Destination: {out_subject_dir}")
    print(f"  Mapped BOLD runs: {len(records)}")
    print(f"  Pipeline sessions: {','.join(str(x) for x in sorted({r.pipeline_session for r in records}))}")
    print(f"  Run range: {min(r.pipeline_run for r in records)}-{max(r.pipeline_run for r in records)}")
    print(f"  T1w files: {t1_count}")
    print(f"  Ignored non-NVD BOLD files: {len(ignored)}")
    print(f"  Manifest: {manifest}")
    if t1_count == 0:
        print("WARNING: no T1w was found; the full preprocessing pipeline requires a T1w image.", file=sys.stderr)
    for record in records:
        print(
            f"  ses-{record.source_session}/task-{record.source_task} -> "
            f"session_{record.pipeline_session}/run_{record.pipeline_run}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
