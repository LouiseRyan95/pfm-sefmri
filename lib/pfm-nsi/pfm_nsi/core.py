import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import scipy.io as sio
import scipy.sparse as sp
from scipy.sparse import csgraph
import scipy.sparse.linalg as spla
from scipy.spatial.distance import cdist
import nibabel as nib


def _load_binary_roi_as_sparse_idx(
    C: Dict[str, Any],
    roi_source: Union[str, os.PathLike, np.ndarray, Sequence[int], Sequence[float]],
    threshold: float = 0.5,
) -> np.ndarray:
    """Resolve a binary ROI source to 1-based sparse target indices.

    Accepted inputs:
      - 1D binary mask aligned to CIFTI grayordinates.
      - 1D list/array of 1-based indices.
      - Path to .txt/.csv (mask vector or 1-based indices).
      - Path to .npy/.npz/.mat/.nii/.dscalar.nii/.dtseries.nii containing mask values.
    """
    n_gray = int(C["data"].shape[0])

    def _from_array(arr: np.ndarray) -> np.ndarray:
        v = np.asarray(arr).squeeze()
        if v.ndim != 1:
            v = v.reshape(-1)
        if v.size == n_gray:
            return (np.where(v > threshold)[0] + 1).astype(np.int64)
        # Otherwise interpret as explicit indices.
        idx = np.asarray(v, dtype=np.int64).ravel()
        return idx

    if isinstance(roi_source, (str, os.PathLike)):
        p = str(roi_source)
        src = Path(p)
        if not src.exists():
            raise FileNotFoundError(f"Binary ROI file not found: {p}")
        lower = src.name.lower()
        if lower.endswith((".txt", ".csv")):
            txt = src.read_text(encoding="utf-8")
            toks: List[str] = []
            for ln in txt.splitlines():
                line = ln.strip()
                if not line or line.startswith("#"):
                    continue
                toks.extend([t.strip() for t in line.split(",") if t.strip()])
            vals = np.asarray([float(t) for t in toks], dtype=float)
            idx = _from_array(vals)
        elif lower.endswith(".npy"):
            idx = _from_array(np.load(p, allow_pickle=False))
        elif lower.endswith(".npz"):
            z = np.load(p, allow_pickle=False)
            if not z.files:
                raise ValueError(f"No arrays found in ROI .npz: {p}")
            idx = _from_array(np.asarray(z[z.files[0]]))
        elif lower.endswith(".mat"):
            idx = _from_array(_smartload_array(p))
        else:
            # NIfTI/CIFTI route.
            img = nib.load(p)
            data = np.asarray(img.dataobj)
            idx = _from_array(data)
    else:
        idx = _from_array(np.asarray(roi_source))

    idx = np.asarray(idx, dtype=np.int64).ravel()
    idx = idx[np.isfinite(idx)]
    idx = idx[(idx >= 1) & (idx <= n_gray)]
    idx = np.unique(idx)
    if idx.size == 0:
        raise ValueError("Binary ROI did not contain any valid target indices.")
    return idx


