function OUT = pfm_nsi_plots(Input, UsabilityMdl, varargin)
%PFM_NSI_PLOTS MATLAB plotting wrapper aligned to Python output names.

if nargin < 2 || isempty(UsabilityMdl)
    UsabilityMdl = [];
end

p = inputParser;
p.addRequired('Input', @isstruct);
p.addRequired('UsabilityMdl');
p.addParameter('ShowPlots', true, @(x) islogical(x) && isscalar(x));
p.addParameter('SaveDir', '', @(x) ischar(x) || isstring(x));
p.addParameter('Prefix', 'pfm_nsi', @(x) ischar(x) || isstring(x));
p.addParameter('DPI', 150, @(x) isnumeric(x) && isscalar(x) && isfinite(x) && x > 0);
p.addParameter('NetworkHistograms', false, @(x) islogical(x) && isscalar(x));
p.addParameter('NetworkAssignmentLambda', 10, @(x) isnumeric(x) && isscalar(x) && isfinite(x));
p.addParameter('StructureHistograms', false, @(x) islogical(x) && isscalar(x));
p.addParameter('StructureAssignmentLambda', 10, @(x) isnumeric(x) && isscalar(x) && isfinite(x));
p.parse(Input, UsabilityMdl, varargin{:});
args = p.Results;

saveDir = char(args.SaveDir);
prefix = char(args.Prefix);
doSave = ~isempty(saveDir);
doPlot = args.ShowPlots;
if doSave && ~exist(saveDir, 'dir')
    mkdir(saveDir);
end

OUT = struct();
headline_lambda = 10;
ridge_tag = sprintf('Lambda%g', headline_lambda);

NSI_r2 = full(double(Input.NSI.Ridge.(ridge_tag).R2(:)));
MI = local_field_or_empty(Input, {'MoransI','mI'});
MI = full(double(MI(:)));
Slope = local_field_or_empty(Input, {'SpectralSlope','slope'});
Slope = full(double(Slope(:)));

OUT.data = struct('NSI_r2', NSI_r2, 'MI', MI, 'Slope', Slope);
OUT.figure_paths = struct();

if local_has_usability_model(UsabilityMdl)
    NSI_use = nanmedian(NSI_r2);
    p_hat = local_predict_binom_logit(UsabilityMdl.model, NSI_use);
    p_lo = interp1(UsabilityMdl.grid.x, UsabilityMdl.grid.ciLo, NSI_use, 'linear', 'extrap');
    p_hi = interp1(UsabilityMdl.grid.x, UsabilityMdl.grid.ciHi, NSI_use, 'linear', 'extrap');

    if p_hat >= 0.8
        label = 'High (0.8-1.0)';
    elseif p_hat >= 0.6
        label = 'Moderate-high (0.6-0.8)';
    elseif p_hat >= 0.4
        label = 'Moderate (0.4-0.6)';
    elseif p_hat >= 0.2
        label = 'Low (0.2-0.4)';
    else
        label = 'Very low (0.0-0.2)';
    end

    OUT.usability = struct();
    OUT.usability.summary_statistic = 'median';
    OUT.usability.summary_nsi = NSI_use;
    OUT.usability.NSI_median = NSI_use;
    OUT.usability.NSI_mean = NSI_use;
    OUT.usability.p_hat = p_hat;
    OUT.usability.ci95 = [p_lo p_hi];
    OUT.usability.decision = label;
    OUT.usability.thresholds = UsabilityMdl.thresholds;
    OUT.usability.expert_judgement_j = local_expert_judgement_j();

    fprintf('\n=== Prospective PFM usability projection ===\n\n');
    fprintf('Dataset summary\n');
    fprintf('  Summary NSI (median, R^2, λ=%d): %.3f\n\n', headline_lambda, NSI_use);
    fprintf('Predicted usability (from trained NSI model)\n');
    fprintf('  P(PFM-usable | NSI):         %.2f\n', p_hat);
    fprintf('  95%% confidence interval:     [%.2f, %.2f]\n', p_lo, p_hi);
    fprintf('  Decision band:               %s\n\n', label);
    J = local_expert_judgement_j();
    fprintf('Expert-judgement J thresholds\n');
    fprintf('  min J:                        %.3f\n', J.min);
    fprintf('  mean J:                       %.3f\n', J.mean);
    fprintf('  max J:                        %.3f\n', J.max);
    fprintf('\n===========================================\n\n');

    if doPlot
        h = local_plot_nsi_usability_curve_from_model(UsabilityMdl, NSI_use, p_hat);
    end
    if doSave && doPlot
        OUT.figure_paths.usability_curve = fullfile(saveDir, [prefix '_usability_curve.png']);
        local_save_figure(h.fig, OUT.figure_paths.usability_curve, args.DPI);
    end
