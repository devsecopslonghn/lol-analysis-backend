from __future__ import annotations

import math
import struct
from collections import Counter
from typing import Any, Iterator


CHUNK_HEADER = struct.Struct("<IBIII")
SIGNATURE_SIZE = 256


class TransportParseError(ValueError):
    """Raised when the ROFL chunk or network-block layer is invalid."""


def summarize_transport(raw: bytes, *, chunks_start: int, chunks_end: int) -> dict[str, Any]:
    """Parse verified ROFL transport framing without claiming packet semantics."""
    if chunks_start < 0 or chunks_end < chunks_start or chunks_end > len(raw):
        raise TransportParseError("invalid chunk region")

    stream_chunks: Counter[int] = Counter()
    opcode_counts: Counter[int] = Counter()
    payload_bytes: Counter[int] = Counter()
    first_opcode_timestamp: dict[int, float] = {}
    last_opcode_timestamp: dict[int, float] = {}
    opcode_streams: dict[int, Counter[int]] = {}
    block_count = 0
    first_timestamp: float | None = None
    last_timestamp: float | None = None
    cursor = chunks_start
    chunk_count = 0
    while cursor < chunks_end:
        if cursor + CHUNK_HEADER.size > chunks_end:
            raise TransportParseError("chunk header is truncated")
        chunk_id, _slot, stream_raw, raw_size, compressed_size = CHUNK_HEADER.unpack_from(raw, cursor)
        stream_id = (stream_raw >> 24) & 0xFF
        body_start = cursor + CHUNK_HEADER.size
        stored_size = compressed_size or raw_size
        body_end = body_start + stored_size
        if body_end > chunks_end:
            raise TransportParseError(f"chunk {chunk_id} body exceeds chunk region")
        body = raw[body_start:body_end]
        if compressed_size:
            body = _decompress(body, raw_size)
        if len(body) != raw_size:
            raise TransportParseError(f"chunk {chunk_id} size mismatch")

        stream_chunks[stream_id] += 1
        for timestamp, packet_id, payload_length in _iter_blocks(body):
            block_count += 1
            opcode_counts[packet_id] += 1
            payload_bytes[packet_id] += payload_length
            first_opcode_timestamp.setdefault(packet_id, timestamp)
            last_opcode_timestamp[packet_id] = timestamp
            opcode_streams.setdefault(packet_id, Counter())[stream_id] += 1
            first_timestamp = timestamp if first_timestamp is None else min(first_timestamp, timestamp)
            last_timestamp = timestamp if last_timestamp is None else max(last_timestamp, timestamp)
        chunk_count += 1
        cursor = body_end

    top_opcodes = [
        {
            "id": packet_id,
            "hex": f"0x{packet_id:04x}",
            "count": count,
            "payload_bytes": payload_bytes[packet_id],
            "average_payload_bytes": round(payload_bytes[packet_id] / count, 3),
        }
        for packet_id, count in opcode_counts.most_common(50)
    ]
    return {
        "status": "verified",
        "chunk_count": chunk_count,
        "stream_chunks": {_stream_name(stream): count for stream, count in sorted(stream_chunks.items())},
        "block_count": block_count,
        "first_timestamp_seconds": first_timestamp,
        "last_timestamp_seconds": last_timestamp,
        "distinct_opcodes": len(opcode_counts),
        "top_opcodes": top_opcodes,
        "opcode_observations": _opcode_observations(
            opcode_counts, payload_bytes, first_opcode_timestamp, last_opcode_timestamp, opcode_streams
        ),
        "semantic_status": "transport_only",
        "semantic_reason": "packet payload semantics require an exact patch profile and client decoder",
    }


def _decompress(body: bytes, expected_size: int) -> bytes:
    try:
        import zstandard

        return zstandard.ZstdDecompressor().decompress(body, max_output_size=expected_size)
    except ImportError as exc:
        raise TransportParseError("zstandard dependency is required for compressed ROFL chunks") from exc
    except Exception as exc:
        raise TransportParseError(f"zstandard chunk decompression failed: {exc}") from exc


def _iter_blocks(body: bytes) -> Iterator[tuple[float, int, int]]:
    cursor = 0
    timestamp = 0.0
    packet_id = 0
    param = 0
    while cursor < len(body):
        marker_offset = cursor
        marker = body[cursor]
        cursor += 1
        if marker & 0x80:
            _need(body, cursor, 1, marker_offset)
            timestamp += body[cursor] * 0.001
            cursor += 1
        else:
            _need(body, cursor, 4, marker_offset)
            timestamp = struct.unpack_from("<f", body, cursor)[0]
            cursor += 4
        if not math.isfinite(timestamp) or timestamp < 0:
            raise TransportParseError("block timestamp is negative or non-finite")

        if marker & 0x10:
            _need(body, cursor, 1, marker_offset)
            payload_length = body[cursor]
            cursor += 1
        else:
            _need(body, cursor, 4, marker_offset)
            payload_length = struct.unpack_from("<I", body, cursor)[0]
            cursor += 4
        if not marker & 0x40:
            _need(body, cursor, 2, marker_offset)
            packet_id = struct.unpack_from("<H", body, cursor)[0]
            cursor += 2
        if marker & 0x20:
            _need(body, cursor, 1, marker_offset)
            param = (param + body[cursor]) & 0xFFFFFFFF
            cursor += 1
        else:
            _need(body, cursor, 4, marker_offset)
            param = struct.unpack_from("<I", body, cursor)[0]
            cursor += 4
        _need(body, cursor, payload_length, marker_offset)
        cursor += payload_length
        yield timestamp, packet_id, payload_length


def _need(body: bytes, cursor: int, size: int, marker_offset: int) -> None:
    if cursor + size > len(body):
        raise TransportParseError(f"network block at offset {marker_offset} is truncated")


def _stream_name(stream_id: int) -> str:
    return {
        1: "gameChunk",
        2: "keyframe",
        3: "startKeyframe",
        4: "startSentinel",
    }.get(stream_id, f"stream-{stream_id}")


def _opcode_observations(
    counts: Counter[int],
    payload_bytes: Counter[int],
    first_timestamps: dict[int, float],
    last_timestamps: dict[int, float],
    streams: dict[int, Counter[int]],
) -> list[dict[str, Any]]:
    # These IDs are transport observations only. Their business meaning is
    # profile-bound and must not be promoted to a verified event on 16.17.
    observed_ids = (0x022C, 0x0226, 0x00C5, 0x015C, 0x036F, 0x0278, 0x0048)
    return [
        {
            "opcode": opcode,
            "hex": f"0x{opcode:04x}",
            "count": counts[opcode],
            "payload_bytes": payload_bytes[opcode],
            "status": "candidate",
            "meaning": "profile-bound opcode observed in transport",
            "first_timestamp_seconds": first_timestamps[opcode],
            "last_timestamp_seconds": last_timestamps[opcode],
            "stream_counts": {_stream_name(stream): count for stream, count in sorted(streams[opcode].items())},
        }
        for opcode in observed_ids
        if counts[opcode]
    ]
