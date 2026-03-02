# maze_https_mongo
**C HTTPS JSON → MongoDB Server**

This project is a secure (HTTPS/TLS) version of the original `maze_http_mongo` server.

It is a small **C** program that:

- Listens for **HTTPS** requests (TLS)
- Receives a **JSON document**
- Appends a server timestamp
- Inserts the document into **MongoDB**

---

## Endpoint

- **POST** `/move`
- **Content-Type:** `application/json`
- **Protocol:** HTTPS

The server automatically appends:

```json
"received_at": "YYYY-MM-DDTHH:MM:SSZ"
```

---

## Requirements

### Libraries
- `libmicrohttpd` (with TLS / GnuTLS support)
- MongoDB C Driver:
  - `libmongoc`
  - `libbson`
- `pkg-config`
- `gcc` or `clang`

### Debian / Ubuntu / Raspberry Pi OS

```bash
sudo apt update
sudo apt install -y   build-essential   pkg-config   libmicrohttpd-dev   libgnutls28-dev   libmongoc-dev   libbson-dev
```

---

## TLS Certificates (Required)

For development and lab use, generate a **self-signed certificate**:

```bash
mkdir certs
cd certs

openssl req -x509 -newkey rsa:2048   -keyout server.key   -out server.crt   -days 365   -nodes   -subj "/CN=localhost"
```

Expected files:

```
certs/server.crt
certs/server.key
```

---

## Build

```bash
gcc -O2 -Wall -Wextra -std=c11 maze_https_mongo.c -o maze_https_mongo   $(pkg-config --cflags --libs libmicrohttpd libmongoc-1.0 gnutls)
```

---

## Run

### Default configuration

```bash
./maze_https_mongo
```

Defaults:
- **Port:** `8443`
- **Mongo URI:** `mongodb://localhost:27017`
- **Database:** `maze`
- **Collection:** `moves`
- **TLS Cert:** `certs/server.crt`
- **TLS Key:** `certs/server.key`

### Override using environment variables

```bash
LISTEN_PORT=9443 CERT_FILE=certs/server.crt KEY_FILE=certs/server.key MONGO_URI="mongodb://localhost:27017" MONGO_DB="maze" MONGO_COL="moves" ./maze_https_mongo
```

---

## Test with curl

Because a self-signed certificate is used, include `-k`:

```bash
curl -k -X POST https://localhost:8443/move   -H "Content-Type: application/json"   -d '{
    "event_type": "player_move",
    "input": {
      "device": "joystick",
      "move_sequence": 1
    },
    "player": {
      "position": { "x": 1, "y": 2 }
    },
    "goal_reached": false,
    "timestamp": "2026-01-25T11:42:18Z"
  }'
```

Expected response:

```json
{"status":"ok"}
```

---

## SDL / Game Client Notes

From an SDL or C-based client, HTTPS requests are commonly sent using **libcurl**.

For development (self-signed certificates only):

```c
curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);
```

⚠️ Do **not** disable certificate verification in production.

---

## Mutual TLS (mTLS)

To require **client certificates** (robot/client authentication), use a CA and client certs.

### 1. Generate CA and client certificates

From the repository root:

```bash
./scripts/gen_mtls_certs.sh
```

This creates in `https/certs/`:

- `ca.crt`, `ca.key` — CA used by the server to verify client certs  
- `client.crt`, `client.key` — client certificate for robots or API clients  

### 2. Run the server with mTLS

Start the server from the **https/** directory so it finds `certs/` (i.e. `https/certs/`).  
If `certs/ca.crt` exists, the server will require a valid client certificate.

```bash
cd https
./maze_https_mongo
```

Or from the repo root with explicit paths:

```bash
CERT_FILE=https/certs/server.crt KEY_FILE=https/certs/server.key CA_FILE=https/certs/ca.crt ./https/maze_https_mongo
```

### 3. Test with curl (client certificate)

```bash
curl -k \
  --cert https/certs/client.crt \
  --key https/certs/client.key \
  -X POST https://localhost:8443/move \
  -H "Content-Type: application/json" \
  -d '{"event_type":"player_move","player":{"position":{"x":1,"y":2}},"goal_reached":false}'
```

Without `--cert`/`--key`, the server will reject the request when mTLS is enabled.

**Note:** mTLS requires libmicrohttpd built with GnuTLS support and the `MHD_OPTION_HTTPS_MEM_TRUST` option (common in recent versions).

---

## Production Notes

For production deployments:

- Use a **CA-signed certificate** (Let’s Encrypt or internal CA)
- Enable TLS verification on clients
- Use **mTLS** (client certificates) as shown above for robot/API identity
- Consider JWT or API key authentication in addition
- Consider running behind a reverse proxy (nginx)

---

## Summary

✔ Encrypted HTTPS transport  
✔ Optional mTLS (client certificates) via `CA_FILE` / `certs/ca.crt`  
✔ Same JSON payload as HTTP version  
✔ MongoDB ingestion unchanged  
✔ Ideal for labs, SDL games, and telemetry pipelines  
