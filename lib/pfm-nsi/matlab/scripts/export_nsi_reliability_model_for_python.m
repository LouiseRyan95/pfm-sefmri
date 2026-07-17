function export_nsi_reliability_model_for_python(out_path)
% Export NSI_reliability_model to Python-friendly format (no MATLAB objects).

here = fileparts(mfilename('fullpath'));
model_dir = fullfile(here, '..', 'models');
if nargin < 1 || isempty(out_path)
    out_path = fullfile(model_dir, 'nsi_reliability_model_py.mat');
end

load(fullfile(model_dir, 'nsi_reliability_model.mat'));
M = NSI_reliability_model;

for e = 1:numel(M.early)
    M.early(e).k_model = linear_model_to_struct(M.early(e).k_model);

    if isfield(M.early(e),'Rmax_model') && ~isempty(M.early(e).Rmax_model)
        M.early(e).Rmax_model = linear_model_to_struct(M.early(e).Rmax_model);
    else
        M.early(e).Rmax_model = [];
    end

    if isfield(M.early(e),'query') && ~isempty(M.early(e).query)
        for q = 1:numel(M.early(e).query)
            if isfield(M.early(e).query(q),'prob_models') && ~isempty(M.early(e).query(q).prob_models)
                for r = 1:numel(M.early(e).query(q).prob_models)
                    % export GLM to plain struct (for Python)
                    M.early(e).query(q).prob_models(r).mdl = glm_to_struct(M.early(e).query(q).prob_models(r).mdl);
                end
            end
        end
    end

NSI_reliability_model = M; %#ok<NASGU>
save(out_path, 'NSI_reliability_model', '-v7');

fprintf('Exported %s\n', out_path);
end

function S = linear_model_to_struct(mdl)
% Convert fitlm/LinearModel to a plain struct.

S = struct();
S.beta = mdl.Coefficients.Estimate;
S.cov  = mdl.CoefficientCovariance;
S.rmse = mdl.RMSE;
S.dfe  = mdl.DFE;

try
    ncoef = numel(S.beta);
    if ncoef == 2
        S.form = 'linear';
    elseif ncoef == 3
        S.form = 'quadratic';
    else
        S.form = 'linear';
    end
catch
    S.form = 'linear';
end

end

function S = glm_to_struct(mdl)
% Convert GeneralizedLinearModel to a plain struct.
S = struct();
try
    S.beta = mdl.Coefficients.Estimate;
    S.coef_names = mdl.CoefficientNames;
catch
    S.beta = [];
    S.coef_names = {};
end
try
    S.link = mdl.Link.Name;
catch
    S.link = 'logit';
end
end
end
