# Roadmap and known gaps

> Research prototype for authorized engagements and isolated lab testing. Use
> only on equipment and networks for which you have explicit authorization.

This document is the working backlog: what the code does today, what is missing,
and how each item is verified. It is not a promise of production readiness.

The approved multi-gateway, Send My, whole-network installer, and expanded
`lora_sink` design is specified in [`DESIGN.md`](DESIGN.md). Its software
phases are implemented; external firmware/retrieval and hardware validation
remain deployment work.

## Verified baseline

- Mesh radio is ESP-NOW only. The routing core uses `RadioTransport`; hardware
  imports and peer registration live in `lib/espnow_transport.py`.
- Wire protocol is `PROTOCOL_VERSION = 4` in `lib/mesh_protocol.py`, with
  boot-aware event identity, targeted gateways, types `r`/`d`/`a`, a 240-byte
  cap, and the four-event allowlist.
- Relay, deduplication, TTL, application ACKs, retries, route failover, bounded
  outbox, and optional outbox persistence are implemented in `mesh_network.py`.
- Gateway writes NDJSON to `mesh.log_path` and serves `/mesh/status` and
  `/mesh/log`. API auth accepts `Authorization: Bearer`, `?token=`, or
  `X-API-Key` (`lib/api.py:41-46`).
- Egress backends are independently queued `log`, `wifi`, native SX1262
  `lora`, and UART companion `sendmy`; `lora_sink` stores and serves batches.
- Whole-network validation/rendering and exact-MAC installer flows are implemented.
- Tests: 102 CPython pytest tests; CI runs `pytest -q` and `compileall`.
- The ESP-NOW mesh has no message authentication, replay protection, or
  per-device keys. The separate LoRa uplink uses a shared-key HMAC.
  `mesh.peer_macs` is a spoofable filtering allowlist, not an identity.

## P0 — Safety and correctness

### 1. Authenticated envelopes and replay protection

- Current: packets are plaintext JSON with no MAC/signature; `mesh.peer_key` is
  only the ESP-NOW PMK/LMK. Any allowed-MAC sender can inject or replay data.
- Gap: authenticated envelope, per-device keys, boot ID + monotonic counter
  nonce, replay window, key provisioning/rotation. Bump `PROTOCOL_VERSION` and
  reject unauthenticated packets when enabled.
- Touch: new `lib/mesh_crypto.py`, `lib/mesh_protocol.py`, `lib/settings.py`,
  `lib/mesh_network.py`, `tests/`, `README.md`, `MESHOPS.md`.
- Verify: tamper, truncated, wrong-key, and replayed packets are rejected;
  valid packets still round-trip. Do not field-test LoRa without this.

### 2. Transport abstraction — complete

- Implemented: `RadioTransport` defines `start`, `stop`, `send`, `recv`, and
  `status`; `EspNowTransport` isolates ESP-NOW hardware behavior; tests inject a
  fake transport into `MeshNetwork`.
- Verified: the core has no `espnow`/`network` import, transport lifecycle and
  status are tested, and unsupported `mesh.transport` values fail validation.

### 3. Egress reliability — partial

- Implemented: bounded persistent spool, HTTP 2xx validation, bounded
  exponential backoff, retry counters, corrupt-spool recovery, and egress
  status under `/mesh/status`.
- Remaining: `urequests.post` is synchronous on MicroPython and LoRa still has
  batch-level rather than per-record acknowledgements. Hardware-specific
  asynchronous HTTP requires a target-supported client.
- Verified: failed batches remain queued, retry windows are honored, spools
  survive restart, and status fields are covered by CPython tests.

### 4. LoRa egress framing — complete

- Implemented: authenticated framing, fragmentation/reassembly, bitmap ACKs,
  selective retry, native SX1262 adapter, external receiver, rotating logs and
  authenticated web console.
