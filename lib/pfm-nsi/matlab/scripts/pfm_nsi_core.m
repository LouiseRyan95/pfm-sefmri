function [Output, Maps] = pfm_nsi_core(C, Structures, Priors, opts)
% PFM_NSI_CORE Core NSI metric engine for MATLAB PFM-NSI.
%
% OVERVIEW
%   This function computes objective quality metrics to assess whether
%   functional connectivity (FC) estimates are suitable for precision
%   functional mapping (PFM).
%
%   The PRIMARY QC METRIC is the Network Similarity Index (NSI), which
%   quantifies how well each target's FC map expresses canonical large-scale
%   network structure using multivariate ridge regression (R²).
%
%   Two ADDITIONAL, OPTIONAL METRICS can be computed to help contextualize
%   NSI values by describing spatial structure in the FC maps:
%     (2) Moran’s I        — spatial autocorrelation / smoothness
%     (3) Spectral slope  — relative dominance of low vs high spatial
%                           frequency components
% -------------------------------------------------------------------------
% INPUTS
%
%   C : CIFTI struct or path
%       Compatible with ft_read_cifti_mod. Time × vertex data are assumed.
%
%   Structures : cell array of brainstructure labels to include
%       Example: {'CORTEX_LEFT','CORTEX_RIGHT'}
%       Use [] or '' to include all structures.
%
%   Priors : struct with fields
%       .FC  [nCortex × K]
%           Canonical FC templates defined on the full cortical surface.
%
%   opts : struct of optional parameters
%
%     --- NSI (PRIMARY METRIC) ---
%       .ridge_lambdas   : array of ridge penalties
%                          (default [1 5 10 25 50])
%       .headline_lambda : lambda whose R² is summarized in
%                          Output.NSI.MedianScore (default 10)
%       .block_size      : sparse-target batch size for blockwise processing
%                          (default 512; set <=0 for full-batch processing)
%       .keep_betas      : true/false, retain ridge beta maps in output
%                          (default false)
%       .keep_fc_map     : true/false, retain full FC map in Maps.FC
%                          (default false)
%
%     --- Sparse target (seed) selection ---
%       .SparseIdxOverride : [Nt × 1] vector of vertex/voxel indices
%           If provided, these indices are used directly as sparse targets
%           instead of calling sparse_parcellation().
%
%           Use this when:
%             • You want full control over seed locations
%             • You want to reuse a fixed sparse set across runs
%             • You want to test specific anatomical targets
%
%       .SparseFrac : scalar in (0,1], OPTIONAL
%           If provided, a random fraction of the internally generated
%           sparse targets is retained. This is applied *after*
%           sparse_parcellation() and structure filtering. This can reduce
%           run time.
%
%           Examples:
%             opts.SparseFrac = 0.5;   % keep 50% of sparse targets
%             opts.SparseFrac = 0.25;  % aggressive subsampling
%
%           Default behavior (unset or empty): no additional subsampling.
%
%     --- Optional spatial metrics (CONTEXTUAL) ---
%       .compute_morans  : true/false, compute Moran’s I (default true)
%       .compute_slope   : true/false, compute spectral slope (default true)
%
%     --- Spatial graph / spectral parameters ---
%       .neighbor_mat_path : path to surface neighbor table
%                            (default 'cifti_surf_neighbors_lr_normalwall.mat')
%       .W                 : precomputed cortical adjacency matrix (optional)
%
%       .slope_kmax      : max eigenmodes for spectral slope (default 400)
%       .slope_low_skip  : # of lowest modes excluded from fit (default 5)
%       .slope_high_frac : fraction of highest modes excluded (default 0.10)
%
%     --- FC preprocessing ---
%       .fc_demean : true/false
%           Demean FC maps across vertices (recommended for non-MGTR/GSR
%           data; default false).
%
% -------------------------------------------------------------------------
% OUTPUTS
%
%   Output : struct containing QC metrics
%
%     --- PRIMARY QC OUTPUT ---
%       .NSI.Ridge.LambdaXX    : ridge betas (optional) and R² for each lambda
%       .NSI.MedianScore       : median R² at opts.headline_lambda
%
%     --- CONTEXTUAL METRICS (OPTIONAL) ---
%       .MoransI.mI            : [1 × Nt] Moran’s I (empty if skipped)
%       .SpectralSlope.slope   : [1 × Nt] spectral slopes (empty if skipped)
%
%     --- Provenance ---
%       .Params                : resolved opts used for this run
%
%   Maps : struct with target indices and optional FC maps
%       .FC        : [nCortex × Nt] FC maps (only when opts.keep_fc_map=true)
%       .SparseIdx : [Nt × 1] sparse target indices
%
% -------------------- Setup & data --------------------
if ischar(C) || isstring(C)
    C = ft_read_cifti_mod(C);
