# testing_data_conversion

Independent Python decoder for FieldFox SA/GPSA Record/Playback sessions,
targeting recordings from a **Keysight N9917B**. It reads session directories
directly and exports CSV or NumPy NPZ without installing or running Data Link.

**Status: initial decoder reconstructed by static analysis.** Before publication,
72 local synthetic tests passed and one real-recording integration test was
skipped. No N9917B recording or matching reference CSV was available, so actual
instrument compatibility and export equivalence are still unvalidated.

## Install

Requires Python 3.11 or newer.

```bash
git clone https://github.com/NicolasSayed/testing_data_conversion.git
cd testing_data_conversion
python -m pip install .
```

On Windows, `py -3.11` can be used instead of `python`. NumPy is the only runtime
dependency. Decoding works offline after installation.

## Command line

Use the complete session directory, including every state, trace and index file
that belongs to it. The directory name is arbitrary.

```bash
python -m fieldfox_recording inspect /path/to/session
python -m fieldfox_recording export /path/to/session --format csv --output output/session.csv
python -m fieldfox_recording export /path/to/session --format npz --output output/session.npz
```

`inspect` prints JSON with metadata, file prefixes, raw headers and structural
checks. Exit code 0 means the session passed the implemented checks; code 2
means incomplete, unsupported or malformed input. Partial inspection is also
available for individual state and index files.

Exports refuse existing files and destinations inside the input session.
Original recordings are never opened for writing.

## Python API

```python
from fieldfox_recording import FieldFoxRecording

rec = FieldFoxRecording.open('/path/to/session')
print(rec.metadata)
print(rec.frequency_hz)       # Common frequency axis, in Hz
print(rec.timestamps)         # ISO strings; instrument timezone is unknown
print(rec.power_dbm.shape)    # (sweeps, points), for a single trace
rec.to_csv('output/session.csv')
rec.to_npz('output/session.npz')

# Stream large sessions or handle changing settings one sweep at a time:
for sweep in rec:
    state = sweep.state
    axis = state.time_axis_s if state.span_hz == 0 else state.frequency_hz
    values = sweep.power_dbm_traces   # (trace_slots, points)
    extra = sweep.auxiliary_values   # Retained separately, meaning unassigned
```

The common-axis property raises if the axis changes during the session.
Zero-span sweeps expose a time axis in seconds. Convenience array properties
load their results into memory; iteration and CSV export use bounded record
reads. NPZ export uses temporary disk-backed power and auxiliary arrays;
timestamp and header metadata still use memory.

## Format summary

- Reconstructed GPSA versions 1–18; little-endian 104-byte state records.
- Trace records contain a 32-byte header before version 4, or a 44-byte header
  from version 4 onward, followed by float32 values. Dimensions come from the
  state header, including any auxiliary values.
- Supports nested stores such as `dSTA00000/00000000.STA` and
  `dTRC00000/00000000.TRC`, plus legacy flat `STA00000`/`TRC00000` stores.
- Recovers frequency axes, state changes, trace masks and exact .NET timestamps.
  Timestamps have 100 ns resolution and are local/unspecified, not established UTC.
- Uses the stored GPSA values as dBm without an additional scaling factor.
- Checks record sizes, IDs, state transitions and optional RPX index CRC-32
  checksums and record counts. Unknown fields are retained as raw data.

CSV is a long-form table with one row per point and trace slot, explicit units,
timestamps and state IDs. It differs from Data Link's presentation layout and
does not include auxiliary values or all raw header fields.

NPZ contains `power_dbm_traces`, `auxiliary_values`, `timestamp_ticks`,
`state_ids`, `trace_masks`, `axes_by_state`, `axis_kind_by_state`,
`trace_headers_json` and `metadata_json`. Load it with
`numpy.load(path, allow_pickle=False)`. Each sweep uses the axis selected by its
state ID. NPZ export needs temporary disk space near the uncompressed data size.

## Limits and validation

RTSA, raw IQ/VITA-49 captures, DLS archives, unknown versions, incomplete
partition sequences and changing record dimensions are unsupported. GPS
coordinate scaling, auxiliary-value meanings and the mapping of trace slots to
physical trace numbers remain unassigned. There is no recovered checksum for
the trace samples, so sample corruption cannot always be detected.

The N9917B appears in the supplied software's recognized model lists, but the
decoder chooses layouts using recording headers. The model name does not prove
which recording version or capture mode a particular session uses.

Local tests covered version branches, endianness, timestamps, boundaries,
state changes, multiple trace slots, zero span, malformed inputs, index checks
and CSV/NPZ exports. Tests and synthetic fixtures are not included in this
minimal publication. A complete finished N9917B GPSA session is needed for
instrument validation; a matching CSV export would enable numerical comparison.

This repository contains only the independent decoding scripts, package metadata
and this README. No Data Link binaries, decompiled code, recordings, sample
outputs or analysis artifacts are included.
