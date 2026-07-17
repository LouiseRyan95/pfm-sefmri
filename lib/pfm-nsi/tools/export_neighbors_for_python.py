#!/usr/bin/env python3
import argparse
from pathlib import Path

import numpy as np
import scipy.io as sio


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export MATLAB cifti_surf_neighbors_lr_normalwall.mat to packaged Python .npz"
    )
    parser.add_argument("src", help="Source MATLAB neighbor .mat path")
    parser.add_argument("dst", help="Destination .npz path")
    args = parser.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)

    mat = sio.loadmat(src)
    if "neighbors" not in mat:
        raise ValueError("Expected variable 'neighbors' in MATLAB file.")

    neighbors = np.asarray(mat["neighbors"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dst, neighbors=neighbors)

    print(f"Exported {dst}")
    print("Shape:", neighbors.shape)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
