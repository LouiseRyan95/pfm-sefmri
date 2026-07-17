%% Example notebook: Using PFM-NSI for data quality assessment
%
% This script demonstrates how to use the PFM-NSI quality control
% framework to evaluate whether a given fMRI dataset is suitable for
% precision functional mapping (PFM).
%
% The primary output of this framework is the Network Similarity Index
% (NSI), which quantifies the extent to which large-scale functional
% network organization is reliably expressed in the data.
%
% ---------------------------------------------------------------------
% DEPENDENCIES
%
% This example relies on two classes of dependencies:
%
% (1) PFM-NSI scripts
%     All functions required for NSI computation (including pfm_nsi and
%     supporting utilities) are expected to be available on the MATLAB
%     path, for example by adding the current folder and its subfolders.
%
% (2) CIFTI I/O utilities
%     This notebook uses ft_read_cifti_mod and ft_write_cifti_mod for
%     loading and saving CIFTI files. These functions are distributed as
%     part of the Midnight Scan Club (MSC) codebase and can be obtained at:
%
%       https://github.com/MidnightScanClub/MSCcodebase
%
%     Ensure that the MSCcodebase/Utilities/read_write_cifti/
%     is added to your MATLAB path before running this notebook.
%
% ---------------------------------------------------------------------

%% Load required priors
%
% priors.mat contains group-level reference functional connectivity (FC)
% structure and related quantities used to compute the Network Similarity
% Index (NSI).
%
% These priors are derived from high-quality, densely sampled datasets and
% are treated as fixed reference inputs during QC.

load('priors.mat');
%Priors.FC = Priors.Alt.FC;

% By default, Priors.FC contains canonical FC templates corresponding to
% 20 large-scale functional networks described in Lynch et al. (2024, Nature).
% These templates largely follow network definitions developed at
% Washington University.
%
% Alternative network templates based on the parcellations of Yeo and
% colleagues are also provided in Priors.Alt.FC.
%
% Users may substitute these alternative priors if desired:
%   e.g., Priors.FC = Priors.Alt.FC;
%
% In practice, NSI values are very similar across these two sets of
% network templates, reflecting the shared large-scale organization of
% functional brain networks.


%% Load example dataset
%
% This is a CIFTI dtseries file containing preprocessed fMRI time series.
% The dataset shown here (ME01; CJL) has already been motion-censored.
%
% Users should replace this with their own dtseries file.

C = ft_read_cifti_mod([pwd '/ME01/Data.dtseries.nii']);

%% Use case #1:
% "Is my data good enough for precision functional mapping?"

%% Configure QC options
%
% opts controls which auxiliary metrics are computed in addition to NSI.
% These metrics are optional but can provide useful converging evidence.

opts = struct;

% Compute Moran's I to
% also quantify spatial autocorrelation
opts.compute_morans = true;

% Compute spatial power spectrum 
% slope (low- vs high-frequency balance)
opts.compute_slope   = true;

% Regularization strength for ridge regression steps
opts.ridge_lambdas   = 10;


%% Define structures to include in QC
%
% QC can be run on cortex only, subcortex only, or any combination.
% Here we include bilateral cortex, cerebellum, and major subcortical ROIs.

Structures = { ...
    'CORTEX_LEFT',      'CEREBELLUM_LEFT', ...
    'ACCUMBENS_LEFT',   'CAUDATE_LEFT', ...
    'PALLIDUM_LEFT',    'PUTAMEN_LEFT',    'THALAMUS_LEFT', ...
    'HIPPOCAMPUS_LEFT', 'AMYGDALA_LEFT', ...
    'CORTEX_RIGHT',     'CEREBELLUM_RIGHT', ...
    'ACCUMBENS_RIGHT',  'CAUDATE_RIGHT', ...
    'PALLIDUM_RIGHT',   'PUTAMEN_RIGHT',   'THALAMUS_RIGHT', ...
    'HIPPOCAMPUS_RIGHT','AMYGDALA_RIGHT'};

%% Load PFM usability model
%
% The usability model maps NSI values onto a probabilistic estimate
% of whether FC maps are likely to be interpretable and reliable
% for individual-level analyses.

load('nsi_usability_model.mat');

