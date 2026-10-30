function data = read_fieldfox(sessionFolder, varargin)
%READ_FIELDFOX Read numbered STA/TRC stores without Python or Data Link.
% data = read_fieldfox('D:\data\RTAUTOsession01');
% data = read_fieldfox(folder,'StartSweep',100,'StopSweep',500);
% Sweep indices and TraceSlot are ZERO-BASED; StopSweep is exclusive.
% Default: select up to 2000 original sweeps, never average them.
% Use 'MaxSweeps',Inf for every requested row (20 million cell limit).
% SourceTimeZone defaults to EST (fixed UTC-05:00), per the user's clock.
% Supported layouts match Python versions 1..18; RTSA needs one block and
% nonzero span. RPX index CRCs are not checked here; use Python inspect.

p = inputParser; p.PartialMatching = false;
addParameter(p,'StartSweep',0); addParameter(p,'StopSweep',Inf);
addParameter(p,'Step',1); addParameter(p,'MaxSweeps',2000);
addParameter(p,'FreqMinHz',-Inf); addParameter(p,'FreqMaxHz',Inf);
addParameter(p,'TraceSlot',0); addParameter(p,'SourceTimeZone','EST');
addParameter(p,'DSTFold',[]);
parse(p,varargin{:}); o = p.Results;
sessionFolder = char(java.io.File(char(sessionFolder)).getCanonicalPath());
assert(isfolder(sessionFolder),'fieldfox:input','Expected a complete session folder.');
sta = store_files(sessionFolder,'STA'); trc = store_files(sessionFolder,'TRC');
assert(~isempty(sta) && ~isempty(trc),'fieldfox:input','Missing STA or TRC store.');
states = struct([]);
for k = 1:numel(sta)
    assert(sta(k).bytes > 0 && mod(sta(k).bytes,104)==0,'fieldfox:truncated','Invalid STA file length.');
    [fid,msg] = fopen(sta(k).path,'rb'); assert(fid>=0,'fieldfox:io',msg);
    cleanup = onCleanup(@() fclose(fid));
    for n = 1:sta(k).bytes/104
        b = fread(fid,104,'*uint8'); assert(numel(b)==104,'fieldfox:truncated','Short state read.');
        s = state_header(b);
        assert(s.state_id==numel(states),'fieldfox:state','State IDs must be consecutive from zero.');
        if isempty(states), states=s;
        else, states(end+1)=s; end %#ok<AGROW>
    end
    clear cleanup
end
s0 = states(1);
for s = states
    assert(isequal([s.version s.application s.points s.blocks s.auxiliary], ...
        [s0.version s0.application s0.points s0.blocks s0.auxiliary]), ...
        'fieldfox:layout','Changing application, dimensions or version is unsupported.');
end
headerBytes = 32 + 12*(s0.version>=4);
stride = headerBytes + 4*(s0.points*s0.blocks+s0.auxiliary);
counts = [trc.bytes]/stride;
assert(all(counts>0 & counts==fix(counts)),'fieldfox:truncated','Invalid TRC file length.');
total = sum(counts); stop = min(o.StopSweep,total);
validateattributes(o.StartSweep,{'numeric'},{'scalar','integer','nonnegative','finite'});
validateattributes(o.Step,{'numeric'},{'scalar','integer','positive','finite'});
validateattributes(o.MaxSweeps,{'numeric'},{'scalar','positive'});
assert(isinf(o.MaxSweeps) || (isfinite(o.MaxSweeps) && o.MaxSweeps==fix(o.MaxSweeps)), ...
    'fieldfox:selection','MaxSweeps must be a positive integer or Inf.');
assert(isscalar(o.StopSweep) && o.StopSweep>o.StartSweep && ...
    (isinf(o.StopSweep) || (isfinite(o.StopSweep) && o.StopSweep==fix(o.StopSweep) && o.StopSweep<=total)), ...
    'fieldfox:selection','StopSweep must be an integer within the session, or Inf.');
assert(o.StartSweep<stop,'fieldfox:selection','Selection is empty.');
validateattributes(o.TraceSlot,{'numeric'},{'scalar','integer','nonnegative','finite'});
assert(o.TraceSlot<s0.blocks,'fieldfox:selection','TraceSlot exceeds the available blocks.');
assert(isscalar(o.FreqMinHz) && isscalar(o.FreqMaxHz) && ...
    ~isnan(o.FreqMinHz) && ~isnan(o.FreqMaxHz) && o.FreqMinHz<=o.FreqMaxHz, ...
    'fieldfox:selection','Invalid frequency bounds.');
