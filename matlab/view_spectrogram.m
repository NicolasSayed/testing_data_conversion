function data = view_spectrogram(sessionFolder, varargin)
%VIEW_SPECTROGRAM Read, plot and optionally save a selected recording section.
% data = view_spectrogram(folder,'StartSweep',100,'StopSweep',500, ...
%     'SourceTimeZone','EST','OutputMat','section.mat');
% Use 'Show',false for export only. Other options pass to read_fieldfox.
p = inputParser; p.KeepUnmatched = true; p.PartialMatching = false;
addParameter(p,'OutputMat',''); addParameter(p,'Show',true);
addParameter(p,'ColorLimits',[]); parse(p,varargin{:});
names = fieldnames(p.Unmatched); options = cell(1,2*numel(names));
for k = 1:numel(names), options(2*k-1:2*k)={names{k},p.Unmatched.(names{k})}; end
data = read_fieldfox(sessionFolder,options{:});
assert(numel(data.frequency_hz)>=2 && numel(data.elapsed_s)>=2, ...
    'fieldfox:plot','A frequency waterfall needs at least two sweeps and two frequency bins.');
assert(all(diff(data.timestamp_ticks)>0),'fieldfox:plot','Sweep timestamps must increase strictly.');
assert(any(isfinite(data.power_dbm(:))),'fieldfox:plot','No finite power values.');
if p.Results.Show
    figure('Name','FieldFox spectrogram','Color','w'); ax=axes;
    % Explicit bin edges preserve irregular sweep timing and the final row/bin.
    x = edges(data.frequency_hz)/1e6; y = edges(data.elapsed_s);
    c = data.power_dbm; c = [c c(:,end); c(end,:) c(end,end)];
    pcolor(ax,x,y,c); shading(ax,'flat'); axis(ax,'xy'); axis(ax,'tight');
    xlabel(ax,'Frequency (MHz)'); ylabel(ax,'Elapsed time from first selected sweep (s)');
    title(ax,sprintf('Sweeps %d..%d, trace slot %d',data.sweep_indices(1),data.sweep_indices(end),data.trace_slot));
    cb=colorbar(ax); ylabel(cb,'Recorded power (dBm)');
    if ~isempty(p.Results.ColorLimits), caxis(ax,p.Results.ColorLimits); end
end
if ~isempty(p.Results.OutputMat)
    target = char(java.io.File(char(p.Results.OutputMat)).getCanonicalPath());
    source = char(java.io.File(char(sessionFolder)).getCanonicalPath());
    assert(~strcmpi(target,source) && ~startsWith(lower(target),[lower(source) filesep]), ...
        'fieldfox:output','Export destination must be outside the input session.');
    assert(~isfile(target) && ~isfolder(target),'fieldfox:output','Export destination already exists.');
    parent = fileparts(target); if ~isfolder(parent), mkdir(parent); end
    temporary = [tempname(parent) '.mat']; cleanup=onCleanup(@() remove_temp(temporary));
    save(temporary,'-struct','data','-v7');
    assert(~isfile(target),'fieldfox:output','Export destination already exists.');
    [ok,msg]=movefile(temporary,target); assert(ok,'fieldfox:io',msg);
    fprintf('Saved %d sweeps x %d frequency bins to %s\n',size(data.power_dbm,1),size(data.power_dbm,2),target);
end
end

function result = edges(centers)
centers=centers(:)'; middle=(centers(1:end-1)+centers(2:end))/2;
result=[centers(1)-(middle(1)-centers(1)) middle centers(end)+(centers(end)-middle(end))];
end

function remove_temp(path)
if isfile(path), delete(path); end
end