%% Run PFM-NSI
%
% pfm_nsi is the MATLAB entrypoint aligned to the Python CLI `run`
% command. It computes NSI, optional contextual metrics, optional model
% projections, and saves figures/outputs with Python-style names.
%
RunOut = pfm_nsi(C, ...
    'Priors', Priors, ...
    'Structures', Structures, ...
    'Opts', opts, ...
    'Usability', true, ...
    'UsabilityModel', NSI_usability_model, ...
    'OutDir', fullfile(pwd, 'pfm_nsi_out'), ...
    'Prefix', 'pfm_nsi');

QcPfm = RunOut.qc;

% NOTE ON RUNTIME:
%   - Runtime is currently on the order of several minutes.
%   - This reflects the use of a large number (~25k) of distributed
%     cortical targets (sparse seeds).
%   - Runtime can be reduced by randomly subsampling
%     the sparse target set using opts.SparseFrac.
%

% Example: retain 25% of sparse targets
% For this dataset, reduces run time from
% 395 seconds to 140 seconds; & produces nearly identical NSI
% opts.SparseFrac = 0.25;
% [QcPfm_SparseFrac, ~] = pfm_nsi_core(C, Structures, Priors, opts);
%
% Advanced (optional): use an explicit binary ROI as sparse targets.
% This overrides structure-based sparse seed generation and does not
% apply additional subsampling.
% opts.BinaryROI = '/path/to/roi_mask.dscalar.nii';
% opts.BinaryROIThreshold = 0.5;
%
% Advanced (optional): compute per-network NSI histograms where each
% sparse target is assigned to its best-matching network from ridge betas.
% opts.compute_network_histograms = true;
% opts.network_assignment_lambda = 10;
%
% Advanced (optional): compute per-structure NSI histograms with
% LH/RH labels collapsed (e.g., CORTEX_LEFT/CORTEX_RIGHT -> CORTEX).
% opts.compute_structure_histograms = true;
% opts.structure_assignment_lambda = 10;

%% Inspect saved summary
%
% pfm_nsi already generated plots, saved outputs, and computed the
% usability projection above. The returned plot summary mirrors the
% Python plotting summary object.

QcPfmSummary = RunOut.plot_summary;


%% Use case #2:
% "I collected a short (~10 min) scout scan.
%  Based on the data quality so far, how likely am I to reach high FC
%  reliability with extended scanning (e.g., 60 minutes total)?"
%
% This use case illustrates how early NSI estimates from a short scan
% can be combined with empirically observed reliability growth curves
% to support prospective decision-making about scan duration needed for
% stable indivdual-level FC inferences.

%% -------------------------------
% Simulate a 10-minute scout scan
% -------------------------------
%
% For demonstration purposes, we simulate a scout scan by truncating
% the example dataset to the first 10 minutes of data.
%
% Users should replace this step with their actual short-duration scan,
% acquired early in a session to support prospective planning.

C_10m = C;
TR  = 1.355;                         % Repetition time (seconds) for ME01
Idx = 1:round((10 * 60) / TR);       % Timepoints corresponding to ~10 min
C_10m.data = C.data(:, Idx);

%% -------------------------------
% QC options (minimal configuration)
% -------------------------------
%
% Here we disable auxiliary spatial metrics and compute NSI only.
% This reflects a lightweight QC pass suitable for early-session
% decision-making based on limited data.

opts = struct;
opts.compute_morans = false;
opts.compute_slope  = false;
opts.ridge_lambdas  = 10;

%% Structures to include
%
% As in Use Case #1, we include cortex, cerebellum, and major subcortical
% structures bilaterally. This can be customized depending on the
% scientific question, acquisition coverage, and downstream analyses.

Structures = { ...
    'CORTEX_LEFT',      'CEREBELLUM_LEFT', ...
    'ACCUMBENS_LEFT',   'CAUDATE_LEFT', ...
    'PALLIDUM_LEFT',    'PUTAMEN_LEFT',    'THALAMUS_LEFT', ...
    'HIPPOCAMPUS_LEFT', 'AMYGDALA_LEFT', ...
    'CORTEX_RIGHT',     'CEREBELLUM_RIGHT', ...
    'ACCUMBENS_RIGHT',  'CAUDATE_RIGHT', ...
    'PALLIDUM_RIGHT',   'PUTAMEN_RIGHT',   'THALAMUS_RIGHT', ...
    'HIPPOCAMPUS_RIGHT','AMYGDALA_RIGHT'};

