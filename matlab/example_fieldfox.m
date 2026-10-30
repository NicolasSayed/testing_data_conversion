% Edit the folder and sweep range, then run this script.
sessionFolder = 'D:\data\RTAUTOsession01';
startSweep = 0;               % zero-based, included
stopSweep = 500;              % zero-based, excluded; use Inf for session end
sourceTimeZone = 'EST';       % fixed UTC-05:00; change if the clock used DST
outputMat = 'section.mat';    % outside the input session; must not exist

data = view_spectrogram(sessionFolder, ...
    'StartSweep',startSweep,'StopSweep',stopSweep, ...
    'SourceTimeZone',sourceTimeZone,'OutputMat',outputMat);

% data.power_dbm: rows=sweeps, columns=frequency bins
% data.frequency_hz, data.elapsed_s, data.timestamp_ticks (exact int64)
% data.timestamp_utc, data.timestamp_est, data.timestamp_eastern (ISO strings)
