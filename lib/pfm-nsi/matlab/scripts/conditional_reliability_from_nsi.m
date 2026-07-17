function OUT = conditional_reliability_from_nsi(QcPFM, NSI_reliability_model, varargin)
%CONDITIONAL_RELIABILITY_FROM_NSI
%
% PURPOSE
%   Given a dataset-level NSI computed from an "early" scan window (NSI_T),
%   predict functional connectivity (FC) reliability at one or more query
%   durations (QueryT) in two complementary ways:
%
%   (1) DETERMINISTIC FORECAST (continuous):
%         - Predict reliability curve parameters from NSI:
%             k_hat    = f_k(NSI)
%             Rmax_hat = f_Rmax(NSI)   (if available, else global fallback)
%         - Forecast expected reliability at each query time:
%             R_hat(T) = Rmax_hat * (1 - exp(-k_hat * T))
%         - Optionally compute uncertainty intervals for R_hat(T) by
%           Monte Carlo propagation through k and Rmax uncertainty.
%
%   (2) PROBABILISTIC ASSURANCE (binary threshold):
%         - For one or more reliability thresholds (e.g., 0.6/0.7/0.8),
%           predict:
%             P(R(T) >= Rth | NSI at NSI_T)   for each query time T.
%         - Uses pre-trained logistic models stored inside NSI_reliability_model.
%
% INPUTS
%   QcPFM : struct output of pfm_nsi_core / pfm_nsi containing NSI summary.
%           This function expects:
%             QcPFM.NSI.MedianScore
%
%   NSI_reliability_model : struct produced by train_nsi_reliability_forecast_v3
%           containing a grid of models across early windows and query times:
%             .early(e).EARLY_MIN
%             .early(e).k_model
%             .early(e).Rmax_model (optional)
%             .early(e).NSI_range  (optional)
%             .early(e).query(t).T_QUERY
%             .early(e).query(t).prob_models(r).mdl and .grid
%             .Rmax_global (fallback)
%
% OPTIONAL PARAMETERS (Name/Value)
%   'NSI_T'            : minutes used to compute NSI (default 10)
%   'QueryT'           : query minutes (scalar OR vector) (default 60)
%   'Thresholds'       : vector of thresholds for probabilistic output
%                        (default [0.6 0.7 0.8])
%   'Verbose'          : print diagnostics (default true)
%   'Plot'             : plot probabilistic curves (default true)
%
%   Deterministic CI options:
%   'DeterministicCI'  : compute uncertainty intervals for deterministic forecast
%                        (default true)
%   'ProspectiveCI'    : if true, uncertainty includes residual scatter (RMSE)
%                        from the regression, approximating uncertainty for a
%                        NEW dataset; if false, uses only mean uncertainty
%                        (default true)
%   'Nmc'              : Monte Carlo draws (default 5000)
%
% OUTPUT
%   OUT : struct with fields:
%     .input                : NSI and query settings
%     .model                : which submodel was used
%     .flags                : extrapolation warnings, CI settings, backward mask
%     .deterministic        : k_hat, Rmax_hat, R_hat(T), and optional CI bands
%     .probabilistic        : per-threshold P(R>=thr) at each query time + CI
%
% BEHAVIOR FOR QueryT VECTORS
%   - Deterministic: returns a full predicted reliability trajectory evaluated
%     at all QueryT values (after applying forward-only masking).
%   - Probabilistic: for each QueryT, selects the nearest trained T_QUERY model
%     and returns the probability estimates for each requested threshold.
%
% FORWARD-ONLY CONSTRAINT
%   - A forecast at time T is invalid if T < EARLY_MIN_used.
%   - For vector QueryT, invalid entries are set to NaN and flagged.
%
% -------------------------------------------------------------------------

%% ---------------- Parse inputs ------------------------------
p = inputParser;
p.addParameter('NSI_T', [], @(x) isnumeric(x) && isscalar(x) && isfinite(x));
p.addParameter('QueryT', [], @(x) isnumeric(x) && isvector(x) && all(isfinite(x)));
p.addParameter('Thresholds', [0.6 0.7 0.8], @(x) isnumeric(x) && isvector(x));