end

if ~exist('opts','var') || isempty(opts), opts = struct(); end
if ~isfield(opts,'ridge_lambdas'),     opts.ridge_lambdas   = [1 5 10 25 50]; end
if ~isfield(opts,'neighbor_mat_path'), opts.neighbor_mat_path = local_default_model_path('cifti_surf_neighbors_lr_normalwall.mat'); end
if ~isfield(opts,'slope_kmax'),        opts.slope_kmax      = 400; end
if ~isfield(opts,'slope_low_skip'),    opts.slope_low_skip  = 5; end
if ~isfield(opts,'slope_high_frac'),   opts.slope_high_frac = 0.10; end
if ~isfield(opts,'headline_lambda'),   opts.headline_lambda = 10; end
if ~isfield(opts,'compute_morans'),    opts.compute_morans  = true; end
if ~isfield(opts,'compute_slope'),     opts.compute_slope   = true; end
if ~isfield(opts,'fc_demean'),         opts.fc_demean       = false; end % important for non-MGTR/GSR data.
if ~isfield(opts,'SparseIdxOverride')
    opts.SparseIdxOverride = [];
end
if ~isfield(opts,'SparseIdxOverrideBypassStructures')
    opts.SparseIdxOverrideBypassStructures = false;
end
if ~isfield(opts,'BinaryROI')
    opts.BinaryROI = [];
end
if ~isfield(opts,'BinaryROIThreshold')
    opts.BinaryROIThreshold = 0.5;
end
if ~isfield(opts,'compute_network_histograms')
    opts.compute_network_histograms = false;
end
if ~isfield(opts,'network_assignment_lambda')
    opts.network_assignment_lambda = opts.headline_lambda;
end
if ~isfield(opts,'compute_structure_histograms')
    opts.compute_structure_histograms = false;
end
if ~isfield(opts,'structure_assignment_lambda')
    opts.structure_assignment_lambda = opts.headline_lambda;
end
if ~isfield(opts,'block_size') || isempty(opts.block_size)
    opts.block_size = 512;
end
if ~isfield(opts,'keep_betas')
    opts.keep_betas = false;
end
if ~isfield(opts,'keep_fc_map')
    opts.keep_fc_map = false;
end

if isempty(Structures)
    Structures = unique(C.brainstructurelabel);
end

% Brain structure bookkeeping
BrainStructure       = C.brainstructure;
BrainStructure(BrainStructure < 0) = []; % drop -1 in local copy
BrainStructureLabels = C.brainstructurelabel;

% Cortex index from CIFTI
nCorticalVertices = nnz(C.brainstructure==1) + nnz(C.brainstructure==2);
CorticalIdx = ~all(C.data(1:nCorticalVertices,:)==0, 2); % cortex-only valid rows

% Sanity: Priors size must match full cortex height
assert(size(Priors.FC,1) == nCorticalVertices, ...
    'Priors.FC must have %d rows (full cortex), found %d.', nCorticalVertices, size(Priors.FC,1));

% All rows to keep (structures filter, drop constant-zero)
keepIdx = find( ismember(BrainStructure, find(ismember(BrainStructureLabels, Structures))) ...
    & ~all(C.data==0,2) );

% -------------------- Sparse target set --------------------
if ~isempty(opts.BinaryROI)
    SparseIdx = local_binary_roi_to_sparse_idx(C, opts.BinaryROI, opts.BinaryROIThreshold);
    opts.SparseIdxOverrideBypassStructures = true;
elseif ~isempty(opts.SparseIdxOverride)
    SparseIdx = opts.SparseIdxOverride(:);
else
    SparseIdx = sparse_parcellation(C, opts.neighbor_mat_path);
