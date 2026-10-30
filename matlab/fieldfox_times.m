function data = fieldfox_times(ticks, sourceTimeZone, dstFold)
%FIELDFOX_TIMES Interpret an unspecified instrument clock without losing ticks.
% EST is fixed UTC-05:00; America/New_York observes daylight saving.
% An empty sourceTimeZone preserves instrument times and leaves conversions empty.
if nargin<2, sourceTimeZone='EST'; end
if nargin<3, dstFold=[]; end
assert(isempty(dstFold) || isequal(dstFold,0) || isequal(dstFold,1), ...
    'fieldfox:timezone','DSTFold must be empty, 0 or 1.');
ticks = int64(ticks(:)); unit = int64(10000000);
whole = idivide(ticks,unit,'floor'); fractions = rem(ticks,unit);
wall = datetime(1,1,1)+seconds(double(whole));
wall.Format = 'yyyy-MM-dd''T''HH:mm:ss';
original = cellstr(wall);
data.timestamp_instrument = append_fraction(original,fractions,'');
data.source_timezone = char(sourceTimeZone);
data.timestamp_conversion = 'not converted: instrument time zone is unspecified';
data.timestamp_utc = repmat({''},numel(ticks),1);
data.timestamp_est = data.timestamp_utc; data.timestamp_eastern = data.timestamp_utc;
data.timestamp_ticks_utc = zeros(0,1,'int64');
if isempty(sourceTimeZone), return; end
zone = char(sourceTimeZone);
if strcmpi(zone,'EST'), zone='Etc/GMT+5'; end
if ~isempty(regexp(zone,'^[+-]\d{2}:\d{2}$','once')), zone=['UTC' zone]; end
local = wall; local.TimeZone = zone;
assert(isequal(cellstr(local),original),'fieldfox:timezone','Instrument time falls in a daylight-saving gap.');
utc = local; utc.TimeZone = 'UTC';
% Detect repeated wall-clock hours and require the same explicit fold as Python.
for delta = [-1 1]
    candidate = utc+hours(delta); candidate.TimeZone = zone;
    ambiguous = strcmp(cellstr(candidate),original);
    if any(ambiguous)
        assert(~isempty(dstFold),'fieldfox:timezone','Ambiguous instrument time; use DSTFold 0 (earlier) or 1 (later).');
        candidate.TimeZone = 'UTC';
        if dstFold==0, utc(ambiguous)=min(utc(ambiguous),candidate(ambiguous));
        else, utc(ambiguous)=max(utc(ambiguous),candidate(ambiguous)); end
    end
end
local = utc; local.TimeZone = zone;
offsetSeconds = seconds(tzoffset(local));
data.timestamp_ticks_utc = ticks-int64(offsetSeconds)*unit;
est = utc; est.TimeZone = 'Etc/GMT+5';
eastern = utc; eastern.TimeZone = 'America/New_York';
data.timestamp_utc = append_fraction(cellstr(utc),fractions,'Z');
data.timestamp_est = append_fraction(cellstr(est),fractions,'-05:00');
easternSuffix = repmat({'-05:00'},numel(ticks),1);
easternSuffix(seconds(tzoffset(eastern))==-4*3600) = {'-04:00'};
data.timestamp_eastern = append_fraction(cellstr(eastern),fractions,easternSuffix);
data.timestamp_conversion = ['converted assuming instrument clock zone ' char(sourceTimeZone)];
end

function result = append_fraction(base,fraction,suffix)
if ischar(suffix), suffix=repmat({suffix},numel(base),1); end
result = cell(numel(base),1);
for k = 1:numel(base)
    result{k} = [base{k} '.' sprintf('%07d',fraction(k)) suffix{k}];
end
end