p.addParameter('Verbose', true, @(x) islogical(x) && isscalar(x));
p.addParameter('Plot', true, @(x) islogical(x) && isscalar(x));

% Deterministic CI controls
p.addParameter('DeterministicCI', true, @(x) islogical(x) && isscalar(x));
p.addParameter('ProspectiveCI', true, @(x) islogical(x) && isscalar(x));
p.addParameter('Nmc', 5000, @(x) isnumeric(x) && isscalar(x) && x > 100 && isfinite(x));

p.parse(varargin{:});

NSI_T     = p.Results.NSI_T;
T_QUERY   = p.Results.QueryT;
R_THRESH  = p.Results.Thresholds(:)';  % row vector
VERBOSE   = p.Results.Verbose;
DO_PLOT   = p.Results.Plot;

DO_DET_CI  = p.Results.DeterministicCI;
DO_PROS_CI = p.Results.ProspectiveCI;
NMC        = p.Results.Nmc;

%% ---------------- Defaults ------------------------------
if isempty(NSI_T),   NSI_T = 10;  end
if isempty(T_QUERY), T_QUERY = 60; end
T_QUERY = T_QUERY(:)';  % enforce row vector for consistent output shapes

%% ---------------- Extract NSI -------------------------------
assert(isfield(QcPFM,'NSI') && isfield(QcPFM.NSI,'MedianScore'), ...
    'QcPFM.NSI.MedianScore not found');
NSI_qc = QcPFM.NSI.MedianScore;

%% ============================================================
% STAGE 1: SELECT TRAINED SUBMODEL (choose EARLY_MIN nearest NSI_T)
%   - We do NOT “interpolate” early windows: we select the nearest trained
%     EARLY_MIN to the NSI window used to compute NSI.
%% ============================================================

EARLY_LIST = [NSI_reliability_model.early.EARLY_MIN];
[~, ie] = min(abs(EARLY_LIST - NSI_T));
early_mdl = NSI_reliability_model.early(ie);

if VERBOSE
    fprintf('Selected EARLY_MIN model: %d min (requested NSI_T=%g)\n', ...
        early_mdl.EARLY_MIN, NSI_T);
end

%% ============================================================
% STAGE 2: FLAGS / DIAGNOSTICS
%   - out-of-range NSI extrapolation
%   - forward-only validity mask for each query time
%% ============================================================

flags = struct();
flags.NSI_out_of_range = false;
flags.NSI_range = [NaN NaN];

if isfield(early_mdl,'NSI_range') && all(isfinite(early_mdl.NSI_range))
    flags.NSI_range = early_mdl.NSI_range;
    flags.NSI_out_of_range = (NSI_qc < early_mdl.NSI_range(1)) || (NSI_qc > early_mdl.NSI_range(2));
    if VERBOSE && flags.NSI_out_of_range
        fprintf('WARNING: NSI=%.3f outside training range [%.3f, %.3f] for EARLY_MIN=%d. Extrapolating.\n', ...
            NSI_qc, early_mdl.NSI_range(1), early_mdl.NSI_range(2), early_mdl.EARLY_MIN);
    end
end

% Forward-only constraint applied per query time
backward_mask = T_QUERY < early_mdl.EARLY_MIN;
flags.backward_query_mask = backward_mask;

if VERBOSE && any(backward_mask)
    fprintf('WARNING: %d/%d query times are < EARLY_MIN=%d and will be returned as NaN (forward-only).\n', ...
        nnz(backward_mask), numel(T_QUERY), early_mdl.EARLY_MIN);
end

% CI settings
flags.DeterministicCI = DO_DET_CI;
flags.ProspectiveCI  = DO_PROS_CI;
flags.Nmc            = NMC;

%% ============================================================
% STAGE 3: DETERMINISTIC RELIABILITY PREDICTION
%   - Predict k_hat and Rmax_hat from NSI
%   - Evaluate R_hat(T) for ALL query times T_QUERY
%% ============================================================

