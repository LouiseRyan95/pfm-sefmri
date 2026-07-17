function OUT = pfm_nsi(C, varargin)
%PFM_NSI MATLAB orchestration entrypoint aligned to the Python CLI `run`.
%
% Example:
%   OUT = pfm_nsi('/path/to/Data.dtseries.nii', ...
%       'Usability', true, ...
%       'Reliability', true, ...
%       'OutDir', 'pfm_nsi_out', ...
%       'Prefix', 'pfm_nsi');

p = inputParser;
p.addRequired('C');
p.addParameter('Structures', local_default_structures(), @(x) iscell(x) || isstring(x) || ischar(x));
p.addParameter('Priors', [], @(x) isstruct(x) || ischar(x) || isstring(x));
p.addParameter('Opts', struct(), @isstruct);

p.addParameter('ModelsDir', local_default_models_dir(), @(x) ischar(x) || isstring(x));
p.addParameter('Usability', false, @(x) islogical(x) && isscalar(x));
p.addParameter('UsabilityModel', [], @(x) isstruct(x) || ischar(x) || isstring(x));
p.addParameter('Reliability', false, @(x) islogical(x) && isscalar(x));
p.addParameter('ReliabilityModel', [], @(x) isstruct(x) || ischar(x) || isstring(x));

p.addParameter('OutDir', 'pfm_nsi_out', @(x) ischar(x) || isstring(x));
p.addParameter('Prefix', 'pfm_nsi', @(x) ischar(x) || isstring(x));
p.addParameter('SaveFigs', true, @(x) islogical(x) && isscalar(x));
p.addParameter('DPI', 150, @(x) isnumeric(x) && isscalar(x) && isfinite(x) && x > 0);

p.addParameter('NSI_T', 10, @(x) isnumeric(x) && isscalar(x) && isfinite(x));
p.addParameter('QueryT', 60, @(x) isnumeric(x) && isvector(x) && all(isfinite(x)));
p.addParameter('Thresholds', [0.6 0.7 0.8], @(x) isnumeric(x) && isvector(x));
p.addParameter('Verbose', true, @(x) islogical(x) && isscalar(x));
p.parse(C, varargin{:});
args = p.Results;

if ischar(args.Structures) || isstring(args.Structures)
    Structures = cellstr(args.Structures);
else
    Structures = args.Structures;
end

outDir = char(args.OutDir);
prefix = char(args.Prefix);
if ~exist(outDir, 'dir')
    mkdir(outDir);
end

Priors = local_load_priors(args.Priors);
UsabilityMdl = [];
ReliabilityMdl = [];
if args.Usability
    UsabilityMdl = local_load_named_model(args.ModelsDir, args.UsabilityModel, 'nsi_usability_model.mat');
end
if args.Reliability
    ReliabilityMdl = local_load_named_model(args.ModelsDir, args.ReliabilityModel, 'nsi_reliability_model.mat');
end

[QcPfm, Maps] = pfm_nsi_core(C, Structures, Priors, args.Opts);

PlotSummary = pfm_nsi_plots(QcPfm, UsabilityMdl, ...
    'ShowPlots', args.SaveFigs, ...
    'SaveDir', local_if(args.SaveFigs, outDir, ''), ...
    'Prefix', prefix, ...
    'DPI', args.DPI, ...
    'NetworkHistograms', local_opt_value(args.Opts, 'compute_network_histograms', false), ...
    'NetworkAssignmentLambda', local_opt_value(args.Opts, 'network_assignment_lambda', 10), ...
    'StructureHistograms', local_opt_value(args.Opts, 'compute_structure_histograms', false), ...
    'StructureAssignmentLambda', local_opt_value(args.Opts, 'structure_assignment_lambda', 10));

paths = struct();
paths.nsi_mat = fullfile(outDir, [prefix '_nsi.mat']);
save(paths.nsi_mat, 'QcPfm', 'Maps', '-v7.3');

