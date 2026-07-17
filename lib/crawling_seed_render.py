#!/usr/bin/env python3
"""Workbench scene-render compatibility helpers for crawling-seed movies."""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


_ENVIRONMENT_KEYS = (
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "PATH",
    "LD_LIBRARY_PATH",
    "LIBRARY_PATH",
    "LIBGL_DRIVERS_PATH",
    "OSMESA_LIBRARY",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_DATA_DIRS",
    "QT_QPA_PLATFORM",
    "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QT_XCB_GL_INTEGRATION",
    "MESA_LOADER_DRIVER_OVERRIDE",
    "GALLIUM_DRIVER",
    "LIBGL_ALWAYS_SOFTWARE",
    "MESA_GL_VERSION_OVERRIDE",
    "MESA_GLSL_VERSION_OVERRIDE",
    "FSLDIR",
    "FREESURFER_HOME",
    "FS_LICENSE",
    "SUBJECTS_DIR",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
)

_ENVIRONMENT_PREFIXES = (
    "QT_",
    "MESA_",
    "LIBGL_",
    "EGL_",
    "FONTCONFIG_",
    "XDG_",
)


def resolve_executable(command: str) -> Path:
    """Resolve an executable name or path and fail before an expensive render."""
    resolved = shutil.which(command)
    if resolved is None:
        raise SystemExit(f"Executable not found or not executable: {command}")
    return Path(resolved).resolve()


def workbench_scene_capture_mode(wb_command: Path) -> str:
    """Return ``modern`` or ``legacy`` from Workbench's advertised commands."""
    result = subprocess.run(
        [str(wb_command), "-list-commands"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = result.stdout or ""
    if result.returncode != 0:
        raise SystemExit(
            f"Failed to query Workbench commands from {wb_command} "
            f"(exit {result.returncode}):\n{output.strip()}"
        )
    commands = {
        line.split(maxsplit=1)[0]
        for line in output.splitlines()
        if line.strip().startswith("-")
    }
    if "-scene-capture-image" in commands:
        return "modern"
    if "-show-scene" in commands:
        return "legacy"
    raise SystemExit(
        f"Workbench {wb_command} supports neither -scene-capture-image nor -show-scene"
    )


def _write_wb_command_shim(
    *, scratch_dir: Path, wb_command: Path, capture_mode: str
) -> Path:
    """Create an executable shim that restores env stripped by wb_surfer2 workers."""
    diagnostic_shim = scratch_dir / ".wb_command_scene_compat.sh"
    lines = [
        "#!/bin/sh",
        "set -eu",
        f"REAL_WB={shlex.quote(str(wb_command))}",
    ]
    environment_keys = sorted(
        set(_ENVIRONMENT_KEYS)
        | {key for key in os.environ if key.startswith(_ENVIRONMENT_PREFIXES)}
    )
    for key in environment_keys:
        value = os.environ.get(key)
        if value is not None:
            lines.append(f"export {key}={shlex.quote(value)}")
    if capture_mode == "legacy":
        lines.extend(
            [
                'if [ "${1:-}" = "-scene-capture-image" ]; then',
                '  if [ "$#" -ne 7 ] || [ "${5:-}" != "-size-width-height" ]; then',
                '    echo "Unsupported -scene-capture-image arguments: $*" >&2',
                "    exit 64",
                "  fi",
                '  exec "$REAL_WB" -show-scene "$2" "$3" "$4" "$6" "$7"',
                "fi",
            ]
        )
    lines.append('exec "$REAL_WB" "$@"')
    script_text = "\n".join(lines) + "\n"
    diagnostic_shim.write_text(script_text, encoding="utf-8")

    runtime_dir = Path(
        os.environ.get("CRAWLING_SEED_FC_SHIM_DIR")
        or (Path.home() / ".cache" / "pfm-mefmri")
    )
    runtime_dir.mkdir(parents=True, exist_ok=True)
    fd, runtime_name = tempfile.mkstemp(
        prefix="crawling_seed_fc_wb_",
        suffix=".sh",
        dir=runtime_dir,
    )
    os.close(fd)
    runtime_shim = Path(runtime_name)
    runtime_shim.write_text(script_text, encoding="utf-8")
    runtime_shim.chmod(
        runtime_shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )
    return runtime_shim.resolve()


def prepare_wbsurfer_environment(
    *, wb_command: str, scratch_dir: Path
) -> tuple[dict[str, str], str]:
    """Build a verbose, version-compatible environment for wb_surfer2."""
    real_wb_command = resolve_executable(wb_command)
    capture_mode = workbench_scene_capture_mode(real_wb_command)
    shim = _write_wb_command_shim(
        scratch_dir=scratch_dir,
        wb_command=real_wb_command,
        capture_mode=capture_mode,
    )
    env = os.environ.copy()
    env["EXTERNAL_COMMAND_LOG"] = "1"
    env["WBCOMMAND_BINARY_PATH"] = str(shim)
    env["OMP_NUM_THREADS"] = "1"
    if capture_mode == "legacy":
        description = "legacy -show-scene compatibility"
    else:
        description = "native -scene-capture-image"
    print(f"[RENDER] Workbench command: {real_wb_command}")
    print(f"[RENDER] Workbench scene backend: {description}")
    print("[RENDER] wb_surfer2 external command logging: enabled")
    return env, str(shim)


def preflight_scene_render(
    *,
    capture_command: str,
    scene_path: Path,
    scene_name: str,
    scratch_dir: Path,
    width: int,
    height: int,
    env: dict[str, str],
) -> None:
    """Render one image before wb_surfer2 starts its multiprocessing pool."""
    output = scratch_dir / ".render_preflight.png"
    for old_output in [output, *scratch_dir.glob(".render_preflight_*.png")]:
        old_output.unlink(missing_ok=True)
    cmd = [
        capture_command,
        "-scene-capture-image",
        str(scene_path),
        scene_name,
        str(output),
        "-size-width-height",
        str(width),
        str(height),
    ]
    print("[PREFLIGHT] Rendering one Workbench scene image", flush=True)
    worker_env = {"OMP_NUM_THREADS": env.get("OMP_NUM_THREADS", "1")}
    print("[PREFLIGHT] Mirroring wb_surfer2's stripped worker environment", flush=True)
    try:
        subprocess.run(
            cmd,
            cwd=str(scene_path.parent),
            env=worker_env,
            check=True,
        )
    except OSError as exc:
        raise SystemExit(
            f"Could not execute Workbench worker shim {capture_command}: {exc}. "
            "Set CRAWLING_SEED_FC_SHIM_DIR to a directory on an executable filesystem."
        ) from exc
    generated = [
        path
        for path in [output, *scratch_dir.glob(".render_preflight_*.png")]
        if path.is_file()
    ]
    if not generated:
        raise SystemExit(
            "Workbench render preflight returned success but produced no PNG"
        )
    invalid: list[Path] = []
    for path in generated:
        with path.open("rb") as stream:
            signature = stream.read(8)
        if path.stat().st_size == 0 or signature != b"\x89PNG\r\n\x1a\n":
            invalid.append(path)
    if invalid:
        raise SystemExit(
            "Workbench render preflight produced invalid PNG output: "
            + ", ".join(str(path) for path in invalid)
        )
    generated_paths = ", ".join(str(path) for path in generated)
    print(
        f"[PREFLIGHT] Workbench scene rendering succeeded: {generated_paths}",
        flush=True,
    )
