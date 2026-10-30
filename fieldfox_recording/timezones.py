"""Explicit interpretation of the instrument's timezone-free .NET clock."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from .parser import MAX_DOTNET_TICKS, RecordingError, ticks_to_iso

TICKS_PER_SECOND = 10_000_000
EST = timezone(timedelta(hours=-5), "EST")


def _zone(name: str) -> tzinfo:
    if name.upper() == "UTC":
        return timezone.utc
    if name.upper() == "EST":
        return EST
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", name)
    if match:
        hours, minutes = map(int, match.groups()[1:])
        if hours > 23 or minutes > 59:
            raise RecordingError(f"Invalid UTC offset: {name}")
        offset = timedelta(hours=hours, minutes=minutes)
        return timezone(offset if match[1] == "+" else -offset)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise RecordingError(f"Unknown source time zone {name!r}; use UTC, EST, +/-HH:MM or an IANA name. Install tzdata for IANA zones on Windows.") from error


def _localize(wall: datetime, zone: tzinfo, fold: int | None) -> datetime:
    candidates = [wall.replace(tzinfo=zone, fold=i) for i in (0, 1)]
    valid = [t.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == wall
             for t in candidates]
    if not any(valid):
        raise RecordingError(f"Instrument time {wall.isoformat()} does not exist in the source time zone (daylight-saving gap)")
    ambiguous = all(valid) and candidates[0].utcoffset() != candidates[1].utcoffset()
    if ambiguous and fold is None:
        raise RecordingError(f"Instrument time {wall.isoformat()} is ambiguous; set --dst-fold 0 for the earlier occurrence or 1 for the later occurrence")
    return candidates[fold if ambiguous else valid.index(True)]


def _iso(value: datetime, fraction: int) -> str:
    wall = value.replace(tzinfo=None).isoformat(timespec="seconds")
    suffix = value.isoformat(timespec="seconds")[len(wall):]
    return f"{wall}.{fraction:07d}" + ("Z" if suffix == "+00:00" else suffix)


def convert_timestamps(ticks: np.ndarray, source_timezone: str | None = None,
                       dst_fold: int | None = None) -> dict:
    """Preserve ticks and export exact ISO times under an explicit clock assumption.

    Without a source zone, converted strings are empty, never guessed. EST is
    fixed UTC-05:00; timestamp_eastern follows America/New_York daylight saving.
    """
    if dst_fold not in (None, 0, 1):
        raise RecordingError("dst_fold must be 0 or 1")
    raw = np.asarray(ticks, dtype=np.int64)
    instrument = np.array([ticks_to_iso(int(t)) for t in raw])
    result = {"timestamp_instrument": instrument,
              "source_timezone": source_timezone or "unspecified",
              "timestamp_conversion": "not converted: instrument time zone is unspecified",
              "timestamp_utc": np.full(len(raw), "", dtype="U1"),
              "timestamp_est": np.full(len(raw), "", dtype="U1"),
              "timestamp_eastern": np.full(len(raw), "", dtype="U1"),
              "timestamp_ticks_utc": np.empty(0, dtype=np.int64)}
    if source_timezone is None:
        if dst_fold is not None:
            raise RecordingError("--dst-fold requires --source-timezone")
        return result
    source, eastern = _zone(source_timezone), _zone("America/New_York")
    utc_times, est_times, eastern_times, utc_ticks = [], [], [], []
    try:
        for tick in raw:
            seconds, fraction = divmod(int(tick), TICKS_PER_SECOND)
            wall = datetime(1, 1, 1) + timedelta(seconds=seconds)
            aware = _localize(wall, source, dst_fold)
            utc = aware.astimezone(timezone.utc)
            offset = aware.utcoffset()
            offset_seconds = offset.days * 86400 + offset.seconds
            converted = int(tick) - offset_seconds * TICKS_PER_SECOND
            if not 0 < converted <= MAX_DOTNET_TICKS:
                raise RecordingError("Converted UTC timestamp is outside the .NET clock range")
            utc_ticks.append(converted)
            utc_times.append(_iso(utc, fraction))
            est_times.append(_iso(utc.astimezone(EST), fraction))
            eastern_times.append(_iso(utc.astimezone(eastern), fraction))
    except (OverflowError, ValueError) as error:
        if isinstance(error, RecordingError):
            raise
        raise RecordingError(f"Cannot convert instrument timestamps: {error}") from error
    result.update(timestamp_conversion=f"converted assuming instrument clock zone {source_timezone}",
                  timestamp_utc=np.array(utc_times), timestamp_est=np.array(est_times),
                  timestamp_eastern=np.array(eastern_times),
                  timestamp_ticks_utc=np.array(utc_ticks, dtype=np.int64))
    return result