nsiSummary = local_nsi_summary(QcPfm);
paths.nsi_json = fullfile(outDir, [prefix '_nsi.json']);
local_write_json(paths.nsi_json, nsiSummary);

if local_opt_value(args.Opts, 'compute_network_histograms', false)
    netSummary = local_get_summary(QcPfm, {'NSI','NetworkAssignment',sprintf('Lambda%g', ...
        local_opt_value(args.Opts, 'network_assignment_lambda', 10)),'Summary'});
    if ~isempty(netSummary)
        paths.network_hist_summary_csv = fullfile(outDir, [prefix '_network_hist_summary.csv']);
        paths.network_hist_summary_json = fullfile(outDir, [prefix '_network_hist_summary.json']);
        local_write_summary_csv(paths.network_hist_summary_csv, netSummary, ...
            {'network_index','network_label','n_targets','median_nsi','mean_nsi'});
        local_write_json(paths.network_hist_summary_json, netSummary);
    end
end

if local_opt_value(args.Opts, 'compute_structure_histograms', false)
    structSummary = local_get_summary(QcPfm, {'NSI','StructureAssignment',sprintf('Lambda%g', ...
        local_opt_value(args.Opts, 'structure_assignment_lambda', 10)),'Summary'});
    if ~isempty(structSummary)
        paths.structure_hist_summary_csv = fullfile(outDir, [prefix '_structure_hist_summary.csv']);
        paths.structure_hist_summary_json = fullfile(outDir, [prefix '_structure_hist_summary.json']);
        local_write_summary_csv(paths.structure_hist_summary_csv, structSummary, ...
            {'structure_label','n_targets','median_nsi','mean_nsi'});
        local_write_json(paths.structure_hist_summary_json, structSummary);
    end
end

ReliabilityOut = [];
if args.Reliability
    ReliabilityOut = conditional_reliability_from_nsi(QcPfm, ReliabilityMdl, ...
        'NSI_T', args.NSI_T, ...
        'QueryT', args.QueryT, ...
        'Thresholds', args.Thresholds, ...
        'Verbose', args.Verbose, ...
        'Plot', args.SaveFigs);
    paths.reliability_mat = fullfile(outDir, [prefix '_reliability.mat']);
    save(paths.reliability_mat, 'ReliabilityOut', '-v7.3');
    paths.reliability_json = fullfile(outDir, [prefix '_reliability.json']);
    local_write_json(paths.reliability_json, ReliabilityOut);
    if args.SaveFigs && ishghandle(gcf)
        paths.reliability_png = fullfile(outDir, [prefix '_reliability_prob.png']);
        local_save_figure(gcf, paths.reliability_png, args.DPI);
    end
end

if args.Usability && isfield(PlotSummary, 'usability')
    paths.usability_json = fullfile(outDir, [prefix '_usability.json']);
    local_write_json(paths.usability_json, PlotSummary.usability);
end

OUT = struct();
OUT.qc = QcPfm;
OUT.maps = Maps;
OUT.plot_summary = PlotSummary;
OUT.reliability = ReliabilityOut;
OUT.paths = paths;
OUT.params = args;
end

function val = local_opt_value(opts, name, fallback)
if isfield(opts, name) && ~isempty(opts.(name))
    val = opts.(name);
else
    val = fallback;
end
end

function out = local_if(cond, a, b)
if cond
    out = a;
else
    out = b;
end
end

function modelDir = local_default_models_dir()
here = fileparts(mfilename('fullpath'));
modelDir = fullfile(here, '..', 'models');
end

function Priors = local_load_priors(src)
if isempty(src)
    src = fullfile(local_default_models_dir(), 'priors.mat');
end
if isstruct(src)
    Priors = src;
    return;
end
tmp = load(char(src));
if isfield(tmp, 'Priors')
    Priors = tmp.Priors;
else
    error('Priors variable not found in %s', char(src));
end
end

function mdl = local_load_named_model(modelsDir, explicit, filename)
if ~isempty(explicit)
    src = explicit;
