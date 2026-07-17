#!/usr/bin/env python3
"""
Build a Workbench/wb_surfer2 crawling seed-FC movie from a dtseries CIFTI.

The output layout is compact for pipeline QC:

  <out-dir>/
    FlatMaps+Inflated_<subject>.scene
    VerticesToSample.txt
    <subject>.mp4
    <subject>/  (temporary; deleted after rendering by default)
      <subject>.dtseries.nii  -> input dtseries symlink by default
      <subject>.dconn.nii

Example:
  python make_crawling_seed_fc_movie.py \
    --dtseries Rest_E1+aCompCor_Concatenated+FDlt0p3.dtseries.nii \
    --subject sub-UPENN \
    --out-dir crawling_seed_fc \
    --wbsurfer-conda-env wbsurfer_env
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from crawling_seed_render import prepare_wbsurfer_environment, preflight_scene_render
from crawling_seed_scene import (
    isolate_scene_document,
    scene_document_needs_pruning,
    scene_render_resource_values,
)


DEFAULT_SCENE = Path(__file__).resolve().parents[1] / "res0urces" / "CrawlingSeedFC" / "FlatMaps+Inflated.scene"
DEFAULT_VERTICES = Path(__file__).resolve().parents[1] / "res0urces" / "CrawlingSeedFC" / "VerticesToSample.txt"

CACHE_MANIFEST_SCHEMA_VERSION = 1
RENDER_RECIPE_VERSION = 2


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    print("[RUN] " + " ".join(str(x) for x in cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True, env=env)


def check_output(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"Missing {label}: {path}")


def ensure_dtseries_link(src: Path, dst: Path, *, copy_dtseries: bool, force: bool) -> None:
    """Ensure an existing scratch input still represents the requested CIFTI."""
    src = src.resolve()
    if dst.exists() or dst.is_symlink():
        replace = force
        if not replace and copy_dtseries:
            if dst.is_symlink() or not dst.is_file():
                replace = True
            else:
                src_stat = src.stat()
                dst_stat = dst.stat()
                replace = (
                    src_stat.st_size != dst_stat.st_size
                    or src_stat.st_mtime_ns != dst_stat.st_mtime_ns
                )
        elif not replace:
            try:
                replace = not dst.is_symlink() or dst.resolve(strict=True) != src
            except FileNotFoundError:
                replace = True
        if not replace:
            return
        if dst.is_dir() and not dst.is_symlink():
            raise SystemExit(f"Expected a dtseries file/link, found directory: {dst}")
        dst.unlink()

    if copy_dtseries:
        shutil.copy2(src, dst)
    else:
        dst.symlink_to(src)


def file_identity(path: Path) -> dict[str, int | str]:
    """Return a cheap, stable identity for large immutable pipeline inputs."""
    resolved = path.resolve()
    stat_result = resolved.stat()
    return {
        "path": resolved.as_posix(),
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
    }


def build_dconn_request(
    dtseries: Path,
    weights: Path | None,
) -> dict[str, object]:
    return {
        "dtseries": file_identity(dtseries),
        "weights": file_identity(weights) if weights is not None else None,
    }


def build_artifact_manifest(
    request: dict[str, object],
    artifact: Path,
) -> dict[str, object]:
    return {
        "schema_version": CACHE_MANIFEST_SCHEMA_VERSION,
        "request": request,
        "artifact": file_identity(artifact),
    }


def manifest_matches(path: Path, expected: dict[str, object]) -> bool:
    if not path.is_file():
        return False
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return actual == expected


def artifact_manifest_matches(
    manifest_path: Path,
    expected_request: dict[str, object],
    artifact: Path,
) -> bool:
    if not artifact.is_file():
        return False
    expected = build_artifact_manifest(expected_request, artifact)
    return manifest_matches(manifest_path, expected)


def write_json_manifest(path: Path, manifest: dict[str, object]) -> None:
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def target_relative_dconn_pattern(subject: str, *, require_parent: bool = False) -> re.Pattern[str]:
    """Match an XML text value that points to this subject's relative dconn."""
    subject_re = re.escape(subject)
    parent_dirs = r"(?:\.\./)+" if require_parent else r"(?:\.\./)*"
    return re.compile(
        rf"(?<=>){parent_dirs}{subject_re}/{subject_re}\.dconn\.nii(?=<)"
    )