- Verified: fake-radio round trips, tamper rejection, receiver dedup/filtering,
  retention operations, settings, full pytest and compileall.
- Remaining: regional duty-cycle enforcement and airtime estimation require a
  deployment region to be selected explicitly.

## P1 — Operability

### 5. Settings and example configuration — partial

- Implemented: `lora` radio/key/retry settings, receiver storage settings,
  gateway/receiver examples, and defensive validation. The legacy flat
  fallback remains available for the ignored standalone `settings.json`, using
  tracked `settings.example.json` as its safe template.
- Remaining: validation is hand-written; there is no JSON schema.
- Verify: `tests/test_settings.py` covers each invalid combination; examples
  still fail on `CHANGE_ME_*` placeholders (expected).

### 6. LoRa mesh transport and bridge

- Current: LoRa is an authenticated gateway-to-receiver egress. It is not a
  node mesh transport and `mesh.transport` remains `espnow`.
- Gap: `mesh.transport: "lora"`, a device-id to 2-byte address map, a bridge
  role with ESP-NOW and LoRa instances, longer route intervals, packet
  aggregation, and a wider dedup window.
- Prerequisite: item 1. A broadcast LoRa mesh without authentication exposes
  every event to any receiver.
- Verify: protocol tests with a fake LoRa transport; loopback bridge test.

### 7. Route quality and time semantics

- Current: routing ranks by hop count and ACK failures only; RSSI/SNR is unused
  and device clocks are not synchronized (`lib/mesh_network.py:459`).
- Gap: optional link-quality metrics, deterministic tie-breaks, and either time
  sync or clearly gateway-relative timestamps.
- Verify: deterministic ranking/failover tests; document timestamp semantics.

### 8. Outbox durability

- Current: `queue_persist` is best effort, writes on every change, and a damaged
  file resets the queue. Writes use a temp file plus rename, but there is no
  torn-write or corruption test.
- Gap: corruption tests, bounded file size, and flash-wear guidance.
- Verify: simulate invalid JSON and interrupted writes; the node still boots.

### 9. Observability — partial

- Implemented: `/mesh/status` includes mesh counters, allowlist size, route
  metrics, active transport status, and stable egress backend/pending/spool and
  retry fields.
- Remaining: LoRa airtime estimation and regional duty-cycle counters.
- Verified: API tests assert authentication methods and the egress status shape.

## P2 — Tooling, firmware, docs

### 10. Test coverage

- Gaps: no tests for `wifi_radio`, `access_point`, `wifi`, the `/kbd` WebSocket,
  or hardware paths; no decode fuzzing; no loopback/integration test.
- Add: property/fuzz tests for `decode_packet`, a MeshNetwork loopback test, and
  an API auth matrix (Bearer, query token, `X-API-Key`, missing token).
- Verify: `python -m pytest -q`; keep tests deterministic and hardware-free.

### 11. CI and tooling

- Current: `.github/workflows/ci.yml` runs only `pytest` and `compileall`.
- Gap: no lint/format/type check, no MicroPython import check, no firmware
  build, and `pytest` is installed unpinned.
- Verify: keep CI fast and deterministic; add a step only when it is stable.

### 12. Documentation

- Keep `README.md` (setup/user view) and `MESHOPS.md` (protocol/design view) in
  sync with behavior changes.
- Add a configuration reference table, troubleshooting notes, and an
  architecture/sequence diagram.
- Update this roadmap when an item is closed or a new gap is confirmed.

## Suggested order

1. Item 1 (security foundation; item 2 is complete).
2. Items 3-5 (egress, LoRa framing, settings).
3. Item 6 (LoRa mesh/bridge) only after item 1.
4. Items 7-9 (routing, durability, observability).
5. Items 10-12 (tests, CI, docs).

## Out of scope

- Broadening the event allowlist or transporting arbitrary files/payloads.
- Initializing USB HID when `mesh_only` is set.
- OTA or production-readiness claims.