end

if doPlot
    h = local_plot_hist_gray(NSI_r2, 'NSI');
    if doSave
        OUT.figure_paths.hist_nsi = fullfile(saveDir, [prefix '_hist_nsi.png']);
        local_save_figure(h, OUT.figure_paths.hist_nsi, args.DPI);
    end
end

if doPlot && ~isempty(MI)
    h = local_plot_hist_gray(MI, 'Moran''s I');
    if doSave
        OUT.figure_paths.hist_moransI = fullfile(saveDir, [prefix '_hist_moransI.png']);
        local_save_figure(h, OUT.figure_paths.hist_moransI, args.DPI);
    end
end

if doPlot && ~isempty(Slope)
    h = local_plot_hist_gray(Slope, 'Spectral slope');
    if doSave
        OUT.figure_paths.hist_slope = fullfile(saveDir, [prefix '_hist_slope.png']);
        local_save_figure(h, OUT.figure_paths.hist_slope, args.DPI);
    end
end

freq = local_field_or_empty(Input, {'SpectralSlope','freq'});
power = local_field_or_empty(Input, {'SpectralSlope','power'});
if doPlot && ~isempty(freq) && ~isempty(power)
    h = local_plot_power_spectra(double(freq(:)), double(power));
    if doSave
        OUT.figure_paths.power_spectra = fullfile(saveDir, [prefix '_power_spectra.png']);
        local_save_figure(h, OUT.figure_paths.power_spectra, args.DPI);
    end
end

if doPlot && args.NetworkHistograms
    ridge_tag = sprintf('Lambda%g', args.NetworkAssignmentLambda);
    net = local_field_or_empty(Input, {'NSI','NetworkAssignment',ridge_tag});
    if isstruct(net) && isfield(net,'NetworkIndex') && isfield(net,'NetworkLabels')
        h = local_plot_network_nsi_histograms(NSI_r2, double(net.NetworkIndex(:)), ...
            net.NetworkLabels, local_network_colors(net), local_finite_x_limits(NSI_r2));
        if doSave
            OUT.figure_paths.hist_nsi_by_network = fullfile(saveDir, [prefix '_hist_nsi_by_network.png']);
            local_save_figure(h, OUT.figure_paths.hist_nsi_by_network, args.DPI);
        end
    end
end

if doPlot && args.StructureHistograms
    ridge_tag = sprintf('Lambda%g', args.StructureAssignmentLambda);
    st = local_field_or_empty(Input, {'NSI','StructureAssignment',ridge_tag});
    if isstruct(st) && isfield(st,'StructureLabelsByTarget') && isfield(st,'StructureLabelsUnique')
        h = local_plot_structure_nsi_histograms(NSI_r2, st.StructureLabelsByTarget(:), ...
            st.StructureLabelsUnique(:), local_finite_x_limits(NSI_r2));
        if doSave
            OUT.figure_paths.hist_nsi_by_structure = fullfile(saveDir, [prefix '_hist_nsi_by_structure.png']);
            local_save_figure(h, OUT.figure_paths.hist_nsi_by_structure, args.DPI);
        end
    end
end
end

function tf = local_has_usability_model(UsabilityMdl)
tf = isstruct(UsabilityMdl) && isfield(UsabilityMdl, 'model') && ...
    isfield(UsabilityMdl, 'grid') && isfield(UsabilityMdl, 'thresholds');
end

function J = local_expert_judgement_j()
J = struct('min', 0.39, 'mean', 0.43, 'max', 0.488);
end

function out = local_field_or_empty(S, parts)
out = [];
for i = 1:numel(parts)
    key = parts{i};
    if ~isstruct(S) || ~isfield(S, key)
        return;
    end
    S = S.(key);
end
out = S;
end

function p = local_predict_binom_logit(mdl, nsi)
x = nsi - double(mdl.muNSI);
form = char(string(mdl.form));
beta = double(mdl.beta(:));
if strcmp(form, 'linear')
    eta = beta(1) + beta(2) * x;
elseif strcmp(form, 'quadratic')
    eta = beta(1) + beta(2) * x + beta(3) * (x.^2);
else
    error('Bad model form');
end
p = 1 ./ (1 + exp(-eta));
end