end

% Enforce structure filtering + drop invalid rows
if opts.SparseIdxOverrideBypassStructures
    nonzeroIdx = find(~all(C.data==0,2));
    SparseIdx = SparseIdx(ismember(SparseIdx, nonzeroIdx));
else
    SparseIdx = SparseIdx(ismember(SparseIdx, keepIdx));
end

% Optional additional random subsampling (OFF by default)
if isfield(opts,'SparseFrac') && ~isempty(opts.SparseFrac) && ~opts.SparseIdxOverrideBypassStructures
    Nfull = numel(SparseIdx); % number of seeds
    Nkeep = max(1, round(opts.SparseFrac * Nfull)); %  number of seeds to keep
    
    % Deterministic, evenly spaced selection
    idx = round(linspace(1, Nfull, Nkeep));
    idx = unique(min(max(idx,1), Nfull));
    SparseIdx = SparseIdx(idx);
    
end

% Sparse target structure labels (LH/RH-collapsed)
SparseStructIdx = BrainStructure(SparseIdx);
SparseStructLabel = cell(numel(SparseIdx),1);
for ii = 1:numel(SparseIdx)
    if SparseStructIdx(ii) >= 1 && SparseStructIdx(ii) <= numel(BrainStructureLabels)
        SparseStructLabel{ii} = collapse_lr_label(BrainStructureLabels{SparseStructIdx(ii)});
    else
        SparseStructLabel{ii} = 'UNKNOWN';
    end
end

% -------------------- Functional connectivity --------------------
X = double(C.data(CorticalIdx,:));      % Vcortex × T
Y = double(C.data(SparseIdx,:));        % Nt × T
muX = mean(X,2);  sX = std(X,0,2);  sX(sX==0)=Inf;
muY = mean(Y,2);  sY = std(Y,0,2);  sY(sY==0)=Inf;
Xz = (X - muX).* (1./sX);               % V × T
Yz = (Y - muY).* (1./sY);
Nt = size(Yz,1);
T = size(Xz,2);
if Nt == 0
    error('No sparse targets available after filtering.');
end
if opts.block_size <= 0
    blockSize = Nt;
else
    blockSize = min(Nt, max(1, round(opts.block_size)));
end

