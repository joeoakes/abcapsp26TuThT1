#!/usr/bin/env bash
set -e # Exit immediately on error

echo "Building all maze applications..."
echo

# =========================
# Build maze_sdl2
# =========================
SRC="maze/maze_sdl2.c"
OUT="maze/maze_sdl2"

echo "Compiling $SRC → $OUT"

gcc -O2 -Wall -Wextra -std=c11 \
    "$SRC" \
    -o "$OUT" \
    $(pkg-config --cflags --libs sdl2 libcurl uuid)

echo "maze_sdl2 build successful."
echo

# =========================
# Build maze_https_mongo
# =========================
SRC="https/maze_https_mongo.c"
OUT="https/maze_https_mongo"

echo "Compiling $SRC → $OUT"

gcc -O2 -Wall -Wextra -std=c11 \
    "$SRC" \
    -o "$OUT" \
    $(pkg-config --cflags --libs libmicrohttpd libmongoc-1.0 gnutls)

echo "maze_https_mongo build successful."
echo

# =========================
# Build maze_https_redis
# =========================
SRC="https/maze_https_redis.c"
OUT="https/maze_https_redis"

echo "Compiling $SRC → $OUT"

gcc -O2 -Wall -Wextra -std=c11 \
    "$SRC" \
    -o "$OUT" \
    $(pkg-config --cflags --libs libmicrohttpd libcurl openssl hiredis uuid)

echo "maze_https_redis build successful."
echo

echo "All builds completed successfully."
