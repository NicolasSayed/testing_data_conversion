"""GPSA binary layouts recovered from Utility.dll als/alt, Core.dll apf/aqb.

This is static parser reconstruction, not validation against instrument data.
See README.md for usage and validation status.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
import re
import struct

import numpy as np
from numpy.typing import NDArray

STATE_RECORD_SIZE = 104  # als.qp(), independent of version
SUPPORTED_VERSIONS = range(1, 19)  # adg.oq writes 18; older branches in als/alt.qm
MAX_DOTNET_TICKS = 3155378975999999999
MAX_VALUES_PER_RECORD = 10_000_000  # allocation guard, not an instrument limit


class RecordingError(ValueError):
    """Malformed or inconsistent recording."""


class UnsupportedFormatError(RecordingError):
    """Input has no supported GPSA layout or needs unsupported interpretation."""


def ticks_to_iso(ticks: int) -> str:
    """Exact .NET 100 ns ticks as ISO local/unspecified time, without a timezone."""
    if not 0 < ticks <= MAX_DOTNET_TICKS:
        raise RecordingError(f"Invalid .NET timestamp ticks: {ticks}")
    seconds, fraction = divmod(ticks, 10_000_000)
    value = datetime(1, 1, 1) + timedelta(seconds=seconds)
    return f"{value.year:04d}-{value.month:02d}-{value.day:02d}T{value.hour:02d}:{value.minute:02d}:{value.second:02d}.{fraction:07d}"


@dataclass(frozen=True)
class State:
    version: int
    application: int
    state_id: int
    first_trace_id: int
    points: int
    trace_count: int
    auxiliary_count: int
    ticks: int
    center_hz: float
    span_hz: float
    settings: dict[str, Any]
    raw_header: bytes

    @property
    def value_count(self) -> int:
        return self.points * self.trace_count + self.auxiliary_count

    @property
    def frequency_hz(self) -> NDArray[np.float64]:
        if self.span_hz == 0:
            raise UnsupportedFormatError("Zero-span trace has a time axis; use time_axis_s.")
        return np.linspace(self.center_hz - self.span_hz / 2,
                           self.center_hz + self.span_hz / 2, self.points)

    @property
    def time_axis_s(self) -> NDArray[np.float64]:
        if self.span_hz != 0:
            raise UnsupportedFormatError("Frequency scan has a frequency axis; use frequency_hz.")
        return np.linspace(self.settings["trigger_delay_s_raw"],
                           self.settings["trigger_delay_s_raw"] + self.settings["sweep_time_s"], self.points)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in vars(self).items() if k != "raw_header"} | {
            "timestamp": ticks_to_iso(self.ticks), "raw_header_hex": self.raw_header.hex()}


def parse_state(data: bytes) -> State:
    """Parse one 104 byte als record, retaining uninterpreted fields."""
    if len(data) != STATE_RECORD_SIZE:
        raise RecordingError(f"State record requires 104 bytes, got {len(data)}")
    version, application_raw, state_id = struct.unpack_from("<bbH", data)
    if version not in SUPPORTED_VERSIONS:
        raise UnsupportedFormatError(f"Unsupported state version {version}; reconstructed range is 1..18")
    application = application_raw if version >= 8 else 1
    first_trace = struct.unpack_from("<H" if version < 5 else "<i", data, 4)[0]
    if version >= 16:
        points, trace_count, auxiliary_count = struct.unpack_from("<hBB", data, 8)
    elif version >= 11:
        points, trace_count = struct.unpack_from("<hh", data, 8)
        auxiliary_count = 0
    else:
        points = struct.unpack_from("<i", data, 8)[0]
        trace_count, auxiliary_count = 1, 0
    if points < 2 or trace_count < 1 or first_trace < 0:
        raise RecordingError(f"Invalid state dimensions/index: points={points}, traces={trace_count}, first_trace={first_trace}")
    count = points * trace_count + auxiliary_count
    if count > MAX_VALUES_PER_RECORD:
        raise RecordingError(f"Trace value count {count} exceeds allocation guard")
    ticks, center, span = struct.unpack_from("<qdd", data, 16)
    ticks_to_iso(ticks)
    if not np.isfinite([center, span]).all():
        raise RecordingError("Non-finite center frequency or span")
    floats = list(struct.unpack_from("<10f", data, 40))
    if version < 13:
        floats[0:2] = [0., 0.]
    if version < 2:
        floats[8] = 0.
    if version < 6:
        floats[9] = 0.
    if not np.isfinite(floats).all():
        raise RecordingError("Non-finite state settings; unsupported sentinel or corrupt header")
    names = ["reference_level_raw", "scale_per_div_raw", "rbw_signed_hz", "vbw_signed_hz",
             "sweep_time_s", "trigger_delay_s_raw", "trigger_level_raw", "trigger_holdoff_s_raw",
             "external_gain_raw", "trigger_extra_raw"]
    settings = dict(zip(names, floats))
    settings.update(application_byte_raw=application_raw,
                    reserved_prefix_hex=data[12:16].hex(),
                    reserved_80_hex=data[80:84].hex(),
                    legacy_84_hex=data[84:88].hex(),
                    average_count_signed=struct.unpack_from("<h", data, 88)[0],
                    reserved_90_hex=data[90:92].hex(),
                    preamp_raw=struct.unpack_from("<b", data, 92)[0],
                    trigger_boolean_raw=bool(data[93]),
                    measurement_path_flags_raw=data[94] if version >= 17 else 0,
                    attenuation_encoded=struct.unpack_from("<b", data, 95)[0],
                    settings_bytes_96_103=list(struct.unpack_from("<8b", data, 96)),
                    rbw_hz=abs(floats[2]), vbw_hz=abs(floats[3]))
    if version < 5:
        settings["reserved_6_hex"] = data[6:8].hex()
    if version < 10:
        settings["preamp_legacy_boolean"] = bool(data[92])
    if version >= 11:
        settings["extra_settings_signed"] = list(struct.unpack_from("<hh", data, 84))
    return State(version, application, state_id, first_trace, points, trace_count,
                 auxiliary_count, ticks, center, span, settings, bytes(data))


def trace_record_size(state: State) -> int:
    """alt.qp(): 32 byte base header, plus 12 GPS bytes from version 4."""
    return (44 if state.version >= 4 else 32) + 4 * state.value_count


@dataclass(frozen=True)
class Sweep:
    trace_id: int
    state: State
    ticks: int
    trace_mask: int
    power_dbm_traces: NDArray[np.float32]
    auxiliary_values: NDArray[np.float32]
    header: dict[str, Any]
    source: str = ""
    offset: int = 0

    @property
    def timestamp(self) -> str:
        return ticks_to_iso(self.ticks)

    @property
    def power_dbm(self) -> NDArray[np.float32]:
        if self.state.trace_count != 1:
            raise UnsupportedFormatError("Multiple traces: use power_dbm_traces (trace, point).")
        return self.power_dbm_traces[0]


def parse_trace(data: bytes, state: State) -> Sweep:
    """Decode one alt record; no amplitude scale or offset is applied."""
    if state.application != 1:
        raise UnsupportedFormatError(f"Application {state.application} is not supported GPSA trace data (RTSA=2).")
    expected = trace_record_size(state)
    if len(data) != expected:
        raise RecordingError(f"Trace record requires {expected} bytes, got {len(data)}")
    if state.version >= 5:
        reserved, state_id, trace_id = struct.unpack_from("<HHi", data)
    else:
        trace_id, state_id, reserved = struct.unpack_from("<HHi", data)
    if trace_id < 0 or state_id != state.state_id:
        raise RecordingError(f"Invalid trace/state link: trace={trace_id}, state={state_id}, expected state={state.state_id}")
    ticks = struct.unpack_from("<q", data, 8)[0]
    ticks_to_iso(ticks)
    pos = 16
    header: dict[str, Any] = {"reserved_prefix": reserved}
    if state.version >= 4:
        j, k, elevation = struct.unpack_from("<iih", data, pos)
        # GPS degree scaling has deliberately not been guessed.
        header.update(gps_j_raw=j, gps_k_raw=k, elevation_m=elevation)
        if state.version >= 7:
            age = struct.unpack_from("<h", data, pos + 10)[0]
            header.update(gps_age_10ms_raw=age, gps_validity=0 if age < 0 else (1 if age * 10 <= 5000 else 2))
        else:
            header.update(gps_validity=data[pos + 10], gps_reserved_byte=data[pos + 11])
        pos += 12
    if state.version >= 12:
        header.update(legacy_condition_bytes=list(data[pos:pos+2]), measurement_conditions=data[pos+2])
    else:
        header.update(adc_overrange=bool(data[pos]), uncalibrated=bool(data[pos+1]),
                      questionable_drift=bool(data[pos+2]) if state.version >= 6 else False)
    trace_mask = data[pos+3]
    reserved_int, parameter = struct.unpack_from("<id", data, pos+4)
    if not np.isfinite(parameter) or parameter < -2:
        raise RecordingError(f"Invalid trace header parameter {parameter}")
    pos += 16
    values = np.frombuffer(data, dtype="<f4", count=state.value_count, offset=pos)
    split = state.points * state.trace_count
    header.update(reserved_int=reserved_int, parameter_raw=parameter,
                  raw_header_hex=data[:pos].hex())
    return Sweep(trace_id, state, ticks, trace_mask,
                 values[:split].reshape(state.trace_count, state.points), values[split:], header)


def _files(root: Path, kind: str) -> list[Path]:
    """apf.a8 layouts: root/STA00000 or dSTA00000/00000000.STA."""
    flat = [p for p in root.iterdir() if p.is_file() and re.fullmatch(kind + r"\d{5}", p.name, re.I)]
    dirs = [p for p in root.iterdir() if p.is_dir() and re.fullmatch("d" + kind + r"\d{5}", p.name, re.I)]
    nested = [p for d in dirs for p in d.iterdir() if p.is_file() and re.fullmatch(r"\d{8}\." + kind, p.name, re.I)]
    if flat and nested:
        raise RecordingError(f"Mixed flat and directory {kind} stores are ambiguous")
    paths = sorted(flat or nested, key=lambda p: int(p.name[3:] if flat else p.stem))
    numbers = [int(p.name[3:] if flat else p.stem) for p in paths]
    if numbers != list(range(len(paths))):
        raise RecordingError(f"Missing, duplicate or nonzero initial {kind} partition number: {numbers[:20]}")
    return paths


def _records(path: Path, size: int) -> Iterator[tuple[int, bytes]]:
    length = path.stat().st_size
    if length == 0 or length % size:
        raise RecordingError(f"{path}: {length} bytes is not a positive multiple of record stride {size}; truncated or unsupported layout")
    with path.open("rb") as stream:
        for offset in range(0, length, size):
            data = stream.read(size)
            if len(data) != size:
                raise RecordingError(f"{path}: short read at byte {offset}")
            yield offset, data


class FieldFoxRecording:
    """Lazy reader of complete GPSA sessions. Iteration uses bounded record reads."""

    def __init__(self, path: Path, states: list[State], trace_files: list[Path], indexes: list[dict[str, Any]]):
        self.path = path
        self.states = states
        self.trace_files = trace_files
        self.indexes = indexes

    @classmethod
    def open(cls, path: str | Path) -> FieldFoxRecording:
        root = Path(path)
        if not root.is_dir():
            raise UnsupportedFormatError("Expected a complete session directory with STA and TRC stores; individual IQ/VITA-49/DLS files are unsupported.")
        state_files, trace_files = _files(root, "STA"), _files(root, "TRC")
        if not state_files:
            raise UnsupportedFormatError("No recognized STA store. Supply the complete GPSA session directory; IQ/VITA-49 captures are unsupported.")
        states = [parse_state(data) for p in state_files for _, data in _records(p, STATE_RECORD_SIZE)]
        if [s.state_id for s in states] != list(range(len(states))):
            raise RecordingError("State identifiers must be consecutive from zero")
        if not trace_files:
            raise RecordingError("Session has state records but no trace store")
        first = states[0]
        for state in states:
            if state.application != 1:
                raise UnsupportedFormatError(f"Application {state.application} is unsupported; GPSA=1, RTSA=2. State bytes can be read by inspect.")
            if (state.version, state.points, state.trace_count, state.auxiliary_count) != (first.version, first.points, first.trace_count, first.auxiliary_count):
                raise UnsupportedFormatError("Changing record dimensions/version within a session requires an unverified storage layout")
        stride = trace_record_size(first)
        for p in trace_files:
            if p.stat().st_size == 0 or p.stat().st_size % stride:
                raise RecordingError(f"{p}: size {p.stat().st_size} is not a positive multiple of trace stride {stride}")
        from .index import read_index
        indexes = [read_index(p) for p in sorted(root.iterdir()) if p.is_file() and p.name.lower() in {"sta.rpx", "trc.rpx"}]
        physical_counts = {"STA": len(states), "TRC": sum(p.stat().st_size // stride for p in trace_files)}
        for index in indexes:
            for kind, store in index["stores"].items():
                if kind in physical_counts and store.get("num_records") != physical_counts[kind]:
                    raise RecordingError(f"RPX {kind} record count {store.get('num_records')} differs from physical count {physical_counts[kind]}")
        return cls(root, states, trace_files, indexes)

    def __iter__(self) -> Iterator[Sweep]:
        expected_id = 0
        stride = trace_record_size(self.states[0])
        previous_state = -1
        for path in self.trace_files:
            for offset, data in _records(path, stride):
                state_id = struct.unpack_from("<H", data, 2)[0]
                if state_id >= len(self.states):
                    raise RecordingError(f"{path}:{offset}: missing state {state_id}")
                state = self.states[state_id]
                sweep = parse_trace(data, state)
                if sweep.trace_id != expected_id:
                    raise RecordingError(f"{path}:{offset}: expected trace {expected_id}, got {sweep.trace_id}")
                if state_id < previous_state or sweep.trace_id < state.first_trace_id:
                    raise RecordingError(f"{path}:{offset}: inconsistent state/trace ordering")
                if state_id != previous_state and sweep.trace_id != state.first_trace_id:
                    raise RecordingError(f"{path}:{offset}: state transition does not match first_trace_id")
                previous_state = state_id
                expected_id += 1
                yield Sweep(**(vars(sweep) | {"source": str(path), "offset": offset}))

    def __len__(self) -> int:
        stride = trace_record_size(self.states[0])
        return sum(p.stat().st_size // stride for p in self.trace_files)

    @property
    def metadata(self) -> dict[str, Any]:
        return {"format": "FieldFox GPSA Record/Playback", "validation": "static reconstruction; instrument compatibility not yet validated",
                "version": self.states[0].version, "n_sweeps": len(self), "n_points": self.states[0].points,
                "trace_count": self.states[0].trace_count, "auxiliary_count": self.states[0].auxiliary_count,
                "trace_stride_bytes": trace_record_size(self.states[0]), "power_unit": "dBm",
                "timestamp_basis": ".NET ticks; local/unspecified instrument clock, timezone unavailable",
                "indexes": self.indexes,
                "states": [s.as_dict() for s in self.states]}

    def _common_axis(self, name: str) -> NDArray[np.float64]:
        axis = getattr(self.states[0], name)
        if any(not np.array_equal(axis, getattr(s, name)) for s in self.states[1:]):
            raise UnsupportedFormatError(f"Session changes {name}; iterate sweeps and use sweep.state.{name}")
        return axis

    @property
    def frequency_hz(self) -> NDArray[np.float64]:
        return self._common_axis("frequency_hz")

    @property
    def time_axis_s(self) -> NDArray[np.float64]:
        return self._common_axis("time_axis_s")

    @property
    def timestamps(self) -> NDArray[np.str_]:
        return np.array([s.timestamp for s in self], dtype="U27")

    @property
    def timestamp_ticks(self) -> NDArray[np.int64]:
        return np.array([s.ticks for s in self], dtype=np.int64)

    @property
    def power_dbm_traces(self) -> NDArray[np.float32]:
        result = np.empty((len(self), self.states[0].trace_count, self.states[0].points), dtype=np.float32)
        for i, sweep in enumerate(self):
            result[i] = sweep.power_dbm_traces
        return result

    @property
    def power_dbm(self) -> NDArray[np.float32]:
        if self.states[0].trace_count != 1:
            raise UnsupportedFormatError("Multiple traces: use power_dbm_traces (sweep, trace, point).")
        return self.power_dbm_traces[:, 0, :]

    def to_csv(self, path: str | Path) -> None:
        from .export import to_csv
        to_csv(self, path)

    def to_npz(self, path: str | Path) -> None:
        from .export import to_npz
        to_npz(self, path)


def inspect_path(path: str | Path) -> dict[str, Any]:
    """Inspect recognized states or unknown prefixes without guessing a decoder."""
    target = Path(path)
    if not target.exists():
        raise RecordingError(f"Path does not exist: {target}")
    if target.is_file():
        with target.open("rb") as f:
            prefix = f.read(STATE_RECORD_SIZE)
        result: dict[str, Any] = {"path": str(target), "size": target.stat().st_size, "prefix_hex": prefix.hex(), "supported": False}
        if prefix.startswith(b"FFRPINDX"):
            from .index import read_index
            try:
                result["index"] = read_index(target)
            except RecordingError as error:
                result["error"] = str(error)
        if re.fullmatch(r"(?:STA\d{5}|\d{8}\.STA)", target.name, re.I):
            try:
                result["state"] = parse_state(prefix).as_dict()
            except RecordingError as error:
                result["error"] = str(error)
        return result
    files = []
    states = []
    for p in sorted(target.rglob("*")):
        if p.is_file():
            with p.open("rb") as f:
                prefix = f.read(16)
            files.append({"path": p.relative_to(target).as_posix(), "size": p.stat().st_size, "prefix_hex": prefix.hex()})
    try:
        for p in _files(target, "STA"):
            for offset, data in _records(p, STATE_RECORD_SIZE):
                states.append({"source": str(p), "offset": offset, **parse_state(data).as_dict()})
        rec = FieldFoxRecording.open(target)
        # Inspect verifies every trace boundary/link without materializing an array.
        count = sum(1 for _ in rec)
        return {"supported": True, "verified_trace_records": count, "metadata": rec.metadata, "files": files}
    except RecordingError as error:
        return {"supported": False, "error": str(error), "states": states, "files": files}
