import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Union

import nibabel as nib
import numpy as np

from .core import read_cifti


def _mesh_asset_path(filename: str) -> str:
    return os.path.join(os.path.dirname(__file__), "models", "mesh", filename)


def _load_metric_gifti(path: Union[str, os.PathLike]) -> np.ndarray:
    img = nib.load(str(path))
    if not hasattr(img, "darrays") or len(img.darrays) == 0:
        raise ValueError(f"No metric arrays found in GIFTI file: {path}")
    cols = [np.asarray(arr.data) for arr in img.darrays]
    data = np.column_stack(cols)
    if data.ndim == 1:
        data = data[:, None]
    return data


def resolve_wb_command(explicit: Optional[str] = None) -> str:
    candidates = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("WB_COMMAND")
    if env:
        candidates.append(env)
    candidates.append("wb_command")

    for cmd in candidates:
        resolved = shutil.which(cmd) if os.path.basename(cmd) == cmd else cmd
        if not resolved:
            continue
        try:
            proc = subprocess.run(
                [resolved, "-version"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            continue
        if proc.returncode == 0:
            return resolved

    raise RuntimeError(
        "fsaverage6 support requires Connectome Workbench (`wb_command`), but it was not found.\n\n"
        "To fix this:\n"
        "1. Install Connectome Workbench: https://www.humanconnectome.org/software/get-connectome-workbench\n"
        "2. Ensure `wb_command` is available on PATH, for example:\n"
        "   export PATH=/path/to/workbench/bin_linux64:$PATH\n"
        "3. Or set an explicit executable path:\n"
        "   export WB_COMMAND=/full/path/to/wb_command\n"
        "4. Verify installation:\n"
        "   wb_command -version\n\n"
        "Then rerun with `--fsaverage6`, or use the default fsLR-32k mode instead."
    )


def _resample_metric(
    wb_command: str,
    src_metric: str,
    src_sphere: str,
    dst_sphere: str,
    src_area: str,
    dst_area: str,
    dst_metric: str,
) -> None:
    proc = subprocess.run(
        [
            wb_command,
            "-metric-resample",
            src_metric,
            src_sphere,
            dst_sphere,
            "ADAP_BARY_AREA",
            dst_metric,
            "-area-metrics",
            src_area,
            dst_area,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(
            "Workbench metric resampling failed while converting fsaverage6 input to fsLR-32k.\n"
            f"Command: {' '.join(proc.args)}\n"
            f"stderr: {stderr or '<empty>'}"
        )


def prepare_cifti_for_mesh(
    cifti_source: Union[str, os.PathLike, Dict[str, Any]],
    mesh: str = "fslr32k",
    dtype: np.dtype = np.float64,
    wb_command: Optional[str] = None,
) -> Dict[str, Any]:
    mesh_key = str(mesh).lower()
    if mesh_key in ("fslr32k", "fslr32k", "fs_lr_32k"):
        if isinstance(cifti_source, (str, os.PathLike)):
            return read_cifti(str(cifti_source), dtype=dtype)
        return cifti_source
    if mesh_key != "fsaverage6":
        raise ValueError(f"Unsupported mesh: {mesh}")
    if not isinstance(cifti_source, (str, os.PathLike)):
        raise TypeError("fsaverage6 conversion currently requires the original input CIFTI path.")
    return _prepare_fsaverage6_cifti(str(cifti_source), dtype=dtype, wb_command=wb_command)


def _prepare_fsaverage6_cifti(
    cifti_path: str,
    dtype: np.dtype = np.float64,
    wb_command: Optional[str] = None,
) -> Dict[str, Any]:
    wb = resolve_wb_command(wb_command)
    C = read_cifti(cifti_path, dtype=dtype)

    label_to_idx = {label: i + 1 for i, label in enumerate(C["brainstructurelabel"])}
    left_id = label_to_idx.get("CORTEX_LEFT")
    right_id = label_to_idx.get("CORTEX_RIGHT")
    if left_id is None or right_id is None:
        raise ValueError("fsaverage6 conversion requires bilateral cortical structures in the input CIFTI.")

    with tempfile.TemporaryDirectory(prefix="pfm_nsi_fsaverage6_") as tmpdir:
        tmp = Path(tmpdir)
        lh_src = tmp / "lh.fsaverage6.func.gii"
        rh_src = tmp / "rh.fsaverage6.func.gii"
        proc = subprocess.run(
            [
                wb,
                "-cifti-separate",
                cifti_path,
                "COLUMN",
                "-metric",
                "CORTEX_LEFT",
                str(lh_src),
                "-metric",
                "CORTEX_RIGHT",
                str(rh_src),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise RuntimeError(
                "Workbench failed to extract cortical metrics from the fsaverage6 CIFTI input.\n"
                f"Command: {' '.join(proc.args)}\n"
                f"stderr: {stderr or '<empty>'}"
            )

        lh_out = tmp / "lh.fslr32k.func.gii"
        rh_out = tmp / "rh.fslr32k.func.gii"
        _resample_metric(
            wb,
            str(lh_src),
            _mesh_asset_path("fsaverage6_std_sphere.L.41k_fsavg_L.surf.gii"),
            _mesh_asset_path("fs_LR-deformed_to-fsaverage.L.sphere.32k_fs_LR.surf.gii"),
            _mesh_asset_path("fsaverage6.L.midthickness_va_avg.41k_fsavg_L.shape.gii"),
            _mesh_asset_path("fs_LR.L.midthickness_va_avg.32k_fs_LR.shape.gii"),
            str(lh_out),
        )
        _resample_metric(
            wb,
            str(rh_src),
            _mesh_asset_path("fsaverage6_std_sphere.R.41k_fsavg_R.surf.gii"),
            _mesh_asset_path("fs_LR-deformed_to-fsaverage.R.sphere.32k_fs_LR.surf.gii"),
            _mesh_asset_path("fsaverage6.R.midthickness_va_avg.41k_fsavg_R.shape.gii"),
            _mesh_asset_path("fs_LR.R.midthickness_va_avg.32k_fs_LR.shape.gii"),
            str(rh_out),
        )

        lh = _load_metric_gifti(lh_out).astype(dtype, copy=False)
        rh = _load_metric_gifti(rh_out).astype(dtype, copy=False)

    cortex_masks = np.load(_mesh_asset_path("fslr32k_cortex_masks.npz"))
    lh_mask = np.asarray(cortex_masks["lh_mask"], dtype=bool)
    rh_mask = np.asarray(cortex_masks["rh_mask"], dtype=bool)
    lh_cortex = lh[lh_mask, :]
    rh_cortex = rh[rh_mask, :]

    sub_idx = np.where(~np.isin(C["brainstructure"], [left_id, right_id]))[0]
    data = np.vstack([lh_cortex, rh_cortex, C["data"][sub_idx, :]])
    brainstructure = np.concatenate(
        [
            np.full(lh_cortex.shape[0], left_id, dtype=np.int32),
            np.full(rh_cortex.shape[0], right_id, dtype=np.int32),
            C["brainstructure"][sub_idx].astype(np.int32, copy=False),
        ]
    )
    pos = np.vstack(
        [
            np.zeros((lh_cortex.shape[0] + rh_cortex.shape[0], 3), dtype=np.float64),
            C["pos"][sub_idx, :],
        ]
    )

    return {
        "data": data,
        "brainstructure": brainstructure,
        "brainstructurelabel": list(C["brainstructurelabel"]),
        "pos": pos,
    }
