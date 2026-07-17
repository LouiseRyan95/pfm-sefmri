#!/usr/bin/env python3
import argparse
from pathlib import Path

import numpy as np
import scipy.io as sio


def _unwrap_scalar(value):
    while isinstance(value, np.ndarray) and value.size == 1:
        value = value.reshape(-1)[0]
    return value


def _normalize_labels(labels_obj):
    arr = np.asarray(labels_obj, dtype=object).ravel()
    labels = []
    for item in arr:
        item = _unwrap_scalar(item)
        if isinstance(item, np.ndarray):
            item = np.asarray(item).squeeze()
        labels.append(str(item))
    return np.asarray(labels, dtype=object)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export MATLAB priors.mat to packaged Python priors.npz")
    parser.add_argument("src", help="Source priors.mat path")
    parser.add_argument("dst", help="Destination priors.npz path")
    args = parser.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)

    mat = sio.loadmat(src, squeeze_me=True, struct_as_record=False)
    if "Priors" not in mat:
        raise ValueError("Expected variable 'Priors' in MATLAB file.")
    pri = mat["Priors"]

    payload = {
        "FC": np.asarray(pri.FC),
    }
    if hasattr(pri, "Alt") and hasattr(pri.Alt, "FC"):
        payload["Alt_FC"] = np.asarray(pri.Alt.FC)
    if hasattr(pri, "NetworkLabels"):
        payload["NetworkLabels"] = _normalize_labels(pri.NetworkLabels)
    if hasattr(pri, "NetworkColors"):
        payload["NetworkColors"] = np.asarray(pri.NetworkColors, dtype=float)

    dst.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dst, **payload)

    print(f"Exported {dst}")
    print("Keys:", sorted(payload.keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