% --- Predict growth rate k from NSI ---
k_hat = predict(early_mdl.k_model, NSI_qc);

% --- Predict ceiling Rmax from NSI if available, else fallback ---
hasRmaxModel = isfield(early_mdl,'Rmax_model') && ~isempty(early_mdl.Rmax_model);

if hasRmaxModel
    Rmax_hat = predict(early_mdl.Rmax_model, NSI_qc);
else
    % fallback to global ceiling if model not present (backward compatible)
    if isfield(NSI_reliability_model,'Rmax_global')
        Rmax_hat = NSI_reliability_model.Rmax_global;
    elseif isfield(NSI_reliability_model,'Rmax')
        Rmax_hat = NSI_reliability_model.Rmax; % old field name
    else
        error('No Rmax model and no Rmax_global in NSI_reliability_model');
    end
end

% --- Clamp parameter predictions to plausible ranges ---
k_hat    = max(k_hat, 1e-8);
Rmax_hat = min(max(Rmax_hat, 0), 0.999);

% --- Evaluate deterministic forecast across requested query times ---
R_hat = Rmax_hat .* (1 - exp(-k_hat .* T_QUERY));
R_hat = min(max(R_hat, 0), 0.999);

% Apply forward-only invalidation
R_hat(backward_mask) = NaN;

%% ============================================================
% STAGE 4: DETERMINISTIC UNCERTAINTY (OPTIONAL)
%   - We draw k and Rmax samples around their predicted means and propagate
%     them through the growth curve across ALL query times.
%   - Output CI arrays are per-time (nT x 2).
%% ============================================================

R_CI95    = nan(numel(T_QUERY), 2);
k_CI95    = [NaN NaN];
Rmax_CI95 = [NaN NaN];

if DO_DET_CI

    % k uncertainty from fitlm at x=NSI_qc
    [mu_k, se_k, ci_k, sigma_k] = local_mu_se_fitlm(early_mdl.k_model, NSI_qc);
    k_CI95 = ci_k;

    % Rmax uncertainty (only if model exists)
    if hasRmaxModel
        [mu_R, se_R, ci_R, sigma_R] = local_mu_se_fitlm(early_mdl.Rmax_model, NSI_qc);
        Rmax_CI95 = ci_R;
    else
        mu_R = Rmax_hat;
        se_R = 0;
        sigma_R = 0;  % no learned residual scatter available
        Rmax_CI95 = [Rmax_hat Rmax_hat];
    end

    % Decide whether to include residual scatter (prospective uncertainty)
    if DO_PROS_CI
        se_k_eff = sqrt(se_k.^2 + sigma_k.^2);
        se_R_eff = sqrt(se_R.^2 + sigma_R.^2);
    else
        se_k_eff = se_k;
        se_R_eff = se_R;
    end

    % Monte Carlo draws of parameters
    k_samp    = mu_k + se_k_eff .* randn(NMC,1);
    Rmax_samp = mu_R + se_R_eff .* randn(NMC,1);

    k_samp    = max(k_samp, 1e-8);
    Rmax_samp = min(max(Rmax_samp, 0), 0.999);

    % Propagate across query times (NMC x nT)
    R_samp = Rmax_samp .* (1 - exp(-k_samp .* T_QUERY));  % implicit expansion
    R_samp = min(max(R_samp, 0), 0.999);

    % Compute per-time 95% intervals
    R_CI95(:,1) = prctile(R_samp, 2.5, 1)';
    R_CI95(:,2) = prctile(R_samp, 97.5, 1)';

    % Apply forward-only invalidation to CI
    R_CI95(backward_mask,:) = NaN;
end

%% ============================================================
% STAGE 5: ASSEMBLE OUTPUT STRUCT
%% ============================================================

OUT = struct();

% Inputs
OUT.input = struct();
OUT.input.NSI        = NSI_qc;
OUT.input.NSI_time   = NSI_T;
OUT.input.query_time = T_QUERY;
OUT.input.thresholds = R_THRESH;