def rewrite_scene_dconn_paths(text: str, *, subject: str, dconn_abs: str) -> str:
    """Canonicalize dconn references while preserving unrelated saved scenes."""
    target_pattern = target_relative_dconn_pattern(subject)
    text = target_pattern.sub(lambda _match: dconn_abs, text)

    # Older saved scenes use this separate BlindedRatings layout. Keep the
    # historical behavior, but use a callable replacement so Windows paths are
    # never interpreted as regular-expression replacement escapes.
    text = re.sub(
        r"(?<=>)\.\./\.\./\.\./BlindedRatings/sub-[^/<]+/sub-[^/<]+\.dconn\.nii(?=<)",
        lambda _match: dconn_abs,
        text,
    )
    text = re.sub(
        r"sub-[A-Za-z0-9]+\.dconn\.nii",
        lambda _match: f"{subject}.dconn.nii",
        text,
    )

    stale_target = target_relative_dconn_pattern(subject, require_parent=True)
    if stale_target.search(text):
        raise SystemExit(
            f"Failed to rewrite relative dconn path for {subject} in cloned scene"
        )
    if dconn_abs not in text:
        raise SystemExit(
            f"Cloned scene does not reference the target dconn for {subject}: {dconn_abs}"
        )
    return text


def scene_has_stale_target_dconn(scene_path: Path, subject: str) -> bool:
    """Return True when an existing generated scene has the known bad path."""
    text = scene_path.read_text(encoding="utf-8", errors="surrogateescape")
    return target_relative_dconn_pattern(subject, require_parent=True).search(text) is not None


def rewrite_scene_self_references(text: str, *, scene_abs: str) -> str:
    """Point saved-scene self references at the generated scene file."""
    text = re.sub(
        r"(?<=>)\.\./\.\./\.\./BlindedRatings/Movies/FlatMaps\+Inflated\.scene(?=<)",
        lambda _match: scene_abs,
        text,
    )
    text = re.sub(
        r"(?<=>)FlatMaps\+Inflated\.scene(?=<)",
        lambda _match: scene_abs,
        text,
    )
    if re.search(r"(?<=>)FlatMaps\+Inflated\.scene(?=<)", text):
        raise SystemExit("Failed to rewrite generated scene self reference")
    return text


def resolved_scene_render_resources(
    scene_path: Path,
    subject: str,
    *,
    text: str | None = None,
) -> set[str]:
    """Return normalized absolute render-resource paths from one scene."""
    if text is None:
        text = scene_path.read_text(encoding="utf-8", errors="surrogateescape")
    try:
        values = scene_render_resource_values(text, subject)
    except ValueError as exc:
        raise SystemExit(f"Invalid generated scene resources: {exc}") from exc

    resources: set[str] = set()
    for value in values:
        path = Path(value)
        if not path.is_absolute():
            path = scene_path.parent / path
        resources.add(path.resolve().as_posix())
    return resources


def scene_has_stale_generated_paths(
    scene_path: Path,
    subject: str,
    *,
    expected_resources: set[str] | None = None,
) -> bool:
    """Return True when a generated scene needs path or content migration."""
    text = scene_path.read_text(encoding="utf-8", errors="surrogateescape")
    stale_dconn = target_relative_dconn_pattern(subject, require_parent=True).search(text)
    stale_self_reference = re.search(r"(?<=>)FlatMaps\+Inflated\.scene(?=<)", text)
    try:
        actual_resources = resolved_scene_render_resources(
            scene_path,
            subject,
            text=text,
        )
    except SystemExit:
        return True
    return (
        stale_dconn is not None
        or stale_self_reference is not None
        or scene_document_needs_pruning(text, subject)
        or (
            expected_resources is not None
            and actual_resources != expected_resources
        )
    )


