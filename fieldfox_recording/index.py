"""Optional RPX index: Utility.dll ank/anl/anm/ano/ann/anp.

CRC-32 uses reflected polynomial 0xEDB88320 (amc); it protects index
chunks, not the sweep data. No binary deserialization or code loading.
"""
from __future__ import annotations
from pathlib import Path
import struct
import zlib
from typing import Any
from .parser import RecordingError, UnsupportedFormatError

MAX_CHUNK_BYTES = 64 * 1024 * 1024


def _tlv(body: bytes) -> list[dict[str, Any]]:
    fields = []
    pos = 0
    while pos < len(body):
        if len(body) - pos < 5:
            raise RecordingError("Truncated RPX item header")
        length, tag = struct.unpack_from("<iB", body, pos)
        pos += 5
        if length < 0 or length > len(body) - pos:
            raise RecordingError("Invalid RPX item length")
        value = body[pos:pos+length]
        fields.append({"tag": tag, "raw_hex": value.hex()})
        pos += length
    return fields


def read_index(path: str | Path) -> dict[str, Any]:
    """Parse bounded chunks, validate CRC and retain unknown chunks/items."""
    target = Path(path)
    result: dict[str, Any] = {"path": str(target), "chunks": [], "stores": {}}
    with target.open("rb") as stream:
        header = stream.read(10)
        if len(header) != 10 or header[:8] != b"FFRPINDX":
            raise UnsupportedFormatError(f"{target}: unsupported RPX signature")
        version = struct.unpack_from("<H", header, 8)[0]
        if version != 1:
            raise UnsupportedFormatError(f"{target}: unsupported RPX version {version}")
        result["version"] = version
        while True:
            offset = stream.tell()
            chunk_header = stream.read(8)
            if not chunk_header:
                break
            if len(chunk_header) != 8:
                raise RecordingError(f"{target}: truncated RPX chunk header at {offset}")
            length, tag = struct.unpack("<i4s", chunk_header)
            if length < 0 or length > MAX_CHUNK_BYTES:
                raise RecordingError(f"{target}: invalid/oversized RPX chunk length {length}")
            body = stream.read(length)
            crc_bytes = stream.read(4)
            if len(body) != length or len(crc_bytes) != 4:
                raise RecordingError(f"{target}: truncated RPX chunk at {offset}")
            crc = struct.unpack("<I", crc_bytes)[0]
            if zlib.crc32(tag + body) != crc:
                raise RecordingError(f"{target}: RPX CRC mismatch at {offset}")
            chunk: dict[str, Any] = {"offset": offset, "tag": tag.decode("ascii", errors="replace"),
                                     "body_length": length, "crc32": f"{crc:08x}"}
            if tag in {b"FDAT", b"fDEV"}:
                fields = _tlv(body)
                chunk["fields"] = fields
                file_type = None
                for field in fields:
                    raw = bytes.fromhex(field["raw_hex"])
                    if field["tag"] == 10:
                        file_type = raw.decode("ascii", errors="replace")
                        field["file_type"] = file_type
                    elif tag == b"FDAT" and field["tag"] in {11, 12, 13}:
                        if len(raw) != 4:
                            raise RecordingError("RPX FDAT numeric item must be four bytes")
                        field["value"] = struct.unpack("<i", raw)[0]
                    elif tag == b"fDEV" and field["tag"] in {11, 12}:
                        if len(raw) % 8:
                            raise RecordingError("RPX fDEV items must be pairs of int32")
                        field["pairs"] = list(struct.iter_unpack("<ii", raw))
                if tag == b"FDAT" and file_type:
                    names = {11: "num_records", 12: "nominal_files_per_dir", 13: "nominal_records_per_file"}
                    result["stores"][file_type] = {names[f["tag"]]: f["value"] for f in fields if "value" in f}
            else:
                # sTRS names/settings and unknown chunks retained without interpretation.
                chunk["raw_body_hex"] = body.hex()
            result["chunks"].append(chunk)
    return result