def _collapse_lr_structure_label(label: str) -> str:
    s = str(label)
    for suffix in ("_LEFT", "_RIGHT"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def _label_to_str(x: Any) -> str:
    v = x
    if isinstance(v, np.ndarray):
        flat = v.ravel()
        if flat.size == 0:
            return ""
        v = flat[0]
    if isinstance(v, bytes):
        return v.decode("utf-8")
    return str(v)


def _smartload_array(path: str, key: Optional[str] = None) -> np.ndarray:
    """Load an array from .npz or .mat."""
    if path.endswith(".npz"):
        z = np.load(path, allow_pickle=True)
        if key is not None and key in z:
            return z[key]
        if len(z.files) == 1:
            return z[z.files[0]]
        raise ValueError(f"Multiple arrays in {path}; pass a key.")
    m = sio.loadmat(path)
    if key is not None and key in m:
        return m[key]
    for k, v in m.items():
        if not k.startswith("__"):
            return v
    raise ValueError(f"No variables found in {path}")


def _default_asset_path(filename: str) -> str:
    return os.path.join(os.path.dirname(__file__), "models", filename)


def _mat_struct_get(mat_struct: Any, field: str) -> Any:
    """Get a field from a MATLAB struct loaded via scipy.io.loadmat."""
    if isinstance(mat_struct, dict):
        return mat_struct[field]
    if isinstance(mat_struct, np.ndarray) and mat_struct.dtype.names:
        return mat_struct[field][0, 0]
    raise TypeError("Unsupported MATLAB struct type")


def _mat_struct_get_opt(mat_struct: Any, field: str) -> Any:
    try:
        return _mat_struct_get(mat_struct, field)
    except Exception:
        return None


def _normalize_network_labels(labels: Any) -> Optional[List[str]]:
    if labels is None:
        return None
    arr = np.asarray(labels, dtype=object).ravel()
    out: List[str] = []
    for item in arr:
        while isinstance(item, np.ndarray) and item.size == 1:
            item = item.reshape(-1)[0]
        out.append(str(np.asarray(item).squeeze()) if isinstance(item, np.ndarray) else str(item))
    return out


def _load_priors(priors: Union[str, Dict[str, Any], np.ndarray]) -> Dict[str, Any]:
    if isinstance(priors, str):
        if priors.endswith(".npz"):
            z = np.load(priors, allow_pickle=True)
            return {
                "FC": np.asarray(z["FC"]),
                "Alt": np.asarray(z["Alt_FC"]) if "Alt_FC" in z else None,
                "NetworkLabels": _normalize_network_labels(z["NetworkLabels"]) if "NetworkLabels" in z else None,
                "NetworkColors": np.asarray(z["NetworkColors"], dtype=float) if "NetworkColors" in z else None,
            }
        pri = sio.loadmat(priors)
        if "Priors" not in pri:
            raise ValueError("Priors file must contain variable 'Priors'.")
        pri = pri["Priors"]
    else:
        pri = priors
    return {
        "FC": _mat_struct_get(pri, "FC"),
        "Alt": _mat_struct_get(pri, "Alt") if hasattr(pri, "dtype") and pri.dtype.names and "Alt" in pri.dtype.names else None,
        "NetworkLabels": _normalize_network_labels(_mat_struct_get_opt(pri, "NetworkLabels")),
        "NetworkColors": _mat_struct_get_opt(pri, "NetworkColors"),
    }


def _structure_name(cifti_name: str) -> str:
    if cifti_name.startswith("CIFTI_STRUCTURE_"):
        return cifti_name[len("CIFTI_STRUCTURE_") :]
    return cifti_name


def read_cifti(path: str, dtype: np.dtype = np.float64) -> Dict[str, Any]:
    img = nib.load(path)
    data = np.asarray(img.dataobj, dtype=dtype)  # time x brain
    if data.ndim != 2:
        raise ValueError("Expected 2D CIFTI dtseries data")
    data = data.T  # brain x time

    axis = img.header.get_axis(1)  # BrainModelAxis
    n = len(axis)

    brainstructurelabel: List[str] = []
    label_to_idx: Dict[str, int] = {}
    brainstructure = np.zeros(n, dtype=np.int32)

    pos = np.zeros((n, 3), dtype=np.float64)
    affine = axis.affine

    for i in range(n):
        el = axis.get_element(i)
        # el: (model_type, vertex_or_ijk, brain_structure_name)
        structure = _structure_name(el[2])
        if structure not in label_to_idx:
            label_to_idx[structure] = len(brainstructurelabel) + 1  # 1-based
            brainstructurelabel.append(structure)
        brainstructure[i] = label_to_idx[structure]

        if el[0] == "CIFTI_MODEL_TYPE_VOXELS":
            ijk = np.array(el[1], dtype=np.float64)
            xyz = affine @ np.array([ijk[0], ijk[1], ijk[2], 1.0])
            pos[i, :] = xyz[:3]
        else:
            # Surface vertices are not required for current QC computations.
            pos[i, :] = 0.0

    return {
        "data": data,
        "brainstructure": brainstructure,
        "brainstructurelabel": brainstructurelabel,
        "pos": pos,
    }


def sparse_parcellation(C: Dict[str, Any], neighbor_mat_path: str) -> np.ndarray:
    Nbr = _smartload_array(neighbor_mat_path, key="neighbors")
    if Nbr.shape[1] < 2:
        raise ValueError("Neighbor table must have at least two columns")

    n_cortex = Nbr.shape[0]
    visited = np.zeros(n_cortex + 1, dtype=bool)  # 1-based
    sub_sample: List[int] = []

    for i in range(1, n_cortex + 1):
        if not visited[i]:
            sub_sample.append(i)
            nbrs = Nbr[i - 1, 1:]
            for nbr in nbrs:
                if np.isnan(nbr):
                    continue
                nbr = int(nbr)
                if nbr >= 1 and nbr <= n_cortex:
                    visited[nbr] = True

    ncortverts = int(np.sum(C["brainstructure"] == 1) + np.sum(C["brainstructure"] == 2))
    brain_structure = C["brainstructure"]
    pos = C["pos"].copy()
    pos = pos[brain_structure != -1]
    subcortical_coords = pos[ncortverts:]

    if subcortical_coords.size == 0:
        return np.asarray(sub_sample, dtype=np.int64)

    D = cdist(subcortical_coords, subcortical_coords)
    subcort_neighbors: List[np.ndarray] = []
    for i in range(D.shape[0]):
        subcort_neighbors.append(np.where(D[i, :] <= 2.0)[0] + 1)  # 1-based

    edge_voxels = np.zeros(D.shape[0] + 1, dtype=bool)
    for i in range(1, D.shape[0] + 1):
        if not edge_voxels[i]:
            sub_sample.append(i + ncortverts)
            for nbr in subcort_neighbors[i - 1]:
                edge_voxels[int(nbr)] = True

    return np.asarray(sub_sample, dtype=np.int64)


def build_cortex_adjacency(CorticalIdx: np.ndarray, neighbor_mat_path: str) -> sp.csr_matrix:
    CorticalIdx = np.asarray(CorticalIdx).astype(bool).ravel()
    Vall = CorticalIdx.size
    Nbr = _smartload_array(neighbor_mat_path, key="neighbors")
    if Nbr.shape[0] != Vall:
        raise ValueError("Neighbor table rows must equal numel(CorticalIdx).")

    rows = []
    cols = []
    for i in range(Vall):
        nbrs = Nbr[i, 1:]
        for nbr in nbrs:
            if np.isnan(nbr):
                continue
            j = int(nbr) - 1
            if j < 0 or j >= Vall:
                continue
            rows.append(i)
            cols.append(j)

    data = np.ones(len(rows), dtype=np.float64)
    Wfull = sp.csr_matrix((data, (rows, cols)), shape=(Vall, Vall))
    Wfull = Wfull.maximum(Wfull.T)
    W = Wfull[CorticalIdx][:, CorticalIdx]
    W = W.maximum(W.T)
    return W


def morans_i_withW(X: np.ndarray, W: sp.csr_matrix) -> np.ndarray:
    V = X.shape[0]
    Xc = X - np.mean(X, axis=0, keepdims=True)
    WX = W.dot(Xc)
    num = np.sum(Xc * WX, axis=0)
    den = np.sum(Xc * Xc, axis=0)
    S0 = float(W.sum())
    eps = np.finfo(np.float64).eps
    mI = (V / S0) * (num / np.maximum(den, eps))
    return mI


def _robustfit_bisquare(x: np.ndarray, y: np.ndarray, max_iter: int = 50, tol: float = 1e-8) -> np.ndarray:
    """Approximate MATLAB robustfit with bisquare weighting.

    Returns coefficients [intercept, slope].
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    X = np.column_stack([np.ones_like(x), x])

    # Initial OLS
    b, *_ = np.linalg.lstsq(X, y, rcond=None)

    c = 4.685
    for _ in range(max_iter):
        r = y - X @ b
        # MAD scale estimate
        mad = np.median(np.abs(r))
        if mad == 0:
            break
        s = mad / 0.6745
        if s <= 0:
            break
        u = r / (c * s)
        w = (1 - u ** 2) ** 2
        w[np.abs(u) >= 1] = 0.0
        W = np.sqrt(w)
        Xw = X * W[:, None]
        yw = y * W
        b_new, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
        if np.linalg.norm(b_new - b) <= tol * np.linalg.norm(b):
            b = b_new
            break
        b = b_new
    return b


def spectral_slope_withW(
    X: np.ndarray,
    W: sp.csr_matrix,
    kmax: int = 400,
    low_skip: int = 5,
    high_frac: float = 0.10,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    V, N = X.shape
    W = W.maximum(W.T)
    d = np.array(W.sum(axis=1)).ravel()
    d[d <= 0] = np.finfo(np.float64).eps
    Dmh = sp.diags(1.0 / np.sqrt(d))
    Lsym = sp.eye(V, format="csr") - Dmh @ W @ Dmh

    # Connected components
    try:
        n_components = csgraph.connected_components(W, directed=False, return_labels=False)
        c = int(n_components)
    except Exception:
        c = max(1, int(np.sum(d == 0)))

    kreq = min(V - 1, kmax + c)

    evals = None
    evecs = None
    sigmas = [1e-6, 1e-5, 1e-4, 1e-3]
    for sigma in sigmas:
        try:
            evals, evecs = spla.eigsh(Lsym, k=kreq, sigma=sigma, which="LM")
            break
        except Exception:
            continue
    if evals is None:
        jitter = 1e-6
        evals, evecs = spla.eigsh(Lsym + jitter * sp.eye(V, format="csr"), k=kreq, which="SA")

    ix = np.argsort(evals)
    evals = evals[ix]
    evecs = evecs[:, ix]

    drop = min(c, len(evals))
    evals = evals[drop:]
    evecs = evecs[:, drop:]

    Xc = X - np.mean(X, axis=0, keepdims=True)
    Xc = Xc / np.maximum(np.std(Xc, axis=0, ddof=1, keepdims=True), np.finfo(np.float64).eps)

    coeff = evecs.T @ Xc
    pw = coeff ** 2

    k = evecs.shape[1]
    hi_drop = max(1, int(math.floor(high_frac * k)))
    start = low_skip
    stop = k - hi_drop
    if stop <= start:
        raise ValueError("Not enough eigenmodes for slope fit; adjust kmax/high_frac/low_skip")
    idx_fit = np.arange(start, stop)

    f = evals[idx_fit]
    logf = np.log(f + 1e-12)

    slope = np.full((N,), np.nan, dtype=np.float64)
    for j in range(N):
        lp = np.log(pw[idx_fit, j] + 1e-12)
        b = _robustfit_bisquare(logf, lp)
        slope[j] = b[1]

    freq = evals
    power = pw
    return slope, freq, power


def pfm_nsi(
    C: Union[str, Dict[str, Any]],
    Structures: Sequence[str],
    Priors: Union[str, Dict[str, Any], np.ndarray],
    opts: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if opts is None:
        opts = {}

    lowmem = bool(opts.get("lowmem", False))
    use_float32 = bool(opts.get("use_float32", lowmem))
    calc_dtype = np.float32 if use_float32 else np.float64
    keep_betas = bool(opts.get("keep_betas", not lowmem))
    keep_fc_map = bool(opts.get("keep_fc_map", not lowmem))
    block_size = int(opts.get("block_size", 512 if lowmem else 0))

    if isinstance(C, (str, os.PathLike)):
        C = read_cifti(str(C), dtype=calc_dtype)

    ridge_lambdas = opts.get("ridge_lambdas", [1, 5, 10, 25, 50])
    if np.isscalar(ridge_lambdas):
        ridge_lambdas = [ridge_lambdas]
    neighbor_mat_path = opts.get("neighbor_mat_path", _default_asset_path("cifti_surf_neighbors_lr_normalwall.npz"))
    slope_kmax = opts.get("slope_kmax", 400)
    slope_low_skip = opts.get("slope_low_skip", 5)
    slope_high_frac = opts.get("slope_high_frac", 0.10)
    headline_lambda = opts.get("headline_lambda", 10)
    network_assignment_lambda = float(opts.get("network_assignment_lambda", headline_lambda))
    structure_assignment_lambda = float(opts.get("structure_assignment_lambda", headline_lambda))
    compute_morans = opts.get("compute_morans", True)
    compute_slope = opts.get("compute_slope", True)
    compute_network_histograms = bool(opts.get("compute_network_histograms", False))
    compute_structure_histograms = bool(opts.get("compute_structure_histograms", False))
    fc_demean = opts.get("fc_demean", False)
    SparseIdxOverride = opts.get("SparseIdxOverride", None)
    SparseIdxOverrideBypassStructures = bool(opts.get("SparseIdxOverrideBypassStructures", False))
    BinaryROI = opts.get("BinaryROI", None)
    BinaryROIThreshold = float(opts.get("BinaryROIThreshold", 0.5))

    if Structures is None or len(Structures) == 0:
        Structures = sorted(set(C["brainstructurelabel"]))

    BrainStructure = C["brainstructure"].copy()
    BrainStructure[BrainStructure < 0] = 0
    BrainStructureLabels = C["brainstructurelabel"]

    nCorticalVertices = int(np.sum(C["brainstructure"] == 1) + np.sum(C["brainstructure"] == 2))
    CorticalIdx = ~np.all(C["data"][:nCorticalVertices, :] == 0, axis=1)

    pri = _load_priors(Priors)
    PFC = np.asarray(pri["FC"], dtype=calc_dtype)
    if PFC.shape[0] != nCorticalVertices:
        raise ValueError(
            f"Priors.FC must have {nCorticalVertices} rows (full cortex), found {PFC.shape[0]}."
        )

    structures_idx = [
        i + 1 for i, s in enumerate(BrainStructureLabels) if s in set(Structures)
    ]
    keepIdx = np.where(
        np.isin(BrainStructure, structures_idx) & ~np.all(C["data"] == 0, axis=1)
    )[0] + 1  # 1-based
    valid_nonzero_idx = np.where(~np.all(C["data"] == 0, axis=1))[0] + 1  # 1-based

    if BinaryROI is not None:
        SparseIdx = _load_binary_roi_as_sparse_idx(C, BinaryROI, threshold=BinaryROIThreshold)
        SparseIdxOverrideBypassStructures = True
    elif SparseIdxOverride is not None and len(SparseIdxOverride) > 0:
        SparseIdx = np.asarray(SparseIdxOverride, dtype=np.int64).ravel()
    else:
        SparseIdx = sparse_parcellation(C, neighbor_mat_path)

    # Enforce structure filtering + drop invalid rows
    if SparseIdxOverrideBypassStructures:
        SparseIdx = SparseIdx[np.isin(SparseIdx, valid_nonzero_idx)]
    else:
        SparseIdx = SparseIdx[np.isin(SparseIdx, keepIdx)]

    # Optional additional random subsampling (deterministic, evenly spaced)
    if "SparseFrac" in opts and opts["SparseFrac"] is not None and not SparseIdxOverrideBypassStructures:
        Nfull = SparseIdx.size
        Nkeep = max(1, int(round(opts["SparseFrac"] * Nfull)))
        idx = np.round(np.linspace(1, Nfull, Nkeep)).astype(int)
        idx = np.unique(np.clip(idx, 1, Nfull))
        SparseIdx = SparseIdx[idx - 1]
    if SparseIdx.size == 0:
        raise ValueError("No sparse targets available after filtering.")
    sparse_struct_idx = BrainStructure[SparseIdx - 1]
    sparse_struct_label = [
        _collapse_lr_structure_label(BrainStructureLabels[int(i) - 1]) if int(i) >= 1 else "UNKNOWN"
        for i in sparse_struct_idx
    ]

    # Functional connectivity
    Xfull = np.asarray(C["data"][:nCorticalVertices, :], dtype=calc_dtype)
    X = Xfull[CorticalIdx, :]
    Y = np.asarray(C["data"][SparseIdx - 1, :], dtype=calc_dtype)

    muX = np.mean(X, axis=1, keepdims=True)
    sX = np.std(X, axis=1, ddof=1, keepdims=True)
    sX[sX == 0] = np.inf
    muY = np.mean(Y, axis=1, keepdims=True)
    sY = np.std(Y, axis=1, ddof=1, keepdims=True)
    sY[sY == 0] = np.inf

    Xz = (X - muX) * (1.0 / sX)
    Yz = (Y - muY) * (1.0 / sY)

    P = PFC[CorticalIdx, :]

    n_targets = Yz.shape[0]
    if block_size <= 0:
        block_size = n_targets
    block_size = max(1, min(block_size, n_targets))

    # Ridge regression setup (SVD of priors templates).
    Xpred = P
    U, s, Vt = np.linalg.svd(Xpred, full_matrices=False)
    Vv = Vt.T
    eps = np.finfo(np.float64).eps
    lam_list = [float(l) for l in ridge_lambdas]
    lam_tags = {lam: f"Lambda{lam:g}" for lam in lam_list}
    r2_by_lam = {lam: np.full((n_targets,), np.nan, dtype=np.float64) for lam in lam_list}
    betas_by_lam = {}
    target_network_tag = f"Lambda{float(network_assignment_lambda):g}"
    network_idx = None
    if compute_network_histograms:
        if target_network_tag not in set(lam_tags.values()):
            raise ValueError("network_assignment_lambda must be included in ridge_lambdas.")
        network_idx = np.full((n_targets,), np.nan, dtype=np.float64)
    if keep_betas:
        for lam in lam_list:
            betas_by_lam[lam] = np.zeros((Xpred.shape[1], n_targets), dtype=np.float32)

    # Allocate FC only when needed (slope and/or FC map export).
    need_fc_matrix = compute_slope or keep_fc_map
    FC_full = None
    if need_fc_matrix:
        FC_full = np.zeros((Xz.shape[0], n_targets), dtype=calc_dtype)

    mI = np.array([])
    need_W = compute_morans or compute_slope
    W = None
    if need_W:
        if "W" in opts and opts["W"] is not None:
            W = opts["W"]
        else:
            W = build_cortex_adjacency(CorticalIdx, neighbor_mat_path)
    if compute_morans:
        mI = np.full((n_targets,), np.nan, dtype=np.float64)

    # NSI/ridge/Moran's I computed blockwise over sparse targets.
    for b0 in range(0, n_targets, block_size):
        b1 = min(n_targets, b0 + block_size)
        Yzb = Yz[b0:b1, :]
        FCb = (Xz @ Yzb.T) / (X.shape[1] - 1)
        if fc_demean:
            FCb = FCb - np.nanmean(FCb, axis=0, keepdims=True)
        if FC_full is not None:
            FC_full[:, b0:b1] = FCb.astype(calc_dtype, copy=False)

        # Ridge R^2 (and optional betas)
        UtYb = U.T @ FCb
        for lam in lam_list:
            w = s / (s ** 2 + lam)
            B = Vv @ (w[:, None] * UtYb)
            Yhat = Xpred @ B
            SSE = np.sum((FCb - Yhat) ** 2, axis=0)
            SST = np.sum((FCb - np.mean(FCb, axis=0, keepdims=True)) ** 2, axis=0)
            R2 = 1 - SSE / np.maximum(SST, eps)
            R2[R2 < 0] = np.nan
            r2_by_lam[lam][b0:b1] = R2
            if compute_network_histograms and lam_tags[lam] == target_network_tag:
                network_idx[b0:b1] = np.argmax(B, axis=0) + 1
            if keep_betas:
                betas_by_lam[lam][:, b0:b1] = B.astype(np.float32, copy=False)

        # Moran's I
        if compute_morans:
            mI[b0:b1] = morans_i_withW(FCb, W)

    Output: Dict[str, Any] = {"NSI": {"Ridge": {}}}

    for lam in lam_list:
        tag = lam_tags[lam]
        ridge_entry: Dict[str, Any] = {"R2": r2_by_lam[lam]}
        if keep_betas:
            ridge_entry["Betas"] = betas_by_lam[lam]
        Output["NSI"]["Ridge"][tag] = ridge_entry

    headTag = f"Lambda{float(headline_lambda):g}"
    if headTag not in Output["NSI"]["Ridge"]:
        raise ValueError("headline_lambda not in ridge_lambdas.")
    Output["NSI"]["MedianScore"] = np.nanmedian(Output["NSI"]["Ridge"][headTag]["R2"])
    if compute_network_histograms:
        n_networks = int(P.shape[1])
        network_labels = opts.get("network_labels")
        if network_labels is None:
            pri_labels = pri.get("NetworkLabels")
            if pri_labels is not None:
                pri_labels = np.asarray(pri_labels, dtype=object).ravel().tolist()
                network_labels = [_label_to_str(x) for x in pri_labels[:n_networks]]
            else:
                network_labels = [f"Network {k:02d}" for k in range(1, n_networks + 1)]
        if len(network_labels) < n_networks:
            raise ValueError("network_labels length must be at least number of prior networks.")
        network_labels = list(network_labels[:n_networks])
        network_colors = opts.get("network_colors")
        if network_colors is None:
            pri_colors = pri.get("NetworkColors")
            if pri_colors is not None:
                c = np.asarray(pri_colors, dtype=float)
                if c.ndim == 2 and c.shape[1] >= 3 and c.shape[0] >= n_networks:
                    network_colors = c[:n_networks, :3]
        if network_colors is not None:
            network_colors = np.asarray(network_colors, dtype=float)
            if network_colors.shape[0] < n_networks:
                raise ValueError("network_colors must have at least one row per prior network.")
            network_colors = network_colors[:n_networks, :3]
        net_rows: List[Dict[str, Any]] = []
        nsi_vals = np.asarray(Output["NSI"]["Ridge"][target_network_tag]["R2"], dtype=float).ravel()
        for k in range(1, n_networks + 1):
            mask = np.asarray(network_idx == k).ravel()
            vals = nsi_vals[mask]
            vals = vals[np.isfinite(vals)]
            net_rows.append(
                {
                    "network_index": int(k),
                    "network_label": str(network_labels[k - 1]),
                    "n_targets": int(mask.sum()),
                    "median_nsi": float(np.nanmedian(vals)) if vals.size else float("nan"),
                    "mean_nsi": float(np.nanmean(vals)) if vals.size else float("nan"),
                }
            )
        Output["NSI"]["NetworkAssignment"] = {
            target_network_tag: {
                "NetworkIndex": np.asarray(network_idx, dtype=np.int64),
                "NetworkLabels": list(network_labels),
                "NetworkColors": network_colors.tolist() if network_colors is not None else None,
                "Summary": net_rows,
            }
        }
    if compute_structure_histograms:
        struct_tag = f"Lambda{float(structure_assignment_lambda):g}"
        if struct_tag not in Output["NSI"]["Ridge"]:
            raise ValueError("structure_assignment_lambda must be included in ridge_lambdas.")
        nsi_vals = np.asarray(Output["NSI"]["Ridge"][struct_tag]["R2"], dtype=float).ravel()
        uniq = sorted(set(sparse_struct_label))
        struct_rows: List[Dict[str, Any]] = []
        for name in uniq:
            mask = np.asarray([s == name for s in sparse_struct_label], dtype=bool)
            vals = nsi_vals[mask]
            vals = vals[np.isfinite(vals)]
            struct_rows.append(
                {
                    "structure_label": str(name),
                    "n_targets": int(mask.sum()),
                    "median_nsi": float(np.nanmedian(vals)) if vals.size else float("nan"),
                    "mean_nsi": float(np.nanmean(vals)) if vals.size else float("nan"),
                }
            )
        Output["NSI"]["StructureAssignment"] = {
            struct_tag: {
                "StructureLabelsByTarget": list(sparse_struct_label),
                "StructureLabelsUnique": uniq,
                "Summary": struct_rows,
            }
        }

    # Moran's I
    if compute_morans:
        Output["MoransI"] = {"mI": mI}
    else:
        Output["MoransI"] = {"mI": np.array([])}

    # Spectral slope
    if compute_slope:
        if FC_full is None:
            raise RuntimeError("FC matrix unavailable for spectral slope computation")
        slope, freq, power = spectral_slope_withW(FC_full, W, slope_kmax, slope_low_skip, slope_high_frac)
        Output["SpectralSlope"] = {"slope": slope, "freq": freq, "power": power}
    else:
        Output["SpectralSlope"] = {"slope": np.array([]), "freq": np.array([]), "power": np.array([])}

    Output["Params"] = {
        "ridge_lambdas": ridge_lambdas,
        "neighbor_mat_path": neighbor_mat_path,
        "slope_kmax": slope_kmax,
        "slope_low_skip": slope_low_skip,
        "slope_high_frac": slope_high_frac,
        "headline_lambda": headline_lambda,
        "compute_morans": compute_morans,
        "compute_slope": compute_slope,
        "fc_demean": fc_demean,
        "SparseIdxOverride": SparseIdxOverride,
        "SparseIdxOverrideBypassStructures": SparseIdxOverrideBypassStructures,
        "BinaryROI": BinaryROI,
        "BinaryROIThreshold": BinaryROIThreshold,
        "SparseFrac": opts.get("SparseFrac", None),
        "compute_network_histograms": compute_network_histograms,
        "compute_structure_histograms": compute_structure_histograms,
        "network_assignment_lambda": network_assignment_lambda,
        "structure_assignment_lambda": structure_assignment_lambda,
        "lowmem": lowmem,
        "use_float32": use_float32,
        "keep_betas": keep_betas,
        "keep_fc_map": keep_fc_map,
        "block_size": block_size,
    }
    Maps: Dict[str, Any] = {"SparseIdx": SparseIdx}
    if keep_fc_map:
        fc_map = np.zeros((nCorticalVertices, n_targets), dtype=calc_dtype)
        if FC_full is not None:
            fc_map[CorticalIdx, :] = FC_full
        Maps["FC"] = fc_map
    return Output, Maps

if __name__ == "__main__":
    # Minimal smoke test using example data (NSI only to save time)
    priors = _default_asset_path("priors.npz")
    cifti = "ME01/Data.dtseries.nii"
    opts = {"compute_morans": False, "compute_slope": False, "ridge_lambdas": 10}
    structures = [
        "CORTEX_LEFT",
        "CEREBELLUM_LEFT",
        "ACCUMBENS_LEFT",
        "CAUDATE_LEFT",
        "PALLIDUM_LEFT",
        "PUTAMEN_LEFT",
        "THALAMUS_LEFT",
        "HIPPOCAMPUS_LEFT",
        "AMYGDALA_LEFT",
        "CORTEX_RIGHT",
        "CEREBELLUM_RIGHT",
        "ACCUMBENS_RIGHT",
        "CAUDATE_RIGHT",
        "PALLIDUM_RIGHT",
        "PUTAMEN_RIGHT",
        "THALAMUS_RIGHT",
        "HIPPOCAMPUS_RIGHT",
        "AMYGDALA_RIGHT",
    ]
    out, maps = pfm_nsi(cifti, structures, priors, opts)
    print("Median NSI:", out["NSI"]["MedianScore"])