def require_scene_render_resources(
    scene_path: Path,
    subject: str,
    expected_resources: set[str] | None = None,
) -> set[str]:
    """Validate all scene resources before starting Workbench rendering."""
    resources = resolved_scene_render_resources(scene_path, subject)
    if expected_resources is not None and resources != expected_resources:
        missing = sorted(expected_resources - resources)
        unexpected = sorted(resources - expected_resources)
        details: list[str] = []
        if missing:
            details.append("missing expected paths:\n" + "\n".join(f"  {p}" for p in missing))
        if unexpected:
            details.append("unexpected paths:\n" + "\n".join(f"  {p}" for p in unexpected))
        raise SystemExit(
            f"Generated scene resources do not match {subject}:\n"
            + "\n".join(details)
        )
    missing_files = sorted(path for path in resources if not Path(path).is_file())
    if missing_files:
        raise SystemExit(
            "Generated scene references missing render resources:\n"
            + "\n".join(f"  {path}" for path in missing_files)
        )
    print(f"[SCENE] Validated {len(resources)} render resource path(s)")
    return resources


def clone_scene(
    template_scene: Path,
    scene_out: Path,
    template_subject: str,
    subject: str,
    surface_resource_dir: Path | None,
    surface_subject_prefix: str | None,
    flat_surface_resource_dir: Path | None,
    flat_surface_subject_prefix: str | None,
    dconn_path: Path,
) -> None:
    template_text = template_scene.read_text(encoding="utf-8", errors="surrogateescape")
    try:
        text, removed_palettes = isolate_scene_document(template_text, template_subject)
    except ValueError as exc:
        raise SystemExit(f"Failed to isolate template scene: {exc}") from exc
    if removed_palettes:
        print(f"[SCENE] Removed legacy palette file reference(s): {', '.join(removed_palettes)}")
    text = text.replace(template_subject, subject)
    if surface_resource_dir is not None:
        surface_root = str(surface_resource_dir.resolve())
        surface_prefix = surface_subject_prefix or infer_surface_subject_prefix(surface_resource_dir)
        flat_root = str((flat_surface_resource_dir or surface_resource_dir).resolve())
        flat_prefix = flat_surface_subject_prefix or surface_prefix
        for hemi in ("L", "R"):
            for surf in ("flat", "sphere"):
                text = text.replace(
                    f"../../../../../../../home/charleslynch/res0urces/HCP_S1200_GroupAvg_v1/S1200.{hemi}.{surf}.32k_fs_LR.surf.gii",
                    f"{flat_root}/{flat_prefix}.{hemi}.{surf}.32k_fs_LR.surf.gii",
                )
                text = text.replace(
                    f"/home/charleslynch/home/charleslynch/res0urces/HCP_S1200_GroupAvg_v1/S1200.{hemi}.{surf}.32k_fs_LR.surf.gii",
                    f"{flat_root}/{flat_prefix}.{hemi}.{surf}.32k_fs_LR.surf.gii",
                )
                text = text.replace(
                    f"S1200.{hemi}.{surf}.32k_fs_LR.surf.gii",
                    f"{flat_prefix}.{hemi}.{surf}.32k_fs_LR.surf.gii",
                )
            for surf in ("inflated", "midthickness", "pial", "very_inflated", "white"):
                text = text.replace(
                    f"../../../../../../../home/charleslynch/res0urces/HCP_S1200_GroupAvg_v1/S1200.{hemi}.{surf}_MSMAll.32k_fs_LR.surf.gii",
                    f"{surface_root}/{surface_prefix}.{hemi}.{surf}.32k_fs_LR.surf.gii",
                )
                text = text.replace(
                    f"/home/charleslynch/home/charleslynch/res0urces/HCP_S1200_GroupAvg_v1/S1200.{hemi}.{surf}_MSMAll.32k_fs_LR.surf.gii",
                    f"{surface_root}/{surface_prefix}.{hemi}.{surf}.32k_fs_LR.surf.gii",
                )
                text = text.replace(
                    f"S1200.{hemi}.{surf}_MSMAll.32k_fs_LR.surf.gii",
                    f"{surface_prefix}.{hemi}.{surf}.32k_fs_LR.surf.gii",
                )
    dconn_abs = dconn_path.resolve().as_posix()
    text = rewrite_scene_dconn_paths(text, subject=subject, dconn_abs=dconn_abs)
    scene_abs = scene_out.resolve().as_posix()
    text = rewrite_scene_self_references(text, scene_abs=scene_abs)
    if scene_document_needs_pruning(text, subject):
        raise SystemExit(
            f"Cloned scene failed single-scene validation for subject {subject!r}"
        )
    partial_scene = scene_out.with_name(f".{scene_out.name}.partial")
    partial_scene.write_text(text, encoding="utf-8", errors="surrogateescape")
    partial_scene.replace(scene_out)