% Model selection / bookkeeping
OUT.model = struct();
OUT.model.EARLY_MIN_used = early_mdl.EARLY_MIN;

% Store a global ceiling (if available) for transparency/debugging
if isfield(NSI_reliability_model,'Rmax_global')
    OUT.model.Rmax_global = NSI_reliability_model.Rmax_global;
elseif isfield(NSI_reliability_model,'Rmax')
    OUT.model.Rmax_global = NSI_reliability_model.Rmax;
else
    OUT.model.Rmax_global = NaN;
end

% Deterministic parameter estimates used for the full trajectory
OUT.model.k_hat    = k_hat;
OUT.model.Rmax_hat = Rmax_hat;

% Flags
OUT.flags = flags;

% Deterministic outputs
OUT.deterministic = struct();
OUT.deterministic.T_QUERY = T_QUERY;
OUT.deterministic.k_hat    = k_hat;
OUT.deterministic.Rmax_hat = Rmax_hat;
OUT.deterministic.R_hat    = R_hat;

OUT.deterministic.CI_supported   = DO_DET_CI;
OUT.deterministic.CI_prospective = DO_PROS_CI;
OUT.deterministic.k_CI95    = k_CI95;
OUT.deterministic.Rmax_CI95 = Rmax_CI95;
OUT.deterministic.R_CI95    = R_CI95;     % (nT x 2)
OUT.deterministic.CI_Nmc    = NMC;

%% ============================================================
% STAGE 6: PROBABILISTIC INFERENCE (OPTIONAL / MODEL-DEPENDENT)
%   - Loop over query times:
%       * choose the nearest trained query model for that time
%       * then loop over thresholds and evaluate P_hat + CI band
%
%   NOTE: Probabilistic models are stored per query_mdl (per T_QUERY grid).
%         Therefore, even if the deterministic trajectory can be evaluated at
%         any time, probabilistic results are tied to the nearest trained
%         query time model.
%% ============================================================

OUT.probabilistic = struct();
OUT.probabilistic.supported = true;

% Pre-initialize per-threshold containers (trajectory-shaped outputs)
for i = 1:numel(R_THRESH)
    R0  = R_THRESH(i);
    tag = sprintf('R_ge_%0.2f', R0);
    tag = strrep(tag,'.','p');

    OUT.probabilistic.(tag) = struct();
    OUT.probabilistic.(tag).R_thresh = R0;
    OUT.probabilistic.(tag).T_query  = T_QUERY;
    OUT.probabilistic.(tag).T_QUERY_used = nan(size(T_QUERY));   % nearest trained time used
    OUT.probabilistic.(tag).P_hat    = nan(size(T_QUERY));       % 1 x nT
    OUT.probabilistic.(tag).P_CI     = nan(numel(T_QUERY),2);    % nT x 2
end

% If no query field exists, nothing probabilistic can be done
if ~isfield(early_mdl,'query') || isempty(early_mdl.query)
    OUT.probabilistic.supported = false;
else
    QUERY_LIST_ALL = [early_mdl.query.T_QUERY];

    % ---- Outer loop: query times ----
    for tt = 1:numel(T_QUERY)

        tq = T_QUERY(tt);

        % Forward-only: skip invalid query times
        if tq < early_mdl.EARLY_MIN
            continue;
        end

        % Choose nearest trained query model to this query time
        [~, it] = min(abs(QUERY_LIST_ALL - tq));
        query_mdl = early_mdl.query(it);
        T_used = query_mdl.T_QUERY;

        % If no probabilistic models are present at this query time, mark unsupported
        if ~isfield(query_mdl,'prob_models') || isempty(query_mdl.prob_models)
            OUT.probabilistic.supported = false;
            continue;
        end

        % ---- Inner loop: thresholds ----
        for i = 1:numel(R_THRESH)

            R0  = R_THRESH(i);
            tag = sprintf('R_ge_%0.2f', R0);
            tag = strrep(tag,'.','p');

            % Record which trained query time was used for this entry
            OUT.probabilistic.(tag).T_QUERY_used(tt) = T_used;

            % Find the probability model corresponding to this threshold
            r = find([query_mdl.prob_models.R_thresh] == R0, 1);
            if isempty(r)
                % Leave NaNs in P_hat / P_CI for this timepoint
                continue;
            end

            pm   = query_mdl.prob_models(r);
            grid = pm.grid;

            % Point estimate for probability at this NSI
            P_hat = predict(pm.mdl, table(NSI_qc,'VariableNames',{'NSI'}));

            % Bootstrap-based uncertainty band (interpolate in NSI grid)
            P_lo  = interp1(grid.NSI, grid.P_lo, NSI_qc, 'linear','extrap');
            P_hi  = interp1(grid.NSI, grid.P_hi, NSI_qc, 'linear','extrap');

            OUT.probabilistic.(tag).P_hat(tt)   = P_hat;
            OUT.probabilistic.(tag).P_CI(tt,:)  = [P_lo P_hi];
        end
    end
