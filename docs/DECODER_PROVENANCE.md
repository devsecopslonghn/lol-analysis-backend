# Decoder provenance

## Replay under analysis

- Replay: `VN2-1568084329.rofl`
- Client: `16.17.810.4348`
- Semantic movement status: `candidate` (warning-only)
- Transport candidate: `0x022c`
- Candidate observations: `15,372`, from `0.000s` to `1793.281s`

## What was found

The public RoflLens project contains a semantic profile for client
`16.14.794.5912`. Its movement and death configurations are useful as a
legacy reference for identifying candidate fields, but they are not an exact
runtime decoder for client `16.17.810.4348`. The replay report therefore
records this profile as `candidate` in `warning_only` mode and never emits
coordinates, routes, ganks or entity ownership from it.

ROFL-X documents the same operational constraint: packet dispatch, decoder
locations and allocators can vary by patch. A new profile requires discovery
against the matching game binary and reconciliation against replay totals.

## Output contract

`movement_transport.jsonl` and `opcode_0226_transport.jsonl` contain only
framing evidence:

- timestamp and chunk/stream identity;
- opcode and parameter;
- payload length;
- `status: candidate` and `semantic_status: transport_only`.

They intentionally do not contain decoded payload bytes or inferred
coordinates. A future exact adapter must verify client version/hash before
replacing these candidate artifacts with `verified` movement or event records.
The old profile cannot be executed by the service unless matching client
executable sections are supplied; the profile JSON alone is insufficient.
