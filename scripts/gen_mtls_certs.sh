#!/usr/bin/env bash
# Generate CA and client certificates for mTLS (mutual TLS).
# Run from repo root, or the script will cd to repo root automatically.
# Output: https/certs/ca.crt, https/certs/ca.key, https/certs/client.crt, https/certs/client.key
# The server uses ca.crt to verify client certificates. Clients use client.crt + client.key.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

CERTS_DIR="${1:-https/certs}"
mkdir -p "$CERTS_DIR"
cd "$CERTS_DIR"

# CA (used by server to verify client certs)
echo "Generating CA (ca.key, ca.crt)..."
openssl genrsa -out ca.key 2048
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt \
  -subj "/CN=Maze-mTLS-CA/O=PSU-Capstone"

# Client cert (signed by CA; used by robots/clients to authenticate)
echo "Generating client certificate (client.key, client.crt)..."
openssl genrsa -out client.key 2048
openssl req -new -key client.key -out client.csr \
  -subj "/CN=minipupper-client/O=PSU-Capstone"
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out client.crt -days 3650 -sha256
rm -f client.csr

echo "Done. Certificates in $CERTS_DIR:"
ls -la ca.crt ca.key client.crt client.key 2>/dev/null || true
echo
echo "To enable mTLS on the server: ensure $CERTS_DIR/ca.crt exists (it does now)."
echo "Start the HTTPS server from the repo root or from https/ with certs in https/certs/."
echo "Test with: curl -k --cert $CERTS_DIR/client.crt --key $CERTS_DIR/client.key -X POST https://localhost:8443/move -H 'Content-Type: application/json' -d '{\"event_type\":\"test\"}'"