%% -------------------------------
% Run PFM QC on scout data (NSI only)
% -------------------------------
%
% NSI is computed using only the short-duration scout scan.
% Even at this early stage, NSI reflects how strongly the dominant
% large-scale FC organization is expressed in the data, which in turn
% helps contextualize expectations for additional data collection.

[QcPfm, ~] = pfm_nsi_core(C_10m, Structures, Priors, opts);

%% -------------------------------
% Load NSI-based reliability model
% -------------------------------
%
% This model summarizes empirical relationships between early NSI
% values and how FC reliability tends to accumulate as scan duration
% increases.
%
% It is learned from independent datasets spanning a range of data
% qualities, sites, and acquisition protocols, and is intended to
% support prospective interpretation rather than subject-specific
% prediction.

load('nsi_reliability_model.mat');

%% -------------------------------
% Evaluate reliability expectations at a target duration
% -------------------------------
%
% Using the early NSI estimate, we quantify how likely it is that FC
% reliability will reach specified levels by a target total scan time.
%
% These estimates are intended to support planning decisions rather than
% to provide a deterministic forecast.
%
% Key parameters:
%  - DecisionT: target scan duration (in minutes)
%  - Thresholds: reliability (R²) levels used to contextualize sufficiency
%  - Plot: generate a visualization summarizing expected outcomes
%  - Verbose: print an interpretable summary to the console

OUT_10m = conditional_reliability_from_nsi(QcPfm, NSI_reliability_model, ...
    'NSI_T',10,'QueryT',60);

%% Interpretation notes
%
% OUT contains probabilistic summaries such as:
%  - P(R ≥ threshold | NSI, DecisionT)
%  - Expected range of reliability accumulation by DecisionT
%
% These outputs are intended to help answer questions like:
%  "Given the quality of the data so far, how reasonable is it to expect
%   that additional scanning will yield stable, interpretable
%   individual-level FC maps by this point in the session?"

%% ===============================================================
%% Use case #3:
% "I have already collected ~30 minutes of data.
%  Based on the data quality, how reliable is my FC likely to be
%  right now?"
%
% This use case illustrates how NSI can be used to contextualize
% the expected reliability of an existing dataset, without
% projecting gains from additional data collection.
%
% Rather than asking how much more data is needed, this scenario
% addresses whether the data currently in hand is likely to support
% stable, interpretable individual-level FC inferences.

%% --------------------------------
% Simulate a 30-minute dataset
% --------------------------------
%
% For demonstration purposes, we simulate an existing dataset by
% truncating the example data to the first ~30 minutes.
%
% Users should replace this step with their full dataset when
% evaluating data already collected.

C_30m = C;
TR  = 1.355;                          % Repetition time (seconds)
Idx = 1:round((30 * 60) / TR);        % Timepoints corresponding to ~30 min
C_30m.data = C.data(:, Idx);

%% -------------------------------
% QC options (minimal configuration)
% -------------------------------
%
% As in prior use cases, we compute NSI only, reflecting a lightweight
% summary of large-scale network organization relevant to FC reliability.

opts = struct;
opts.compute_morans = false;
opts.compute_slope  = false;
opts.ridge_lambdas  = 10;

%% -------------------------------
% Structures to include
% -------------------------------
%
% Cortex, cerebellum, and major subcortical structures are included
% bilaterally, consistent with standard PFM analyses.

Structures = { ...
    'CORTEX_LEFT',      'CEREBELLUM_LEFT', ...
    'ACCUMBENS_LEFT',   'CAUDATE_LEFT', ...
    'PALLIDUM_LEFT',    'PUTAMEN_LEFT',    'THALAMUS_LEFT', ...
    'HIPPOCAMPUS_LEFT', 'AMYGDALA_LEFT', ...
    'CORTEX_RIGHT',     'CEREBELLUM_RIGHT', ...
    'ACCUMBENS_RIGHT',  'CAUDATE_RIGHT', ...
    'PALLIDUM_RIGHT',   'PUTAMEN_RIGHT',   'THALAMUS_RIGHT', ...
    'HIPPOCAMPUS_RIGHT','AMYGDALA_RIGHT'};

%% -------------------------------
% Run PFM QC on existing data
% -------------------------------
%
% NSI is computed from the full ~30-minute dataset.
% At this duration, NSI reflects how clearly large-scale FC structure
% has emerged, providing a principled way to interpret expected
% FC reliability of the data already collected.