end

%% ============================================================
% STAGE 7: OPTIONAL PLOT (probabilistic curves)
%   - For vector QueryT, we plot the probabilistic curves for ONE selected
%     query time to keep the visualization clean.
%   - Here we choose the LAST query time by default (often the “final target”).
%% ============================================================

if DO_PLOT

    % Select which query time to visualize
    tq_plot = T_QUERY(end);

    if VERBOSE && numel(T_QUERY) > 1
        fprintf('Plotting probabilistic curves for QueryT=%g (last element of QueryT vector).\n', tq_plot);
    end

    if isfield(early_mdl,'query') && ~isempty(early_mdl.query)
        QUERY_LIST_ALL = [early_mdl.query.T_QUERY];
        [~, it] = min(abs(QUERY_LIST_ALL - tq_plot));
        query_mdl = early_mdl.query(it);

        if isfield(query_mdl,'prob_models') && ~isempty(query_mdl.prob_models)

            FIG_W = 5.6; FIG_H = 3.1; FS = 10;
            cols = [0.75 0.75 0.75; 0.50 0.50 0.50; 0.20 0.20 0.20];
            lineStyles = {'-','--','-.'};
            red = [0.70 0.00 0.00];

            figure('Color','w','Units','inches','Position',[1 1 FIG_W FIG_H]);
            ax = gca;
            hold(ax,'on');
            yyaxis(ax,'left');

            xline(NSI_qc,'-','Color',[0.75 0 0],'LineWidth',1.4);
            curveHandles = gobjects(1, min(numel(R_THRESH),3));

            for i = 1:min(numel(R_THRESH),3)  % plotting supports up to 3 cleanly

                R0 = R_THRESH(i);

                pm = query_mdl.prob_models([query_mdl.prob_models.R_thresh] == R0);
                if isempty(pm), continue; end
                pm = pm(1);

                g  = pm.grid;

                % Force column vectors (guards against row/col issues)
                x     = g.NSI(:);
                P_med = g.P_med(:);
                P_lo  = g.P_lo(:);
                P_hi  = g.P_hi(:);

                % CI ribbon
                fill([x; flipud(x)], [P_lo; flipud(P_hi)], cols(i,:), ...
                    'FaceAlpha',0.10, 'EdgeColor','none');

                % Median curve
                curveHandles(i) = plot(x, P_med, ...
                    'Color', cols(i,:)*0.6, ...
                    'LineStyle', lineStyles{i}, ...
                    'LineWidth',2.2, ...
                    'DisplayName', sprintf('P(R^2 >= %.2f)', R0));
            end

            ylim([0 1]);
            box off
            ax.TickDir = 'out';
            ax.FontName = 'Arial';
            ax.FontSize = FS - 1;
            ax.Position = [0.12 0.16 0.76 0.74];
            ax.YColor = [0 0 0];

            xlabel(sprintf('NSI (%d min)', OUT.model.EARLY_MIN_used));
            ylabel(sprintf('P(R^2 \\ge threshold at %d min)', query_mdl.T_QUERY));

            % Deterministic point for the plotted time (use the closest index)
            [~, tt_plot] = min(abs(T_QUERY - tq_plot));
            Rhat_plot = OUT.deterministic.R_hat(tt_plot);
            status_txt = '';
            if isfield(flags,'NSI_out_of_range') && flags.NSI_out_of_range
                status_txt = local_format_extrapolation_status(NSI_qc, flags.NSI_range);
            end

            yyaxis(ax,'right');
            ylim([0 1]);
            ax.YColor = red;
            ax.FontSize = FS - 1;
            ax.TickDir = 'out';
            ylabel(sprintf('Deterministic R^2 at %d min', query_mdl.T_QUERY), ...
                'Color', red, 'FontSize', FS);
            hDet = scatter(NSI_qc, Rhat_plot, ...
                38, red, 'd', 'filled', 'MarkerEdgeColor', 'w', 'LineWidth', 0.8, ...
                'DisplayName', sprintf('Deterministic R^2(%.0f)', tq_plot));

            yyaxis(ax,'left');
            if ~isempty(status_txt)
                text(0.02, 0.97, status_txt, ...
                    'Units','normalized', ...
                    'HorizontalAlignment','left', ...
                    'VerticalAlignment','top', ...
                    'FontSize', FS - 1, ...
                    'Color', red, ...
                    'BackgroundColor', [1.00 0.96 0.96], ...
                    'Margin', 2);
            end

            title(sprintf('NSI=%.3f | Deterministic R^2(%.0f)=%.3f', NSI_qc, tq_plot, Rhat_plot), ...
                'FontWeight','normal', 'FontSize', FS + 0.5);

            keep = isgraphics(curveHandles);
            legend([curveHandles(keep) hDet], 'Location', 'southeast', 'Box', 'off', 'FontSize', 8);

            set(findall(gcf,'-property','FontName'),'FontName','Arial');
            set(findall(gcf,'-property','FontSize'),'FontSize',FS);
        end
    end