def infer_surface_subject_prefix(surface_dir: Path) -> str:
    matches = sorted(surface_dir.glob("*.L.midthickness.32k_fs_LR.surf.gii"))
    if len(matches) != 1:
        raise SystemExit(
            "Expected exactly one surface subject prefix in "
            f"{surface_dir}, found {len(matches)}; set "
            "--surface-subject-prefix explicitly"
        )
    suffix = ".L.midthickness.32k_fs_LR.surf.gii"
    return matches[0].name[: -len(suffix)]


def require_scene_surfaces(surface_dir: Path, surface_prefix: str, flat_surface_dir: Path | None = None, flat_surface_prefix: str | None = None) -> list[Path]:
    missing: list[Path] = []
    surface_paths: list[Path] = []
    for hemi in ("L", "R"):
        for surf in ("inflated", "midthickness", "pial", "very_inflated", "white"):
            path = surface_dir / f"{surface_prefix}.{hemi}.{surf}.32k_fs_LR.surf.gii"
            surface_paths.append(path)
            if not path.is_file():
                missing.append(path)
        for surf in ("flat", "sphere"):
            path = (flat_surface_dir or surface_dir) / f"{flat_surface_prefix or surface_prefix}.{hemi}.{surf}.32k_fs_LR.surf.gii"
            surface_paths.append(path)
            if not path.is_file():
                missing.append(path)
    if missing:
        preview = "\n".join(f"  {path}" for path in missing[:8])
        extra = "" if len(missing) <= 8 else f"\n  ... and {len(missing) - 8} more"
        raise SystemExit(f"Missing scene surface files:\n{preview}{extra}")
    return surface_paths


def read_vertices(vertices_path: Path) -> list[str]:
    vertices: list[str] = []
    with vertices_path.open("r", encoding="utf-8") as f:
        for line in f:
            value = line.strip()
            if value and not value.startswith("#"):
                vertices.append(value)
    if not vertices:
        raise SystemExit(f"No vertices found in {vertices_path}")
    return vertices


def wb_surfer_command(args: argparse.Namespace) -> list[str]:
    if args.wbsurfer_bin:
        return [args.wbsurfer_bin]
    if args.wbsurfer_conda_env:
        return ["conda", "run", "-n", args.wbsurfer_conda_env, "wb_surfer2"]
    return ["wb_surfer2"]


def normalize_subject_name(value: str) -> str:
    """Return a subject label with exactly one leading ``sub-`` prefix."""
    normalized = value.strip()
    if not normalized:
        raise argparse.ArgumentTypeError("subject must have a non-empty label")
    while normalized.startswith("sub-sub-"):
        normalized = normalized[4:]
    if not normalized.startswith("sub-"):
        normalized = f"sub-{normalized}"
    label = normalized[4:]
    if not label:
        raise argparse.ArgumentTypeError("subject must have a non-empty label")
    if "/" in label or "\\" in label:
        raise argparse.ArgumentTypeError("subject must not contain path separators")
    return normalized


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def movie_duration_seconds(movie: Path, ffprobe_bin: str) -> float:
    output = check_output(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(movie),
        ]
    )
    try:
        duration = float(output)
    except ValueError as exc:
        raise SystemExit(f"Could not parse ffprobe duration for {movie}: {output!r}") from exc
    if duration <= 0:
        raise SystemExit(f"Movie duration must be positive for compression: {movie}")
    return duration


def existing_movie_is_valid(movie: Path, ffprobe_bin: str) -> bool:
    """Validate a cached MP4 and preserve invalid legacy partial outputs."""
    if not movie.is_file():
        return False
    try:
        duration = movie_duration_seconds(movie, ffprobe_bin)
    except (OSError, subprocess.CalledProcessError, SystemExit) as exc:
        invalid_movie = movie.with_name(
            f".{movie.stem}.invalid{movie.suffix}"
        )
        invalid_movie.unlink(missing_ok=True)
        movie.replace(invalid_movie)
        print(
            f"[REBUILD] Invalid movie cache preserved as {invalid_movie}: {exc}"
        )
        return False
    print(f"[CACHE] Validated existing movie ({duration:.1f}s): {movie}")
    return True