function h = local_plot_hist_gray(vals, ttl)
vals = vals(isfinite(vals));
h = figure('Color','w','Units','inches','Position',[1 1 3.2 3.0]);
histogram(vals, 40, 'FaceColor', [0.75 0.75 0.75], 'EdgeColor', 'none');
hold on;
if ~isempty(vals)
    m = median(vals);
    yl = ylim;
    plot([m m], yl, 'k-', 'LineWidth', 1);
end
set(gca, 'FontName', 'Arial', 'FontSize', 10, 'TickDir', 'out', 'Box', 'off');
title(ttl, 'FontWeight', 'normal');
ylabel('Count');
hold off;
end

function h = local_plot_power_spectra(freq, power)
[k, Nt] = size(power);
smooth_win = 5;
power_sm = zeros(k, Nt);
for j = 1:Nt
    power_sm(:,j) = local_smooth_vec(power(:,j), smooth_win);
end
meanPower_sm = mean(power_sm, 2, 'omitnan');

h = figure('Color','w','Units','inches','Position',[1 1 4 3]);
hold on;
for j = 1:Nt
    loglog(freq, power_sm(:,j), 'Color', [0.85 0.85 0.85], 'LineWidth', 0.5);
end
loglog(freq, meanPower_sm, 'k', 'LineWidth', 2);
vals = power_sm(:);
vals = vals(vals > 0 & isfinite(vals));
if ~isempty(vals)
    logvals = log10(vals);
    ylim([10^prctile(logvals,1) 10^prctile(logvals,99)]);
end
xlabel('Graph frequency (Laplacian eigenvalue)');
ylabel('Power');
title('Spatial power spectra');
set(gca, 'FontName', 'Arial', 'FontSize', 10, 'TickDir', 'out', 'Box', 'off');
hold off;
end

function h = local_plot_network_nsi_histograms(nsi, netIdx, labels, colors, xlims)
nNet = numel(labels);
nRows = 10;
nCols = max(2, ceil(nNet / nRows));
h = figure('Color','w','Units','inches','Position',[1 1 max(8.8,4.4*nCols) 11.5]);
for k = 1:nNet
    local_select_tile(nRows, nCols, k);
    vals = nsi(netIdx == k);
    vals = vals(isfinite(vals));
    if ~isempty(vals)
        histogram(vals, 30, 'FaceColor', colors(k,:), 'EdgeColor', 'none', 'FaceAlpha', 0.75);
        hold on;
        m = median(vals);
        yl = ylim;
        plot([m m], yl, 'k-', 'LineWidth', 1);
        hold off;
    end
    if ~isempty(xlims), xlim(xlims); end
    title(labels{k}, 'FontWeight', 'normal', 'HorizontalAlignment', 'left');
    ylabel('Count');
    set(gca, 'TickDir', 'out', 'Box', 'off', 'FontName', 'Arial', 'FontSize', 9);
end
for kk = (nNet+1):(nRows*nCols)
    local_select_tile(nRows, nCols, kk);
    axis off;
end
xlabel('NSI (R^2)');
end

function h = local_plot_structure_nsi_histograms(nsi, labelsByTarget, uniq, xlims)
nStruct = numel(uniq);
counts = zeros(nStruct,1);
for k = 1:nStruct
    counts(k) = sum(strcmp(labelsByTarget, uniq{k}));
end
[~, ix] = sort(counts, 'descend');
uniq = uniq(ix);
gray = linspace(0.25, 0.75, max(nStruct, 2));
nRows = 10;
nCols = max(2, ceil(nStruct / nRows));
h = figure('Color','w','Units','inches','Position',[1 1 max(8.8,4.4*nCols) 11.5]);
for k = 1:nStruct
    local_select_tile(nRows, nCols, k);
    mask = strcmp(labelsByTarget, uniq{k});
    vals = nsi(mask);
    vals = vals(isfinite(vals));
    if ~isempty(vals)
        histogram(vals, 30, 'FaceColor', [gray(k) gray(k) gray(k)], ...
            'EdgeColor', 'none', 'FaceAlpha', 0.85);
        hold on;
        m = median(vals);
        yl = ylim;
        plot([m m], yl, 'k-', 'LineWidth', 1);
        hold off;
    end
    if ~isempty(xlims), xlim(xlims); end
    title(uniq{k}, 'FontWeight', 'normal', 'HorizontalAlignment', 'left');
    ylabel('Count');
    set(gca, 'TickDir', 'out', 'Box', 'off', 'FontName', 'Arial', 'FontSize', 9);
end
for kk = (nStruct+1):(nRows*nCols)
    local_select_tile(nRows, nCols, kk);
    axis off;
