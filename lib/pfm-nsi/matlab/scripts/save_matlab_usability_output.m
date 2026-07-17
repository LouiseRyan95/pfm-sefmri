function save_matlab_usability_output(cifti_path, out_dir)
% Save MATLAB pfm_nsi usability output for comparison.
%
% Example:
%   save_matlab_usability_output('/path/to/Data.dtseries.nii', '/tmp/pfm_nsi_out')

if nargin < 1 || isempty(cifti_path)
    cifti_path = fullfile(pwd, 'ME01', 'Data.dtseries.nii');
end
if nargin < 2 || isempty(out_dir)
    out_dir = pwd;
end
if ~exist(out_dir, 'dir')
    mkdir(out_dir);
end

here = fileparts(mfilename('fullpath'));
model_dir = fullfile(here, '..', 'models');

load(fullfile(model_dir, 'priors.mat'));
load(fullfile(model_dir, 'nsi_usability_model.mat'));
C = ft_read_cifti_mod(cifti_path);

opts = struct;
opts.compute_morans = false;
opts.compute_slope  = false;
opts.ridge_lambdas  = 10;

Structures = { ...
    'CORTEX_LEFT',      'CEREBELLUM_LEFT', ...
    'ACCUMBENS_LEFT',   'CAUDATE_LEFT', ...
    'PALLIDUM_LEFT',    'PUTAMEN_LEFT',    'THALAMUS_LEFT', ...
    'HIPPOCAMPUS_LEFT', 'AMYGDALA_LEFT', ...
    'CORTEX_RIGHT',     'CEREBELLUM_RIGHT', ...
    'ACCUMBENS_RIGHT',  'CAUDATE_RIGHT', ...
    'PALLIDUM_RIGHT',   'PUTAMEN_RIGHT',   'THALAMUS_RIGHT', ...
    'HIPPOCAMPUS_RIGHT','AMYGDALA_RIGHT'};

[QcPfm, ~] = pfm_nsi_core(C, Structures, Priors, opts);
OUT = pfm_nsi_plots(QcPfm, NSI_usability_model, 'ShowPlots', false);

out_path = fullfile(out_dir, 'Usability_matlab.mat');
save(out_path, 'OUT', '-v7');

fprintf('Saved %s\n', out_path);
end