requested = ceil((stop-o.StartSweep)/o.Step);
step = o.Step;
if isfinite(o.MaxSweeps), step = step*max(1,ceil(requested/o.MaxSweeps)); end
indices = (o.StartSweep:step:stop-1)'; rows = numel(indices);
assert(rows<=20000000 && rows*s0.auxiliary<=20000000, ...
    'fieldfox:memory','Selected auxiliary arrays exceed the allocation limit; select fewer sweeps.');
ticks = zeros(rows,1,'int64'); masks = zeros(rows,1,'uint8');
stateIds = zeros(rows,1,'uint16'); auxiliary = zeros(rows,s0.auxiliary,'single');
power = []; referenceAxis = []; axisKind = ''; base = 0; previousState = -1;
for k = 1:numel(trc)
    selected = find(indices>=base & indices<base+counts(k));
    if isempty(selected), base = base+counts(k); continue; end
    [fid,msg] = fopen(trc(k).path,'rb'); assert(fid>=0,'fieldfox:io',msg);
    cleanup = onCleanup(@() fclose(fid));
    for row = selected'
        index = indices(row); offset = (index-base)*stride;
        assert(fseek(fid,offset,'bof')==0,'fieldfox:io','Cannot seek to selected record.');
        b = fread(fid,stride,'*uint8'); assert(numel(b)==stride,'fieldfox:truncated','Short trace read.');
        sid = double(value(b,2,'uint16'));
        if s0.version>=5, tid = double(value(b,4,'int32'));
        else, tid = double(value(b,0,'uint16')); end
        assert(sid<numel(states) && tid==index,'fieldfox:link','Invalid trace/state link.');
        s = states(sid+1);
        assert(sid>=previousState && tid>=s.first_trace,'fieldfox:link','Inconsistent state order.');
        if sid+1<numel(states)
            assert(tid<states(sid+2).first_trace,'fieldfox:link','Trace uses an outdated state.');
        end
        previousState = sid;
        if s.span_hz==0
            axisValues = linspace(s.trigger_delay_s,s.trigger_delay_s+s.sweep_time_s,s.points);
            kind = 'time_axis_s';
            assert(isinf(o.FreqMinHz) && isinf(o.FreqMaxHz),'fieldfox:axis','Frequency crop is unavailable for zero span.');
        else
            axisValues = linspace(s.center_hz-s.span_hz/2,s.center_hz+s.span_hz/2,s.points);
            kind = 'frequency_hz';
        end
        if isempty(power)
            referenceAxis = axisValues; axisKind = kind;
            mask = true(size(axisValues));
            if strcmp(kind,'frequency_hz'), mask = axisValues>=o.FreqMinHz & axisValues<=o.FreqMaxHz; end
            assert(any(mask),'fieldfox:axis','Frequency selection is empty.');
            assert(rows*nnz(mask)<=20000000,'fieldfox:memory','Select fewer sweeps or frequency bins (20 million cell limit).');
            power = zeros(rows,nnz(mask),'single');
        else
            assert(strcmp(axisKind,kind) && isequal(referenceAxis,axisValues), ...
                'fieldfox:axis','Axis changes in the selected section; select a shorter range.');
        end
        ticks(row) = value(b,8,'int64'); check_ticks(ticks(row));
        parameter = value(b,headerBytes-8,'double');
        assert(isfinite(parameter) && parameter>=-2,'fieldfox:header','Invalid trace header parameter.');
        values = value(b,headerBytes,'single',s.points*s.blocks+s.auxiliary);
        slot = values(o.TraceSlot*s.points+(1:s.points));
        power(row,:) = reshape(slot(mask),1,[]);
        auxiliary(row,:) = reshape(values(s.points*s.blocks+1:end),1,[]);
        masks(row) = b(headerBytes-12); stateIds(row) = uint16(sid);
    end
    clear cleanup
    base = base+counts(k);