[QcPfm, ~] = pfm_nsi_core(C_30m, Structures, Priors, opts);

%% -------------------------------
% Load NSI-based reliability model
% -------------------------------
%
% This model captures empirically observed relationships between NSI
% and FC reliability at different scan durations, learned from
% independent datasets spanning a wide range of data qualities.

load('nsi_reliability_model.mat');

%% -------------------------------
% Evaluate reliability at current duration
% -------------------------------
%
% Using the observed NSI, we estimate the probability that FC
% reliability exceeds commonly used thresholds at the *current*
% scan duration.
%
% No assumptions are made about additional data collection.

OUT_30m = conditional_reliability_from_nsi(QcPfm, NSI_reliability_model, ...
    'NSI_T',30,'QueryT',30);

%% -------------------------------
% Interpretation notes
% -------------------------------
%
% OUT contains probabilistic summaries such as:
%  - P(R ≥ threshold | NSI, 30 min)
%  - Expected distribution of FC reliability at the current duration
%
% These outputs are intended to help answer questions like:
%  "Given the data I have already collected, how confident should I be
%   that individual-level FC estimates are stable and interpretable?"
%
% This use case is particularly relevant for retrospective QC,
% dataset screening, and deciding whether existing data are sufficient
% for downstream PFM analyses.

%% BETA 

%------------------------------------------------------------
% example call for new function
% ------------------------------------------------------------
OUT = conditional_reliability_from_nsi(QcPFM, NSI_reliability_model, ...
    'NSI_T', NSI_T, ...
    'QueryT',30, ...
    'Thresholds', [0.6 0.7 0.8], ...
    'Verbose', true, ...
    'Plot', true, ...                
    'DeterministicCI', false, ...
    'ProspectiveCI', false, ...
    'Nmc', 10^4);


%% ===============================================================
%% Use case #4:
%  Reliability-driven adaptive stopping rule
%
%  Combines:
%     - NSI-based projected reliability growth
%     - Explicit scan cost assumptions
%
%  to determine whether additional scan time is justified.
%
% ===============================================================

%% -------------------------------
% Load NSI-based reliability model
% -------------------------------
%
% This model captures empirically observed relationships between NSI
% and FC reliability at different scan durations, learned from
% independent datasets spanning a wide range of data qualities.

load('nsi_reliability_model.mat');

% ---------------------------------------------------------------
% Scan economics
% ---------------------------------------------------------------

CostPerHour   = 900;
CostPerMinute = CostPerHour / 60;
DeltaT        = 5;        % minutes per evaluation step
StartT        = 10;       % initial scout duration
MaxT          = 120;      % safety cap
Value_per_0p01_R = 200;
Value_per_R      = Value_per_0p01_R / 0.01;
Lambda = CostPerMinute / Value_per_R;

T = StartT;

fprintf('\n==================================================\n');
fprintf('Sequential Adaptive Stopping\n');
fprintf('Lambda (required gain/min): %.6f\n', Lambda);
fprintf('--------------------------------------------------\n');