end

end

%% ========================================================================
% Local helper: mean/SE/CI for fitlm prediction at scalar x
% Returns:
%   mu    : predicted mean at x
%   se    : approx SE of predicted mean at x
%   ci95  : 95% CI for predicted mean at x (if available)
%   sigma : residual SD (RMSE) of the model (captures scatter around mean)
%% ========================================================================
function [mu, se, ci95, sigma] = local_mu_se_fitlm(mdl, x)

mu = NaN; se = NaN; ci95 = [NaN NaN];

% Residual scatter (useful for prospective prediction uncertainty)
try
    sigma = mdl.RMSE;
catch
    sigma = 0;
end

% Try numeric predict first (typical for fitlm built on vectors)
try
    [mu, ci95] = predict(mdl, x);
    se = (ci95(2) - ci95(1)) / (2*1.96);
    return;
catch
end

% If model expects table input (e.g., trained with named predictors), try that
try
    pname = mdl.PredictorNames{1};
    tblx = table(x, 'VariableNames', {pname});
    [mu, ci95] = predict(mdl, tblx);
    se = (ci95(2) - ci95(1)) / (2*1.96);
    return;
catch
end

% Fallback: point prediction only
try
    mu = predict(mdl, x);
    se = 0;
    ci95 = [mu mu];
catch
    mu = NaN; se = NaN; ci95 = [NaN NaN];
end

end

function status_txt = local_format_extrapolation_status(NSI_qc, NSI_range)
status_txt = 'EXTRAPOLATED: OUTSIDE TRAINING RANGE';
if numel(NSI_range) < 2 || any(~isfinite(NSI_range))
    return;
end
lo = NSI_range(1);
hi = NSI_range(2);
if NSI_qc < lo
    status_txt = sprintf('EXTRAPOLATED BELOW TRAINING RANGE [%.3f, %.3f]', lo, hi);
elseif NSI_qc > hi
    status_txt = sprintf('EXTRAPOLATED ABOVE TRAINING RANGE [%.3f, %.3f]', lo, hi);
end
end