def compress_movie_to_target_size(
    *,
    source_movie: Path,
    output_movie: Path,
    target_size_mb: float,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    overwrite: bool,
) -> None:
    require_file(source_movie, "source movie")
    if output_movie.exists() and not overwrite:
        print(f"[SKIP] Existing compressed movie: {output_movie}")
        return

    duration = movie_duration_seconds(source_movie, ffprobe_bin)
    target_bits = target_size_mb * 1024 * 1024 * 8
    video_kbps = max(50, int((target_bits / duration) * 0.97 / 1000))
    passlog = output_movie.with_suffix(".ffmpeg2pass")
    partial_output = output_movie.with_name(
        f".{output_movie.stem}.partial{output_movie.suffix}"
    )
    partial_output.unlink(missing_ok=True)

    print(
        f"[INFO] Compressing to ~{target_size_mb:g} MB "
        f"({duration:.1f}s, video bitrate {video_kbps}k)"
    )
    first_pass = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(source_movie),
        "-an",
        "-c:v",
        "libx264",
        "-b:v",
        f"{video_kbps}k",
        "-pass",
        "1",
        "-passlogfile",
        str(passlog),
        "-f",
        "mp4",
        "/dev/null",
    ]
    second_pass = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(source_movie),
        "-an",
        "-c:v",
        "libx264",
        "-b:v",
        f"{video_kbps}k",
        "-pass",
        "2",
        "-passlogfile",
        str(passlog),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(partial_output),
    ]
    run(first_pass)
    run(second_pass)
    require_file(partial_output, "compressed movie")
    movie_duration_seconds(partial_output, ffprobe_bin)
    partial_output.replace(output_movie)
    print(f"[COMPRESS] Completed movie: {output_movie}")

    for log_path in output_movie.parent.glob(passlog.name + "*"):
        try:
            log_path.unlink()
        except FileNotFoundError:
            pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a dconn and wb_surfer2 crawling seed-FC movie from a dtseries CIFTI."
    )
    parser.add_argument("--dtseries", required=True, type=Path, help="Input .dtseries.nii CIFTI.")
    parser.add_argument(
        "--subject",
        required=True,
        type=normalize_subject_name,
        help="Scene/movie subject name; a single sub- prefix is enforced.",
    )
    parser.add_argument("--out-dir", required=True, type=Path, help="Output root.")
    parser.add_argument("--scene-template", default=DEFAULT_SCENE, type=Path)
    parser.add_argument("--vertices", default=DEFAULT_VERTICES, type=Path)
    parser.add_argument("--template-subject", default="sub-ME01")
    parser.add_argument(
        "--surface-resource-dir",
        default=None,
        type=Path,
        help="Directory containing subject-specific *.32k_fs_LR.surf.gii files for scene rendering.",
    )
    parser.add_argument("--surface-subject-prefix", default=None, help="Subject prefix used by surface filenames.")
    parser.add_argument("--flat-surface-resource-dir", default=None, type=Path, help="Directory containing subject-specific flat/sphere 32k surfaces.")
    parser.add_argument("--flat-surface-subject-prefix", default=None, help="Subject prefix used by flat/sphere surface filenames.")
    parser.add_argument("--wb-command", default="wb_command")
    parser.add_argument("--wbsurfer-bin", default=None, help="Path to wb_surfer2. Overrides --wbsurfer-conda-env.")
    parser.add_argument("--wbsurfer-conda-env", default=None, help="Conda env containing wb_surfer2.")
    parser.add_argument("--weights", type=Path, default=None, help="Optional weights file for wb_command.")
    parser.add_argument("--vertex-mode", default="CORTEX_LEFT", help="Surface name passed after --vertex-mode.")
    parser.add_argument("--width", type=positive_int, default=1920)
    parser.add_argument("--height", type=positive_int, default=1080)
    parser.add_argument("--framerate", type=positive_int, default=10)
    parser.add_argument("--num-cpus", type=positive_int, default=None)
    parser.add_argument(
        "--target-size-mb",
        type=positive_float,
        default=None,
        help="Approximate final MP4 size in MiB. Uses ffmpeg two-pass compression after wb_surfer2.",
    )
    parser.add_argument(
        "--keep-source-movie",
        action="store_true",
        help="Keep the larger pre-compression wb_surfer2 MP4 when --target-size-mb is used.",
    )
    parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg executable used for compression.")
    parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe executable used for compression.")
    parser.add_argument("--reverse", action="store_true", help="Append the reverse traversal.")
    parser.add_argument("--closed", action="store_true", help="Append the first vertex to close the traversal.")
    parser.add_argument("--copy-dtseries", action="store_true", help="Copy instead of symlinking the dtseries.")
    parser.add_argument("--force", action="store_true", help="Overwrite generated scene/movie and dtseries link.")
    parser.add_argument("--force-dconn", action="store_true", help="Recompute dconn even if it exists.")
    parser.add_argument(
        "--skip-movie",
        action="store_true",
        help="Prepare/validate the dconn and scene without rendering; use --keep-dconn to retain scratch outputs.",
    )
    parser.add_argument("--keep-dconn", action="store_true", help="Keep the intermediate dense correlation CIFTI.")
    args = parser.parse_args(argv)
    if args.reverse and args.closed:
        raise SystemExit("--reverse and --closed are mutually exclusive")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    dtseries = args.dtseries.resolve()
    scene_template = args.scene_template.resolve()
    vertices_src = args.vertices.resolve()
    surface_resource_dir = args.surface_resource_dir.resolve() if args.surface_resource_dir is not None else None
    flat_surface_resource_dir = args.flat_surface_resource_dir.resolve() if args.flat_surface_resource_dir is not None else None
    out_dir = args.out_dir.resolve()
    subject_dir = out_dir / args.subject
    movie_dir = out_dir
    subject_dtseries = subject_dir / f"{args.subject}.dtseries.nii"
    dconn = subject_dir / f"{args.subject}.dconn.nii"
    dconn_manifest_path = subject_dir / ".dconn_manifest.json"
    render_manifest_path = movie_dir / f".{args.subject}.render_manifest.json"
    scene_manifest_path = movie_dir / f".{args.subject}.scene_manifest.json"
    scene_out = movie_dir / f"FlatMaps+Inflated_{args.subject}.scene"
    vertices_out = movie_dir / "VerticesToSample.txt"
    movie_out = movie_dir / f"{args.subject}.mp4"
    source_movie_out = movie_dir / f"{args.subject}.source.mp4"
    render_movie_out = source_movie_out if args.target_size_mb is not None else movie_out

    require_file(dtseries, "dtseries")
    require_file(scene_template, "scene template")
    require_file(vertices_src, "vertex list")
    scene_surface_paths: list[Path] = []
    if surface_resource_dir is not None:
        if not surface_resource_dir.is_dir():
            raise SystemExit(f"Missing surface resource directory: {surface_resource_dir}")
        surface_prefix = args.surface_subject_prefix or infer_surface_subject_prefix(surface_resource_dir)
        flat_surface_prefix = args.flat_surface_subject_prefix or surface_prefix
        if flat_surface_resource_dir is not None and not flat_surface_resource_dir.is_dir():
            raise SystemExit(f"Missing flat surface resource directory: {flat_surface_resource_dir}")
        scene_surface_paths = require_scene_surfaces(
            surface_resource_dir,
            surface_prefix,
            flat_surface_resource_dir,
            flat_surface_prefix,
        )
    if args.weights is not None:
        require_file(args.weights, "weights file")

    subject_dir.mkdir(parents=True, exist_ok=True)
    movie_dir.mkdir(parents=True, exist_ok=True)

    expected_scene_resources: set[str] | None = None
    if surface_resource_dir is not None:
        expected_scene_resources = {
            dconn.resolve().as_posix(),
            scene_out.resolve().as_posix(),
            *(path.resolve().as_posix() for path in scene_surface_paths),
        }

    expected_dconn_request = build_dconn_request(dtseries, args.weights)
    dconn_cache_valid = artifact_manifest_matches(
        dconn_manifest_path,
        expected_dconn_request,
        dconn,
    )
    dconn_cache_invalidated = args.force_dconn or (
        dconn.exists() and not dconn_cache_valid
    )
    dconn_needs_build = args.force_dconn or not dconn_cache_valid
    ensure_dtseries_link(
        dtseries,
        subject_dtseries,
        copy_dtseries=args.copy_dtseries,
        force=args.force or dconn_needs_build,
    )
    shutil.copy2(vertices_src, vertices_out)

    expected_scene_request: dict[str, object] = {
        "recipe_version": RENDER_RECIPE_VERSION,
        "subject": args.subject,
        "scene_template": file_identity(scene_template),
        "template_subject": args.template_subject,
        "surface_resources": [file_identity(path) for path in scene_surface_paths],
        "scene_resources": sorted(expected_scene_resources or []),
    }
    expected_render_request: dict[str, object] = {
        "recipe_version": RENDER_RECIPE_VERSION,
        "subject": args.subject,
        "dconn": expected_dconn_request,
        "scene": expected_scene_request,
        "vertices": file_identity(vertices_src),
        "render": {
            "vertex_mode": args.vertex_mode,
            "width": args.width,
            "height": args.height,
            "framerate": args.framerate,
            "reverse": args.reverse,
            "closed": args.closed,
            "num_cpus": args.num_cpus,
            "target_size_mb": args.target_size_mb,
            "keep_source_movie": args.keep_source_movie,
            "wb_command": args.wb_command,
            "wbsurfer_command": wb_surfer_command(args),
            "ffmpeg_bin": args.ffmpeg_bin,
            "ffprobe_bin": args.ffprobe_bin,
        },
    }

    scene_cache_valid = artifact_manifest_matches(
        scene_manifest_path,
        expected_scene_request,
        scene_out,
    ) and not scene_has_stale_generated_paths(
        scene_out,
        args.subject,
        expected_resources=expected_scene_resources,
    )
    scene_refreshed = args.force or not scene_cache_valid
    if scene_refreshed:
        if scene_out.exists():
            print(f"[REBUILD] Existing scene lacks a matching request/artifact manifest: {scene_out}")
        clone_scene(
            scene_template,
            scene_out,
            args.template_subject,
            args.subject,
            surface_resource_dir,
            args.surface_subject_prefix,
            flat_surface_resource_dir,
            args.flat_surface_subject_prefix,
            dconn,
        )
        write_json_manifest(
            scene_manifest_path,
            build_artifact_manifest(expected_scene_request, scene_out),
        )

    render_cache_valid = False
    render_manifest_stale = False
    if not args.skip_movie:
        render_cache_valid = artifact_manifest_matches(
            render_manifest_path,
            expected_render_request,
            movie_out,
        ) and existing_movie_is_valid(movie_out, args.ffprobe_bin)
        render_artifacts_exist = (
            movie_out.exists()
            or source_movie_out.exists()
            or render_manifest_path.exists()
        )
        render_manifest_stale = render_artifacts_exist and not render_cache_valid
        if render_manifest_stale:
            print("[REBUILD] Existing movie lacks a matching request/artifact manifest")

    completed = False
    dconn_ready = False
    previous_dconn_available = dconn.is_file()
    runtime_capture_command: Path | None = None
    try:
        if dconn_needs_build:
            if dconn.exists():
                reason = "--force-dconn" if args.force_dconn else "input manifest changed"
                print(f"[REBUILD] Existing dconn invalidated ({reason}): {dconn}")
            partial_dconn = dconn.with_name(
                f".{args.subject}.partial.dconn.nii"
            )
            partial_dconn.unlink(missing_ok=True)
            cmd = [
                args.wb_command,
                "-cifti-correlation",
                str(subject_dtseries),
                str(partial_dconn),
            ]
            if args.weights is not None:
                cmd.extend(["-weights", str(args.weights.resolve())])
            run(cmd, cwd=subject_dir)
            require_file(partial_dconn, "new dconn")
            partial_dconn.replace(dconn)
            print(f"[DCONN] Completed correlation: {dconn}")
        else:
            print(f"[SKIP] Existing dconn: {dconn}")
        require_file(dconn, "dconn")
        dconn_ready = True
        write_json_manifest(
            dconn_manifest_path,
            build_artifact_manifest(expected_dconn_request, dconn),
        )
        require_scene_render_resources(
            scene_out,
            args.subject,
            expected_scene_resources,
        )

        if not args.skip_movie:
            refresh_movie = (
                args.force
                or args.force_dconn
                or dconn_cache_invalidated
                or scene_refreshed
                or render_manifest_stale
            )
            final_movie_cached = not refresh_movie and render_cache_valid
            if final_movie_cached:
                print(f"[SKIP] Existing movie: {movie_out}")
                print("[INFO] Use --force to regenerate it.")
            else:
                partial_movie = render_movie_out.with_name(
                    f".{render_movie_out.stem}.partial{render_movie_out.suffix}"
                )
                partial_movie.unlink(missing_ok=True)
                render_env, capture_command = prepare_wbsurfer_environment(
                    wb_command=args.wb_command,
                    scratch_dir=subject_dir,
                )
                runtime_capture_command = Path(capture_command)
                preflight_scene_render(
                    capture_command=capture_command,
                    scene_path=scene_out,
                    scene_name=args.subject,
                    scratch_dir=subject_dir,
                    width=args.width,
                    height=args.height,
                    env=render_env,
                )
                vertices = read_vertices(vertices_out)
                cmd = [
                    *wb_surfer_command(args),
                    "-s",
                    str(scene_out),
                    "-n",
                    args.subject,
                    "-o",
                    str(partial_movie),
                    "--width",
                    str(args.width),
                    "--height",
                    str(args.height),
                    "-r",
                    str(args.framerate),
                ]
                if args.num_cpus is not None:
                    cmd.extend(["--num-cpus", str(args.num_cpus)])
                if args.reverse:
                    cmd.append("--reverse")
                if args.closed:
                    cmd.append("--closed")
                cmd.extend(["--vertex-mode", args.vertex_mode])
                cmd.extend(vertices)
                run(cmd, cwd=movie_dir, env=render_env)
                require_file(partial_movie, "wb_surfer2 output movie")
                movie_duration_seconds(partial_movie, args.ffprobe_bin)
                partial_movie.replace(render_movie_out)
                print(f"[RENDER] Completed movie: {render_movie_out}")

                if args.target_size_mb is not None:
                    compress_movie_to_target_size(
                        source_movie=render_movie_out,
                        output_movie=movie_out,
                        target_size_mb=args.target_size_mb,
                        ffmpeg_bin=args.ffmpeg_bin,
                        ffprobe_bin=args.ffprobe_bin,
                        overwrite=True,
                    )
                    if (
                        not args.keep_source_movie
                        and render_movie_out != movie_out
                        and render_movie_out.exists()
                    ):
                        render_movie_out.unlink()
            require_file(movie_out, "final movie")
            write_json_manifest(
                render_manifest_path,
                build_artifact_manifest(expected_render_request, movie_out),
            )
        completed = True
    finally:
        if runtime_capture_command is not None:
            runtime_capture_command.unlink(missing_ok=True)
        if not completed:
            if dconn.exists() and not dconn_ready:
                if previous_dconn_available:
                    print(f"[PRESERVE] previous dconn after failed refresh: {dconn}")
                else:
                    dconn.unlink()
                    print(f"[CLEANUP] removed incomplete dconn: {dconn}")
            elif dconn.exists():
                print(f"[PRESERVE] completed dconn after failure: {dconn}")
            if subject_dir.exists():
                print(
                    f"ERROR: [fc_movie] failed; preserved diagnostics: {subject_dir}",
                    file=sys.stderr,
                    flush=True,
                )
        elif args.keep_dconn and dconn.exists():
            print(f"[DONE] dconn: {dconn}")
        elif dconn.exists():
            dconn.unlink()
            print(f"[CLEANUP] removed intermediate dconn: {dconn}")
        if completed and not args.keep_dconn and subject_dir.exists():
            shutil.rmtree(subject_dir)
            print(f"[CLEANUP] removed scratch dir: {subject_dir}")

    print(f"[DONE] scene: {scene_out}")
    if not args.skip_movie:
        print(f"[DONE] movie: {movie_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