while T + DeltaT <= MaxT
    
    
    c = C;
    TR  = 1.1;                          % Repetition time (seconds)
    Idx = 1:round((T * 60) / TR);        % Timepoints corresponding to ~30 min
    c.data = C.data(:, Idx);
    
    %% -------------------------------
    % QC options (minimal configuration)
    % -------------------------------
    %
    % As in prior use cases, we compute NSI only, reflecting a lightweight
    % summary of large-scale network organization relevant to FC reliability.
    
    opts = struct;
    opts.compute_morans = false;
    opts.compute_slope  = false;
    opts.ridge_lambdas  = 10;
    
    %% -------------------------------
    % Structures to include
    % -------------------------------
    %
    % Cortex, cerebellum, and major subcortical structures are included
    % bilaterally, consistent with standard PFM analyses.
    
    Structures = { ...
        'CORTEX_LEFT',      'CEREBELLUM_LEFT', ...
        'ACCUMBENS_LEFT',   'CAUDATE_LEFT', ...
        'PALLIDUM_LEFT',    'PUTAMEN_LEFT',    'THALAMUS_LEFT', ...
    'HIPPOCAMPUS_LEFT', 'AMYGDALA_LEFT', ...
        'CORTEX_RIGHT',     'CEREBELLUM_RIGHT', ...
        'ACCUMBENS_RIGHT',  'CAUDATE_RIGHT', ...
        'PALLIDUM_RIGHT',   'PUTAMEN_RIGHT',   'THALAMUS_RIGHT', ...
    'HIPPOCAMPUS_RIGHT','AMYGDALA_RIGHT'};
    
    %% -------------------------------
    % Run PFM QC on existing data
    % -------------------------------
    %
    % NSI is computed from the full ~30-minute dataset.
    % At this duration, NSI reflects how clearly large-scale FC structure
    % has emerged, providing a principled way to interpret expected
    % FC reliability of the data already collected.
    
    [QcPfm, ~] = pfm_nsi_core(c, Structures, Priors, opts);
    
    
    % Current projection
    OUT_now = conditional_reliability_from_nsi(QcPfm, NSI_reliability_model, ...
        'NSI_T',StartT, ...
        'QueryT',T, ...
        'Verbose',false, ...
        'Plot',false);
    
    % Next projection
    OUT_next = conditional_reliability_from_nsi(QcPfm, NSI_reliability_model, ...
        'NSI_T',StartT, ...
        'QueryT',T + DeltaT, ...
        'Verbose',false, ...
        'Plot',false);

    R_now  = OUT_now.deterministic.R_hat;
    R_next = OUT_next.deterministic.R_hat;

    DeltaR = R_next - R_now;
    MarginalGain = DeltaR / DeltaT;

    fprintf('T = %3d min | R = %.3f | dR/dt = %.6f\n', ...
        T, R_now, MarginalGain);

    if MarginalGain < Lambda
        fprintf('Stopping criterion met at T = %d minutes\n', T);
        break;
    end

    T = T + DeltaT;

end

OptimalT = T;

fprintf('==================================================\n');
fprintf('Optimal scan duration: %d minutes\n', OptimalT);
fprintf('==================================================\n\n');

%% ===============================================================
%% Visualization of adaptive stopping
%% ===============================================================

T_grid = 0:1:120;

% Forecast using the NSI from the scout (StartT)
OUT_ref = conditional_reliability_from_nsi(QcPfm, ...
    NSI_reliability_model, ...
    'NSI_T',StartT, ...
    'QueryT',StartT, ...
    'Verbose',false, ...
    'Plot',false);

k_hat = OUT_ref.deterministic.k_hat;
Rmax  = NSI_reliability_model.Rmax;

R_curve = Rmax * (1 - exp(-k_hat .* T_grid));
dR_dT   = Rmax * k_hat .* exp(-k_hat .* T_grid);

figure('Color','w','Units','inches','Position',[1 1 7.5 3.5]);

% ---------------------------
% Panel 1: Reliability growth
% ---------------------------
subplot(1,2,1)
plot(T_grid, R_curve, 'k','LineWidth',2); hold on
xline(OptimalT,'r--','LineWidth',1.5);
scatter(OptimalT, ...
    Rmax*(1-exp(-k_hat*OptimalT)), ...
    60,'r','filled');

xlabel('Scan duration (min)')
ylabel('Projected reliability (R^2)')
title('Reliability growth curve')
ylim([0 1])
box off
set(gca,'TickDir','out')

% ---------------------------
% Panel 2: Marginal gain
% ---------------------------
subplot(1,2,2)
plot(T_grid, dR_dT, 'k','LineWidth',2); hold on
yline(Lambda,'r--','LineWidth',1.5);
xline(OptimalT,'r--','LineWidth',1.5);

xlabel('Scan duration (min)')
ylabel('Marginal gain (dR/dT)')
title('Marginal reliability gain')
box off
set(gca,'TickDir','out')


hold on

% Region where gain > Lambda
idx_good = dR_dT >= Lambda;
area(T_grid(idx_good), dR_dT(idx_good), ...
    'FaceColor',[0.85 0.95 0.85], ...
    'EdgeColor','none');

% Region where gain < Lambda
idx_bad = dR_dT < Lambda;
area(T_grid(idx_bad), dR_dT(idx_bad), ...
    'FaceColor',[0.95 0.95 0.95], ...
    'EdgeColor','none');

text(OptimalT+2, Lambda*1.5, ...
    sprintf('Stop at %d min',OptimalT), ...
    'Color','r','FontWeight','bold');