end
xlabel('NSI (R^2)');
end

function local_select_tile(nRows, nCols, idx)
subplot(nRows, nCols, idx);
end

function xlims = local_finite_x_limits(vals)
v = vals(isfinite(vals));
if isempty(v)
    xlims = [];
    return;
end
lo = min(v);
hi = max(v);
if hi <= lo
    hi = lo + eps;
end
pad = 0.02 * (hi - lo);
xlims = [lo-pad hi+pad];
end

function y_s = local_smooth_vec(y, win)
if nargin < 2, win = 5; end
y = y(:);
if win <= 1 || numel(y) <= win
    y_s = y;
    return;
end
k = ones(win,1) / win;
y_s = conv(y, k, 'same');
end

function colors = local_network_colors(net)
nNet = numel(net.NetworkLabels);
colors = lines(max(nNet, 7));
if isfield(net, 'NetworkColors') && ~isempty(net.NetworkColors)
    c = double(net.NetworkColors);
    if size(c,1) >= nNet && size(c,2) >= 3
        colors = c(1:nNet,1:3);
    end
end
end

function h = local_plot_nsi_usability_curve_from_model(UsabilityMdl, pointNSI, pointP)
xgrid = UsabilityMdl.grid.x(:);
pHat = UsabilityMdl.grid.p(:);
ciLo = UsabilityMdl.grid.ciLo(:);
ciHi = UsabilityMdl.grid.ciHi(:);

fig = figure('Color','w','Position',[200 200 520 320]);
ax = axes(fig); hold(ax,'on');
set(ax,'Position',[0.15 0.22 0.75 0.62]);
set(ax,'FontName','Arial','FontSize',13,'TickDir','out','Box','off');
xlabel(ax,'NSI');
ylabel(ax,'P(PFM-usable)');
ylim(ax,[0 1]); yticks(ax,0:0.2:1);

xl = [min(xgrid) max(xgrid)];
pad = 0.03 * (xl(2) - xl(1));
xlim(ax,[xl(1)-pad xl(2)+pad]);

xL = xlim(ax);
yL = [0 1];
n = 300;
red = [0.85 0.30 0.30];
yellow = [0.95 0.85 0.30];
green = [0.35 0.75 0.45];
mid = 0.55;
C = zeros(n,1,3);
for i = 1:n
    t = (i-1)/(n-1);
    if t <= mid
        a = t / mid;
        col = (1-a) * red + a * yellow;
    else
        a = (t-mid) / (1-mid);
        col = (1-a) * yellow + a * green;
    end
    C(i,1,:) = col;
end
hImg = image(ax, [xL(1) xL(2)], [yL(1) yL(2)], C);
set(hImg, 'AlphaData', 0.18);
set(ax, 'YDir', 'normal');

bands = [ ...
    0.0 0.2 0.65 0.15 0.15; ...
    0.2 0.4 0.85 0.35 0.35; ...
    0.4 0.6 0.95 0.85 0.30; ...
    0.6 0.8 0.70 0.85 0.45; ...
    0.8 1.0 0.35 0.75 0.45];
for b = 1:size(bands,1)
    y0 = bands(b,1); y1 = bands(b,2);
    col = bands(b,3:5);
    patch(ax, [xL(1) xL(2) xL(2) xL(1)], [y0 y0 y1 y1], col, ...
        'EdgeColor', 'none', 'FaceAlpha', 0.08);
end

J = local_expert_judgement_j();
line(ax, [J.min J.min], [0 1], 'Color', [0.55 0.55 0.55], 'LineStyle', '-', 'LineWidth', 1.0);
line(ax, [J.max J.max], [0 1], 'Color', [0.55 0.55 0.55], 'LineStyle', '-', 'LineWidth', 1.0);
line(ax, [J.mean J.mean], [0 1], 'Color', [0 0 0], 'LineStyle', '-', 'LineWidth', 1.8);

patch(ax, [xgrid; flipud(xgrid)], [ciLo; flipud(ciHi)], ...
    [0.8 0.8 0.8], 'EdgeColor', 'none', 'FaceAlpha', 0.35);
plot(ax, xgrid, pHat, 'k-', 'LineWidth', 1.8);
scatter(ax, pointNSI, pointP, 45, 'k', 'filled');
hold(ax,'off');
h.fig = fig;
h.ax = ax;
end

function local_save_figure(fig, path, dpi)
try
    exportgraphics(fig, path, 'Resolution', dpi);
catch
    print(fig, path, '-dpng', sprintf('-r%d', round(dpi)));
end
end
