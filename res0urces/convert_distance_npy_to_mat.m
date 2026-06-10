function convert_distance_npy_to_mat(npyFile, outMatFile, varargin)
%CONVERT_DISTANCE_NPY_TO_MAT Convert pipeline DistanceMatrix.npy to MATLAB .mat.
%
%   convert_distance_npy_to_mat('DistanceMatrix.npy', 'DistanceMatrix.mat')
%
% The current ME-fMRI/PFM pipeline writes DistanceMatrix.npy as a uint8 NumPy
% array. Older code expects a v7.3 MAT file. 
% This converter reads the NPY data in row chunks and
% writes that variable without requiring the whole matrix to be duplicated in
% memory.
%
% Optional name/value pairs:
%   'VariableName'  MAT variable name. Default: 'D'
%   'ChunkRows'     Number of matrix rows copied per chunk. Default: 512
%   'Force'         Overwrite existing output file. Default: false

p = inputParser;
p.addRequired('npyFile', @(x) ischar(x) || isstring(x));
p.addRequired('outMatFile', @(x) ischar(x) || isstring(x));
p.addParameter('VariableName', 'D', @(x) ischar(x) || isstring(x));
p.addParameter('ChunkRows', 512, @(x) isnumeric(x) && isscalar(x) && x >= 1);
p.addParameter('Force', false, @(x) islogical(x) || isnumeric(x));
p.parse(npyFile, outMatFile, varargin{:});

npyFile = char(p.Results.npyFile);
outMatFile = char(p.Results.outMatFile);
varName = char(p.Results.VariableName);
chunkRows = double(p.Results.ChunkRows);
force = logical(p.Results.Force);

if ~isvarname(varName)
    error('VariableName must be a valid MATLAB variable name.');
end
if ~exist(npyFile, 'file')
    error('NPY file not found: %s', npyFile);
end

[outDir, ~, outExt] = fileparts(outMatFile);
if isempty(outExt)
    outMatFile = [outMatFile '.mat'];
end
if ~isempty(outDir) && ~exist(outDir, 'dir')
    mkdir(outDir);
end
if exist(outMatFile, 'file')
    if force
        delete(outMatFile);
    else
        error('Output file already exists: %s. Use ''Force'', true to overwrite.', outMatFile);
    end
end

info = local_read_npy_header(npyFile);
if numel(info.shape) ~= 2
    error('Expected a 2-D distance matrix, got shape [%s].', num2str(info.shape));
end
if ~strcmp(info.matlabType, 'uint8')
    error('Expected uint8 NPY data from the pipeline, got descr=%s.', info.descr);
end

nRows = double(info.shape(1));
nCols = double(info.shape(2));
if nRows ~= nCols
    warning('Distance matrix is not square: %d x %d.', nRows, nCols);
end

if info.fortranOrder
    mapShape = [nRows nCols];
else
    % C-order NPY rows are contiguous. Mapping as [nCols nRows] lets each
    % original row be read as one MATLAB column and transposed below.
    mapShape = [nCols nRows];
end

mm = memmapfile( ...
    npyFile, ...
    'Offset', info.dataOffset, ...
    'Format', {info.matlabType, mapShape, 'raw'}, ...
    'Writable', false);

m = matfile(outMatFile, 'Writable', true);
m.(varName)(nRows, nCols) = uint8(0);

fprintf('Converting %s -> %s (%s: %d x %d uint8)\n', npyFile, outMatFile, varName, nRows, nCols);
for rowStart = 1:chunkRows:nRows
    rowStop = min(rowStart + chunkRows - 1, nRows);
    rows = rowStart:rowStop;
    if info.fortranOrder
        chunk = mm.Data.raw(rows, :);
    else
        chunk = mm.Data.raw(:, rows).';
    end
    m.(varName)(rows, :) = chunk;
    fprintf('  rows %d-%d / %d\n', rowStart, rowStop, nRows);
end

fprintf('Done. MATLAB code can load with: S = load(''%s''); D = S.%s;\n', outMatFile, varName);
end

function info = local_read_npy_header(npyFile)
fid = fopen(npyFile, 'r');
if fid < 0
    error('Unable to open NPY file: %s', npyFile);
end
cleanup = onCleanup(@() fclose(fid));

magic = fread(fid, 6, 'uint8=>uint8')';
expected = uint8([147 double('NUMPY')]);
if numel(magic) ~= 6 || any(magic ~= expected)
    error('File does not have a valid NPY magic header: %s', npyFile);
end

version = fread(fid, 2, 'uint8=>uint8')';
if version(1) == 1
    headerLen = fread(fid, 1, 'uint16', 0, 'ieee-le');
elseif version(1) == 2 || version(1) == 3
    headerLen = fread(fid, 1, 'uint32', 0, 'ieee-le');
else
    error('Unsupported NPY version: %d.%d', version(1), version(2));
end

header = char(fread(fid, headerLen, 'char=>char')');
dataOffset = ftell(fid);

descrTok = regexp(header, '''descr''\s*:\s*''([^'']+)''', 'tokens', 'once');
if isempty(descrTok)
    error('Could not parse NPY dtype descriptor from header: %s', header);
end
descr = descrTok{1};

shapeTok = regexp(header, '''shape''\s*:\s*\(([^\)]*)\)', 'tokens', 'once');
if isempty(shapeTok)
    error('Could not parse NPY shape from header: %s', header);
end
shapeVals = regexp(shapeTok{1}, '\d+', 'match');
shape = str2double(shapeVals);

fortranOrder = ~isempty(regexp(header, '''fortran_order''\s*:\s*True', 'once'));

switch descr
    case {'|u1', '<u1', '>u1'}
        matlabType = 'uint8';
    otherwise
        matlabType = '';
end

info = struct( ...
    'descr', descr, ...
    'matlabType', matlabType, ...
    'shape', shape, ...
    'fortranOrder', fortranOrder, ...
    'dataOffset', dataOffset);
end
