# Maze App Guide

## Run
From repo root:
```bash
./maze/maze_sdl2
```

## Dashboard mode by platform
- **macOS**: pressing `L` toggles the embedded HTML dashboard in the same SDL window (WKWebView path).
- **Linux/Ubuntu/WSL**: embedded WKWebView is not used; dashboard behavior falls back to non-macOS path.
- If your platform does not support embedding, keep the local dashboard server running and view it in browser as fallback.

## Controls quick reference (`maze_sdl2`)
- **Laptop/keyboard**
  - Move: Arrow keys or `W/A/S/D`
  - Dashboard toggle: `L`
  - Regenerate maze: `R`
  - Toggle AI autoplay: `P`
  - Quit: `Esc`
- **GameController / Game HAT style mapping**
  - Move: D-pad
  - Toggle AI autoplay: `L1` (left shoulder), fallback `Y`
  - Dashboard toggle: `Back` / `Select`
  - Regenerate maze: `Start`

## AI autoplay discovery helper
If you are not sure what command/port your teammate used for the AI brain service:
```bash
bash scripts/find_ai_brain.sh
```

If a candidate is found, the script prints the exact `MAZE_AUTOPLAY=1 ... ./maze/maze_sdl2` command to use.

## mTLS quickstart (zero-trust transport)
Use this when you need certificate-authenticated HTTPS between maze client and servers.

1. Generate certs (CA + server + client):
```bash
bash scripts/gen_mtls_certs.sh
```

2. Start HTTPS servers with mTLS enabled (example: logging server):
```bash
CERT_FILE=https/certs/server.crt \
KEY_FILE=https/certs/server.key \
CA_FILE=https/certs/ca.crt \
LISTEN_PORT=8443 \
./https/maze_https_mongo
```

3. Run maze client with certificate verification + client cert:
```bash
MAZE_TLS_CA_FILE=https/certs/ca.crt \
MAZE_TLS_CLIENT_CERT=https/certs/client.crt \
MAZE_TLS_CLIENT_KEY=https/certs/client.key \
MAZE_LOGGING_URL=https://10.170.8.130:8443/move \
MAZE_AI_URL=https://10.170.8.109:8443/move \
MAZE_MISSION_URL=https://10.170.8.109:8443/mission \
./maze/maze_sdl2
```

Notes:
- `MAZE_TLS_INSECURE=1` exists only for temporary local debugging; keep it unset for real mTLS.
- With mTLS enabled on servers, requests without client cert are rejected.
