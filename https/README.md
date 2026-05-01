# HTTPS Services (Mongo, Redis, Mini-Pupper)

This directory contains three C HTTPS servers used in the project pipeline:

- `maze_https_mongo` -> receives telemetry and stores in MongoDB
- `maze_https_redis` -> receives telemetry/mission JSON and stores in Redis
- `maze_https_minipupper` -> legacy/manual body-relative Mini-Pupper flow/testing

For AI maze autoplay, use the Python bridge in `robot/` instead. It maps `UP`, `DOWN`, `LEFT`, and `RIGHT` to absolute maze-grid cell movement and waits for robot completion acknowledgements.

All servers support TLS on `/move`, and support mTLS when `CA_FILE` is provided.

---

## Security Model

- Transport: HTTPS (TLS)
- Identity: X.509 certificates
- Optional mutual auth: mTLS (server verifies client cert against CA)
- Typical port in this project: `8443`

For zero-trust-style deployment, run with:
- `CERT_FILE` + `KEY_FILE` (server identity)
- `CA_FILE` (required client-certificate trust anchor)

---

## Build

From repo root:

```bash
bash scripts/build.sh
```

If Mongo C driver is unavailable locally:

```bash
SKIP_HTTPS_MONGO=1 bash scripts/build.sh
```

---

## Generate Certificates (CA + server + client)

From repo root:

```bash
bash scripts/gen_mtls_certs.sh
```

Generated in `https/certs/`:

- `ca.crt`, `ca.key`
- `server.crt`, `server.key`
- `client.crt`, `client.key`

---

## Run Servers with mTLS

### Mongo logging server

```bash
CERT_FILE=https/certs/server.crt \
KEY_FILE=https/certs/server.key \
CA_FILE=https/certs/ca.crt \
LISTEN_PORT=8443 \
MONGO_URI="mongodb://localhost:27017" \
MONGO_DB="maze" \
MONGO_COL="team1ttmoves" \
./https/maze_https_mongo
```

### Redis server

```bash
CERT_FILE=https/certs/server.crt \
KEY_FILE=https/certs/server.key \
CA_FILE=https/certs/ca.crt \
LISTEN_PORT=8443 \
REDIS_HOST=127.0.0.1 \
REDIS_PORT=6379 \
REDIS_PREFIX=team1tt \
./https/maze_https_redis
```

### Mini-Pupper server (legacy/manual)

```bash
CERT_FILE=https/certs/server.crt \
KEY_FILE=https/certs/server.key \
CA_FILE=https/certs/ca.crt \
LISTEN_PORT=8443 \
./https/maze_https_minipupper
```

When `CA_FILE` is set, requests without a valid client certificate are rejected.

---

## Test with curl (mTLS)

```bash
curl --cacert https/certs/ca.crt \
  --cert https/certs/client.crt \
  --key https/certs/client.key \
  -X POST https://localhost:8443/move \
  -H "Content-Type: application/json" \
  -d '{
    "event_type":"player_move",
    "input":{"device":"joystick","move_sequence":1},
    "player":{"position":{"x":1,"y":2}},
    "goal_reached":false,
    "timestamp":"2026-01-25T11:42:18Z"
  }'
```

---

## Maze Client mTLS Settings

`maze/maze_sdl2` supports these TLS env vars for outbound HTTPS to logging/AI servers:

- `MAZE_TLS_CA_FILE`
- `MAZE_TLS_CLIENT_CERT`
- `MAZE_TLS_CLIENT_KEY`
- `MAZE_TLS_INSECURE=1` (debug only; avoid in deployment)

Example:

```bash
MAZE_TLS_CA_FILE=https/certs/ca.crt \
MAZE_TLS_CLIENT_CERT=https/certs/client.crt \
MAZE_TLS_CLIENT_KEY=https/certs/client.key \
MAZE_LOGGING_URL=https://10.170.8.130:8443/move \
MAZE_AI_URL=https://10.170.8.109:8443/move \
MAZE_MISSION_URL=https://10.170.8.109:8443/mission \
./maze/maze_sdl2
```

---

## Notes

- Mongo target for this team is `team1ttmoves`.
- Redis is documented as namespace/prefix `team1tt` (key format may vary by server implementation).