% ---------- Metric 1: Network similarity index (NSI) ------------------
% Ridge regression (SVD fast path), computed in target blocks.
P  = Priors.FC(CorticalIdx,:);          % V x K
[U,S,Vv] = svd(P,'econ'); s = diag(S);
lamList = double(opts.ridge_lambdas(:)');
Output.NSI.Ridge = struct();
for lambda = lamList
    tag = ['Lambda' num2str(lambda)];
    Output.NSI.Ridge.(tag).R2 = nan(1, Nt);
    if opts.keep_betas
        Output.NSI.Ridge.(tag).Betas = zeros(size(P,2), Nt, 'single');
    end
end
if opts.compute_network_histograms
    netTag = ['Lambda' num2str(opts.network_assignment_lambda)];
    assert(any(abs(lamList - double(opts.network_assignment_lambda)) < 1e-12), ...
        'network_assignment_lambda not in ridge_lambdas.');
    netIdx = nan(1, Nt);
else
    netTag = '';
    netIdx = [];
end

needFCMatrix = (opts.compute_slope || opts.keep_fc_map);
if needFCMatrix
    FC = zeros(size(Xz,1), Nt, 'like', Xz);  % Vcortex x Nt
else
    FC = [];
end

% -------------------- Adjacency (only if needed) --------------------
need_W = (opts.compute_morans || opts.compute_slope);
W = [];  % default
if need_W
    if isfield(opts,'W') && ~isempty(opts.W)
        W = opts.W;
    else
        W = build_cortex_adjacency(CorticalIdx, opts.neighbor_mat_path); % binary topology
    end
end
if opts.compute_morans
    Output.MoransI.mI = nan(1, Nt);
else
    Output.MoransI.mI = [];
end

for b0 = 1:blockSize:Nt
    b1 = min(Nt, b0 + blockSize - 1);
    Yzb = Yz(b0:b1,:);
    FCb = (Xz * Yzb.') / (T - 1);
    if opts.fc_demean
        FCb = bsxfun(@minus, FCb, mean(FCb, 1, 'omitnan'));
    end
    if needFCMatrix
        FC(:, b0:b1) = FCb;
    end

    if opts.compute_morans
        Output.MoransI.mI(b0:b1) = morans_i_withW(FCb, W);
    end

    UtYb = U' * FCb;
    for lambda = lamList
        w = s ./ (s.^2 + lambda);
        B = Vv * (bsxfun(@times, w, UtYb));     % K × Nb
        Yhat = P * B;
        SSE  = sum((FCb - Yhat).^2, 1);
        SST  = sum((FCb - mean(FCb,1)).^2, 1);
        R2   = 1 - SSE ./ max(SST, eps);
        R2(R2<0) = NaN;
        tag = ['Lambda' num2str(lambda)];
        Output.NSI.Ridge.(tag).R2(b0:b1) = R2;
        if opts.keep_betas
            Output.NSI.Ridge.(tag).Betas(:,b0:b1) = single(B);
        end
        if opts.compute_network_histograms && strcmp(tag, netTag)
            [~, idx] = max(B, [], 1);
            netIdx(b0:b1) = idx;
        end
    end
end

Maps.SparseIdx = SparseIdx;
if opts.keep_fc_map
    Maps.FC = zeros(nCorticalVertices, Nt, 'like', Xz);
    Maps.FC(CorticalIdx,:) = FC;
end

headTag = ['Lambda' num2str(opts.headline_lambda)];
assert(isfield(Output.NSI.Ridge, headTag), 'headline_lambda not in ridge_lambdas.');
Output.NSI.MedianScore = nanmedian(Output.NSI.Ridge.(headTag).R2);
if opts.compute_network_histograms
    nNet = size(P, 2);
    labels = cell(1,nNet);
    colors = [];
    if isfield(Priors, 'NetworkLabels') && ~isempty(Priors.NetworkLabels)
        rawLabels = Priors.NetworkLabels(:);
        if numel(rawLabels) >= nNet
            for k = 1:nNet
                labels{k} = char(rawLabels{k});
            end
        end
    end
    for k = 1:nNet
        if isempty(labels{k})
            labels{k} = sprintf('Network %02d', k);
        end
    end
    if isfield(Priors, 'NetworkColors') && ~isempty(Priors.NetworkColors)
        c = double(Priors.NetworkColors);
        if size(c,1) >= nNet && size(c,2) >= 3
            colors = c(1:nNet,1:3); % truncate to K; ignores extra Noise row
        end
    end
    summary = struct('network_index',{},'network_label',{},'n_targets',{},'median_nsi',{},'mean_nsi',{});
    nsiVals = Output.NSI.Ridge.(netTag).R2(:);
    for k = 1:nNet
        vals = nsiVals(netIdx(:)==k);
        vals = vals(isfinite(vals));
        summary(k).network_index = k;
        summary(k).network_label = labels{k};
        summary(k).n_targets = sum(netIdx(:)==k);
        if isempty(vals)
            summary(k).median_nsi = NaN;
            summary(k).mean_nsi = NaN;
        else
            summary(k).median_nsi = median(vals);
            summary(k).mean_nsi = mean(vals);
        end
    end
    Output.NSI.NetworkAssignment.(netTag).NetworkIndex = netIdx(:);
    Output.NSI.NetworkAssignment.(netTag).NetworkLabels = labels;
    Output.NSI.NetworkAssignment.(netTag).NetworkColors = colors;
    Output.NSI.NetworkAssignment.(netTag).Summary = summary;
end
if opts.compute_structure_histograms
    structTag = ['Lambda' num2str(opts.structure_assignment_lambda)];
    assert(isfield(Output.NSI.Ridge, structTag), 'structure_assignment_lambda not in ridge_lambdas.');
    nsiVals = Output.NSI.Ridge.(structTag).R2(:);
    uniq = unique(SparseStructLabel, 'stable');
    summary = struct('structure_label',{},'n_targets',{},'median_nsi',{},'mean_nsi',{});
    for k = 1:numel(uniq)
        mask = strcmp(SparseStructLabel, uniq{k});
        vals = nsiVals(mask);
        vals = vals(isfinite(vals));
        summary(k).structure_label = uniq{k};
        summary(k).n_targets = sum(mask);
        if isempty(vals)
            summary(k).median_nsi = NaN;
            summary(k).mean_nsi = NaN;
        else
            summary(k).median_nsi = median(vals);
            summary(k).mean_nsi = mean(vals);
        end
    end
    Output.NSI.StructureAssignment.(structTag).StructureLabelsByTarget = SparseStructLabel;
    Output.NSI.StructureAssignment.(structTag).StructureLabelsUnique = uniq;
    Output.NSI.StructureAssignment.(structTag).Summary = summary;
end

% -------------------- Metric 3: Spectral slope (optional) -----------
if opts.compute_slope
    if isempty(FC)
        error('FC matrix unavailable for spectral slope computation.');
    end
    [slope, freq, power] = spectral_slope_withW(FC, W, ...
        opts.slope_kmax, opts.slope_low_skip, opts.slope_high_frac);
    Output.SpectralSlope.slope = slope;   % [1 x Nt]
    Output.SpectralSlope.freq  = freq;    % [k x 1]
    Output.SpectralSlope.power = power;   % [k x Nt]
else
    Output.SpectralSlope.slope = [];
    Output.SpectralSlope.freq  = [];
    Output.SpectralSlope.power = [];
end

% (optional but handy) record effective opts for provenance
Output.Params = opts;

end

% ---------------------------- Helpers -----------------------------------

function W = build_cortex_adjacency(CorticalIdx, neighbor_mat_path)
CorticalIdx = CorticalIdx(:);
Vall = numel(CorticalIdx);
Nbr = smartload(neighbor_mat_path); % Vall x k
assert(size(Nbr,1) == Vall, 'Neighbor table rows must equal numel(CorticalIdx).');

Wfull = spalloc(Vall, Vall, Vall*6);
for i = 1:Vall
    nbrs = Nbr(i, 2:end);
    nbrs(nbrs==0 | isnan(nbrs)) = [];
    if ~isempty(nbrs), Wfull(i, nbrs) = 1; end
end
Wfull = max(Wfull, Wfull.');
W = Wfull(CorticalIdx, CorticalIdx);
W = max(W, W.');
end

function mI = morans_i_withW(X, W)
[V, ~] = size(X);
X  = X - mean(X,1);
WX = W * X;
num = sum(X .* WX, 1);
den = sum(X.^2, 1);
S0  = full(sum(W(:)));
mI  = (V / S0) * (num ./ max(den, eps));
end

function [slope, freq, power] = spectral_slope_withW(X, W, kmax, low_skip, high_frac)
if nargin < 3 || isempty(kmax),      kmax = 400; end
if nargin < 4 || isempty(low_skip),  low_skip = 5; end
if nargin < 5 || isempty(high_frac), high_frac = 0.10; end

[V, N] = size(X);
W = max(W, W.');                   % enforce symmetry
d = full(sum(W,2)); d(d<=0) = eps;
Dmh = spdiags(1./sqrt(d), 0, V, V);
Lsym = speye(V) - Dmh * W * Dmh;   % normalized Laplacian

% Estimate # of components (zero eigenvalues)
c = 1;
try
    if exist('graph','file') == 2 && exist('conncomp','file') == 2
        G = graph(W,'upper'); c = max(conncomp(G));
    else
        c = max(1, sum(full(sum(W~=0,2))==0));
    end
catch
end

kreq = min(V-1, kmax + c);

opts.isreal = 1; opts.issym = 1;
sigmas = [1e-6, 1e-5, 1e-4, 1e-3];
success = false;
for s = 1:numel(sigmas)
    try
        [Evec, Eval] = eigs(Lsym, kreq, sigmas(s), opts);
        success = true; break
    catch
    end
end
if ~success
    jitter = 1e-6;
    [Evec, Eval] = eigs(Lsym + jitter*speye(V), kreq, 'sa', opts);
end

[Eval, ix] = sort(diag(Eval));
Evec = Evec(:,ix);

% drop all DC modes
drop = min(c, numel(Eval));
Eval = Eval(drop+1:end);
Evec = Evec(:,drop+1:end);

% normalize input maps
X = X - mean(X,1);
X = X ./ max(std(X,0,1), eps);

coeff = Evec' * X;     % k x N
pw    = coeff.^2;

k = size(Evec,2);
hi_drop = max(1, floor(high_frac * k));
idx_fit = (low_skip+1) : (k - hi_drop);
idx_fit = idx_fit(idx_fit >= 1 & idx_fit <= k);

f    = Eval(idx_fit);
logf = log(f + 1e-12);

slope = nan(1,N);
use_robust = exist('robustfit','file') == 2;
for j = 1:N
    lp = log(pw(idx_fit, j) + 1e-12);
    if use_robust
        b = robustfit(logf, lp); slope(j) = b(2);
    else
        p = polyfit(logf, lp, 1); slope(j) = p(1);
    end
end

% additional outputs for visualization
freq  = Eval;  % [k x 1] spatial frequencies
power = pw;    % [k x N] power spectrum per target

end

function sub_sample = sparse_parcellation(C, neighbor_mat_path)
Nbr = smartload(neighbor_mat_path);
sub_sample = []; neighbors = [];
for i = 1:size(Nbr,1)
    if ~ismember(i, neighbors)
        sub_sample = [sub_sample i];
        neighbors  = [neighbors Nbr(i,2:end)];
    end
end
ncortverts = nnz(C.brainstructure==1) + nnz(C.brainstructure==2);
brain_structure = C.brainstructure;
C.pos(brain_structure==-1,:) = [];
subcortical_coords = C.pos(ncortverts+1:end,:);
D = pdist2(subcortical_coords, subcortical_coords);
subcort_neighbors = cell(1, size(D,1));
for i = 1:size(D,1)
    subcort_neighbors{i} = find(D(i,:) <= 2);
end
edge_voxels = [];
for i = 1:size(D,1)
    if ~ismember(i, edge_voxels)
        sub_sample = [sub_sample i + ncortverts];
        edge_voxels = [edge_voxels subcort_neighbors{i}];
    end
end
end

function p = local_default_model_path(filename)
here = fileparts(mfilename('fullpath'));
candidate = fullfile(here, '..', 'models', filename);
if exist(candidate, 'file')
    p = candidate;
else
    p = filename;
end
end

function X = smartload(path_in)
% Load first variable from a MAT file or return numeric input unchanged.
if isnumeric(path_in)
    X = path_in;
    return;
end
if ~(ischar(path_in) || isstring(path_in))
    error('smartload:BadInput', 'Input must be numeric or a MAT file path.');
end
s = load(char(path_in));
f = fieldnames(s);
if isempty(f)
    error('smartload:EmptyMat', 'No variables found in MAT file: %s', char(path_in));
end
X = s.(f{1});
end

function SparseIdx = local_binary_roi_to_sparse_idx(C, roi_source, thr)
% Convert a binary ROI source into 1-based sparse target indices.
nGray = size(C.data,1);
if nargin < 3 || isempty(thr)
    thr = 0.5;
end

if isnumeric(roi_source) || islogical(roi_source)
    vals = roi_source(:);
elseif ischar(roi_source) || isstring(roi_source)
    p = char(roi_source);
    if ~exist(p, 'file')
        error('Binary ROI file not found: %s', p);
    end
    [~,~,ext] = fileparts(lower(p));
    if strcmp(ext, '.mat')
        vals = smartload(p);
        vals = vals(:);
    elseif strcmp(ext, '.txt') || strcmp(ext, '.csv')
        vals = readmatrix(p);
        vals = vals(:);
    else
        R = ft_read_cifti_mod(p);
        vals = R.data(:);
    end
else
    error('Unsupported BinaryROI input type.');
end

if numel(vals) == nGray
    SparseIdx = find(double(vals) > thr);
else
    SparseIdx = double(vals(:));
end

SparseIdx = SparseIdx(isfinite(SparseIdx));
SparseIdx = round(SparseIdx);
SparseIdx = unique(SparseIdx(SparseIdx>=1 & SparseIdx<=nGray));
if isempty(SparseIdx)
    error('BinaryROI did not contain any valid target indices.');
end
end

function out = collapse_lr_label(in)
out = char(in);
if endsWith(out, '_LEFT')
    out = out(1:end-5);
elseif endsWith(out, '_RIGHT')
    out = out(1:end-6);
end
end
