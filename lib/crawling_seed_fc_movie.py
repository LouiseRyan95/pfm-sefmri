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
import re
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_SCENE = Path(__file__).resolve().parents[1] / "res0urces" / "CrawlingSeedFC" / "FlatMaps+Inflated.scene"
DEFAULT_VERTICES = Path(__file__).resolve().parents[1] / "res0urces" / "CrawlingSeedFC" / "VerticesToSample.txt"


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("[RUN] " + " ".join(str(x) for x in cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def check_output(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"Missing {label}: {path}")


def ensure_dtseries_link(src: Path, dst: Path, *, copy_dtseries: bool, force: bool) -> None:
    if dst.exists() or dst.is_symlink():
        if force:
            dst.unlink()
        else:
            return

    if copy_dtseries:
        shutil.copy2(src, dst)
    else:
        dst.symlink_to(src.resolve())


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
    text = template_scene.read_text(encoding="utf-8", errors="surrogateescape")
    if template_subject not in text:
        raise SystemExit(f"Template subject {template_subject!r} was not found in {template_scene}")
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
    dconn_name = f"{subject}.dconn.nii"
    dconn_abs = str(dconn_path.resolve())
    text = re.sub(
        r"\.\./\.\./\.\./BlindedRatings/sub-[^/<]+/sub-[^/<]+\.dconn\.nii",
        dconn_abs,
        text,
    )
    text = re.sub(r"sub-[A-Za-z0-9]+\.dconn\.nii", dconn_name, text)
    text = re.sub(
        r"\.\./\.\./\.\./BlindedRatings/Movies/FlatMaps\+Inflated\.scene",
        str(scene_out.resolve()),
        text,
    )
    scene_out.write_text(text, encoding="utf-8", errors="surrogateescape")


def infer_surface_subject_prefix(surface_dir: Path) -> str:
    matches = sorted(surface_dir.glob("*.L.midthickness.32k_fs_LR.surf.gii"))
    if not matches:
        raise SystemExit(f"Could not infer subject surface prefix from {surface_dir}")
    suffix = ".L.midthickness.32k_fs_LR.surf.gii"
    return matches[0].name[: -len(suffix)]


def require_scene_surfaces(surface_dir: Path, surface_prefix: str, flat_surface_dir: Path | None = None, flat_surface_prefix: str | None = None) -> None:
    missing: list[Path] = []
    for hemi in ("L", "R"):
        for surf in ("inflated", "midthickness", "pial", "very_inflated", "white"):
            path = surface_dir / f"{surface_prefix}.{hemi}.{surf}.32k_fs_LR.surf.gii"
            if not path.is_file():
                missing.append(path)
        for surf in ("flat", "sphere"):
            path = (flat_surface_dir or surface_dir) / f"{flat_surface_prefix or surface_prefix}.{hemi}.{surf}.32k_fs_LR.surf.gii"
            if not path.is_file():
                missing.append(path)
    if missing:
        preview = "\n".join(f"  {path}" for path in missing[:8])
        extra = "" if len(missing) <= 8 else f"\n  ... and {len(missing) - 8} more"
        raise SystemExit(f"Missing scene surface files:\n{preview}{extra}")


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
    if output_movie.exists():
        if overwrite:
            output_movie.unlink()
        else:
            print(f"[SKIP] Existing compressed movie: {output_movie}")
            return

    duration = movie_duration_seconds(source_movie, ffprobe_bin)
    target_bits = target_size_mb * 1024 * 1024 * 8
    video_kbps = max(50, int((target_bits / duration) * 0.97 / 1000))
    passlog = output_movie.with_suffix(".ffmpeg2pass")

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
        str(output_movie),
    ]
    run(first_pass)
    run(second_pass)

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
    parser.add_argument("--subject", required=True, help="Scene/movie subject name, usually sub-*.")
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
    parser.add_argument("--skip-movie", action="store_true", help="Only prepare dtseries/dconn/scene.")
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
    scene_out = movie_dir / f"FlatMaps+Inflated_{args.subject}.scene"
    vertices_out = movie_dir / "VerticesToSample.txt"
    movie_out = movie_dir / f"{args.subject}.mp4"
    source_movie_out = movie_dir / f"{args.subject}.source.mp4"
    render_movie_out = source_movie_out if args.target_size_mb is not None else movie_out

    require_file(dtseries, "dtseries")
    require_file(scene_template, "scene template")
    require_file(vertices_src, "vertex list")
    if surface_resource_dir is not None:
        if not surface_resource_dir.is_dir():
            raise SystemExit(f"Missing surface resource directory: {surface_resource_dir}")
        surface_prefix = args.surface_subject_prefix or infer_surface_subject_prefix(surface_resource_dir)
        flat_surface_prefix = args.flat_surface_subject_prefix or surface_prefix
        if flat_surface_resource_dir is not None and not flat_surface_resource_dir.is_dir():
            raise SystemExit(f"Missing flat surface resource directory: {flat_surface_resource_dir}")
        require_scene_surfaces(surface_resource_dir, surface_prefix, flat_surface_resource_dir, flat_surface_prefix)
    if args.weights is not None:
        require_file(args.weights, "weights file")

    subject_dir.mkdir(parents=True, exist_ok=True)
    movie_dir.mkdir(parents=True, exist_ok=True)

    ensure_dtseries_link(dtseries, subject_dtseries, copy_dtseries=args.copy_dtseries, force=args.force)
    shutil.copy2(vertices_src, vertices_out)

    if args.force or not scene_out.exists():
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

    try:
        if args.force_dconn and dconn.exists():
            dconn.unlink()
        if not dconn.exists():
            cmd = [args.wb_command, "-cifti-correlation", str(subject_dtseries), str(dconn)]
            if args.weights is not None:
                cmd.extend(["-weights", str(args.weights.resolve())])
            run(cmd, cwd=subject_dir)
        else:
            print(f"[SKIP] Existing dconn: {dconn}")

        if not args.skip_movie:
            if args.target_size_mb is not None and movie_out.exists() and not args.force:
                print(f"[SKIP] Existing movie: {movie_out}")
                print("[INFO] Use --force to regenerate and compress it to --target-size-mb.")
            else:
                if args.force and source_movie_out.exists():
                    source_movie_out.unlink()
                if args.force and movie_out.exists():
                    movie_out.unlink()
                if not render_movie_out.exists():
                    vertices = read_vertices(vertices_out)
                    cmd = [
                        *wb_surfer_command(args),
                        "-s",
                        str(scene_out),
                        "-n",
                        args.subject,
                        "-o",
                        str(render_movie_out),
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
                    run(cmd, cwd=movie_dir)
                else:
                    print(f"[SKIP] Existing source movie: {render_movie_out}")

                if args.target_size_mb is not None:
                    compress_movie_to_target_size(
                        source_movie=render_movie_out,
                        output_movie=movie_out,
                        target_size_mb=args.target_size_mb,
                        ffmpeg_bin=args.ffmpeg_bin,
                        ffprobe_bin=args.ffprobe_bin,
                        overwrite=args.force,
                    )
                    if not args.keep_source_movie and render_movie_out != movie_out and render_movie_out.exists():
                        render_movie_out.unlink()
    finally:
        if args.keep_dconn and dconn.exists():
            print(f"[DONE] dconn: {dconn}")
        elif dconn.exists():
            dconn.unlink()
            print(f"[CLEANUP] removed intermediate dconn: {dconn}")
        if not args.keep_dconn and subject_dir.exists():
            shutil.rmtree(subject_dir)
            print(f"[CLEANUP] removed scratch dir: {subject_dir}")

    print(f"[DONE] scene: {scene_out}")
    if not args.skip_movie:
        print(f"[DONE] movie: {movie_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
