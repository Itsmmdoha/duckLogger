"""Authenticated, fragmented MeshOps messages for an SX1262 link."""

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib
try:
    import ustruct as struct
except ImportError:
    import struct

MAGIC = b"DL"
VERSION = 1
TYPE_DATA = 1
TYPE_ACK = 2
HEADER = ">2sBBIHBBH"
HEADER_SIZE = struct.calcsize(HEADER)
TAG_SIZE = 12
MAX_FRAME_BYTES = 220
MAX_PAYLOAD = MAX_FRAME_BYTES - HEADER_SIZE - TAG_SIZE
MAX_FRAGMENTS = 64


def _hmac_sha256(key, data):
    """Small RFC 2104 implementation supported by MicroPython uhashlib."""
    if len(key) > 64:
        key = hashlib.sha256(key).digest()
    key = key + b"\x00" * (64 - len(key))
    outer = bytes((value ^ 0x5c) for value in key)
    inner = bytes((value ^ 0x36) for value in key)
    return hashlib.sha256(outer + hashlib.sha256(inner + data).digest()).digest()


def encode_frame(frame_type, session, message_seq, fragment, total, payload, key):
    if frame_type not in (TYPE_DATA, TYPE_ACK):
        raise ValueError("invalid LoRa frame type")
    if not isinstance(payload, bytes):
        payload = bytes(payload)
    if not key or len(key) < 16:
        raise ValueError("LoRa frame key must be at least 16 bytes")
    if total < 1 or total > MAX_FRAGMENTS or fragment < 0 or fragment >= total or len(payload) > MAX_PAYLOAD:
        raise ValueError("invalid LoRa fragment")
    header = struct.pack(HEADER, MAGIC, VERSION, frame_type, session,
                         message_seq, fragment, total, len(payload))
    body = header + payload
    return body + _hmac_sha256(key, body)[:TAG_SIZE]


def decode_frame(raw, key):
    if not isinstance(raw, bytes) or len(raw) < HEADER_SIZE + TAG_SIZE:
        raise ValueError("truncated LoRa frame")
    body, tag = raw[:-TAG_SIZE], raw[-TAG_SIZE:]
    if _hmac_sha256(key, body)[:TAG_SIZE] != tag:
        raise ValueError("invalid LoRa frame authentication")
    magic, version, frame_type, session, message_seq, fragment, total, length = \
        struct.unpack(HEADER, body[:HEADER_SIZE])
    payload = body[HEADER_SIZE:]
    if magic != MAGIC or version != VERSION or frame_type not in (TYPE_DATA, TYPE_ACK):
        raise ValueError("unsupported LoRa frame")
    if length != len(payload) or total < 1 or fragment >= total:
        raise ValueError("invalid LoRa frame length")
    return {
        "type": frame_type, "session": session, "message_seq": message_seq,
        "fragment": fragment, "total": total, "payload": payload,
    }


def fragment_message(payload, key, session, message_seq):
    if not isinstance(payload, bytes):
        payload = payload.encode("utf-8")
    total = max(1, (len(payload) + MAX_PAYLOAD - 1) // MAX_PAYLOAD)
    if total > MAX_FRAGMENTS:
        raise ValueError("LoRa message is too large")
    return [encode_frame(TYPE_DATA, session, message_seq, index, total,
                         payload[index * MAX_PAYLOAD:(index + 1) * MAX_PAYLOAD], key)
            for index in range(total)]


def encode_ack(key, session, message_seq, total, received):
    bitmap = bytearray((total + 7) // 8)
    for index in received:
        if 0 <= index < total:
            bitmap[index // 8] |= 1 << (index % 8)
    return encode_frame(TYPE_ACK, session, message_seq, 0, 1, bytes(bitmap), key)


def decode_ack(frame, total):
    if frame["type"] != TYPE_ACK:
        raise ValueError("not an ACK frame")
    payload = frame["payload"]
    return {index for index in range(total)
            if index // 8 < len(payload) and payload[index // 8] & (1 << (index % 8))}