end
times = fieldfox_times(ticks,o.SourceTimeZone,o.DSTFold);
data = times;
data.power_dbm = power; data.timestamp_ticks = ticks;
data.elapsed_s = double(ticks-ticks(1))/1e7;
data.sweep_indices = int64(indices); data.trace_slot = o.TraceSlot; data.effective_step = step;
data.frequency_hz = []; data.time_axis_s = [];
data.(axisKind) = referenceAxis(mask)';
data.auxiliary_values = auxiliary; data.trace_masks = masks; data.state_ids = stateIds;
data.source_session = sessionFolder; data.states = states;
names = {'GPSA','RTSA'};
data.metadata_json = jsonencode(struct('application_name',names{s0.application}, ...
    'version',s0.version,'n_sweeps',total,'trace_count',s0.blocks, ...
    'index_validation','RPX CRCs not checked by MATLAB; use Python inspect'));
end

function files = store_files(folder,kind)
listing = dir(folder); flat = struct('path',{},'number',{},'bytes',{}); nested = flat;
for entry = listing'
    if ~entry.isdir && ~isempty(regexpi(entry.name,['^' kind '\d{5}$'],'once'))
        flat(end+1) = struct('path',fullfile(folder,entry.name),'number',str2double(entry.name(4:end)),'bytes',entry.bytes); %#ok<AGROW>
    elseif entry.isdir && ~isempty(regexpi(entry.name,['^d' kind '\d{5}$'],'once'))
        children = dir(fullfile(folder,entry.name));
        for child = children'
            if ~child.isdir && ~isempty(regexpi(child.name,['^\d{8}\.' kind '$'],'once'))
                nested(end+1) = struct('path',fullfile(folder,entry.name,child.name), ...
                    'number',str2double(child.name(1:8)),'bytes',child.bytes); %#ok<AGROW>
            end
        end
    end
end
assert(isempty(flat) || isempty(nested),'fieldfox:layout','Mixed flat/nested stores are ambiguous.');
files = [flat nested]; [~,order] = sort([files.number]); files = files(order);
assert(isequal([files.number],0:numel(files)-1),'fieldfox:layout','Missing or duplicate partition numbers.');
end

function s = state_header(b)
s.version = double(value(b,0,'int8')); s.application = double(value(b,1,'int8'));
assert(s.version>=1 && s.version<=18,'fieldfox:version','Unsupported state version (expected 1..18).');
if s.version<8, s.application = 1; end
assert(ismember(s.application,[1 2]),'fieldfox:mode','Unsupported application.');
s.state_id = double(value(b,2,'uint16'));
if s.version>=5, s.first_trace = double(value(b,4,'int32'));
else, s.first_trace = double(value(b,4,'uint16')); end
if s.version>=16
    s.points = double(value(b,8,'int16')); s.blocks = double(b(11)); s.auxiliary = double(b(12));
elseif s.version>=11
    s.points = double(value(b,8,'int16')); s.blocks = double(value(b,10,'int16')); s.auxiliary = 0;
else
    s.points = double(value(b,8,'int32')); s.blocks = 1; s.auxiliary = 0;
end
assert(s.points>=2 && s.blocks>=1 && s.first_trace>=0 && ...
    s.points*s.blocks+s.auxiliary<=10000000,'fieldfox:dimensions','Invalid state dimensions.');
s.timestamp_ticks = value(b,16,'int64'); check_ticks(s.timestamp_ticks);
s.center_hz = value(b,24,'double'); s.span_hz = value(b,32,'double');
settings = value(b,40,'single',10);
if s.version<13, settings(1:2)=0; end
if s.version<2, settings(9)=0; end
if s.version<6, settings(10)=0; end
assert(all(isfinite([s.center_hz s.span_hz double(settings(:)')])), ...
    'fieldfox:header','Nonfinite state settings.');
s.sweep_time_s = double(settings(5)); s.trigger_delay_s = double(settings(6));
assert(s.application~=2 || (s.blocks==1 && s.span_hz~=0), ...
    'fieldfox:rtsa','Multiple-block and zero-span RTSA are unsupported.');
s.raw_header = b';
end

function v = value(b,offset,kind,count)
if nargin<4, count=1; end
sample = cast(0,kind); width = numel(typecast(sample,'uint8'));
v = typecast(b(offset+(1:width*count)),kind);
[~,~,endian] = computer;
if endian=='B', v=swapbytes(v); end
end

function check_ticks(t)
maximum = int64(315537897599)*int64(10000000)+int64(9999999);
assert(t>0 && t<=maximum,'fieldfox:timestamp','Invalid .NET timestamp.');
end