else
    src = fullfile(char(modelsDir), filename);
end
if isstruct(src)
    mdl = src;
    return;
end
tmp = load(char(src));
vars = fieldnames(tmp);
if isempty(vars)
    error('No variables found in %s', char(src));
end
mdl = tmp.(vars{1});
end

function structures = local_default_structures()
structures = { ...
    'CORTEX_LEFT',      'CEREBELLUM_LEFT', ...
    'ACCUMBENS_LEFT',   'CAUDATE_LEFT', ...
    'PALLIDUM_LEFT',    'PUTAMEN_LEFT',    'THALAMUS_LEFT', ...
    'HIPPOCAMPUS_LEFT', 'AMYGDALA_LEFT', ...
    'CORTEX_RIGHT',     'CEREBELLUM_RIGHT', ...
    'ACCUMBENS_RIGHT',  'CAUDATE_RIGHT', ...
    'PALLIDUM_RIGHT',   'PUTAMEN_RIGHT',   'THALAMUS_RIGHT', ...
    'HIPPOCAMPUS_RIGHT','AMYGDALA_RIGHT'};
end

function summary = local_nsi_summary(QcPfm)
ridgeTag = 'Lambda10';
summary = struct();
summary.median_score = QcPfm.NSI.MedianScore;
if isfield(QcPfm.NSI,'Ridge') && isfield(QcPfm.NSI.Ridge, ridgeTag)
    summary.r2 = QcPfm.NSI.Ridge.(ridgeTag).R2(:)';
else
    summary.r2 = [];
end
end

function node = local_get_summary(S, parts)
node = [];
for i = 1:numel(parts)
    key = parts{i};
    if ~isstruct(S) || ~isfield(S, key)
        return;
    end
    S = S.(key);
end
node = S;
end

function local_write_summary_csv(path, rows, columns)
fid = fopen(path, 'w');
assert(fid ~= -1, 'Could not open %s for writing.', path);
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, '%s\n', strjoin(columns, ','));
for i = 1:numel(rows)
    vals = cell(1, numel(columns));
    for j = 1:numel(columns)
        key = columns{j};
        if isfield(rows(i), key)
            vals{j} = local_csv_value(rows(i).(key));
        else
            vals{j} = '';
        end
    end
    fprintf(fid, '%s\n', strjoin(vals, ','));
end
end

function s = local_csv_value(v)
if ischar(v) || isstring(v)
    s = char(string(v));
    s = ['"' strrep(s, '"', '""') '"'];
elseif isnumeric(v) || islogical(v)
    if isempty(v) || ~isscalar(v) || ~isfinite(double(v))
        s = '';
    else
        s = num2str(double(v), '%.12g');
    end
else
    s = '';
end
end

function local_write_json(path, value)
fid = fopen(path, 'w');
assert(fid ~= -1, 'Could not open %s for writing.', path);
cleanup = onCleanup(@() fclose(fid));
safeValue = local_json_safe(value);
try
    txt = jsonencode(safeValue, 'PrettyPrint', true);
catch
    txt = jsonencode(safeValue);
end
fprintf(fid, '%s\n', txt);
end

function out = local_json_safe(in)
if isstruct(in)
    if numel(in) > 1
        out = arrayfun(@local_json_safe_scalar, in, 'UniformOutput', false);
    else
        out = local_json_safe_scalar(in);
    end
elseif iscell(in)
    out = cellfun(@local_json_safe, in, 'UniformOutput', false);
elseif isnumeric(in) || islogical(in)
    out = double(in);
    out(~isfinite(out)) = NaN;
else
    out = in;
end
end

function out = local_json_safe_scalar(in)
out = struct();
f = fieldnames(in);
for i = 1:numel(f)
    out.(f{i}) = local_json_safe(in.(f{i}));
end
end

function local_save_figure(fig, path, dpi)
try
    exportgraphics(fig, path, 'Resolution', dpi);
catch
    print(fig, path, '-dpng', sprintf('-r%d', round(dpi)));
end
end
