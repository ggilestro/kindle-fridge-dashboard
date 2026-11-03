#!/bin/sh
# Copy server/ to the Docker host and rebuild the container.
#
# Usage: scripts/deploy-server.sh [-n]      (-n = dry run: list what rsync would change)
#
# DEPLOY_HOST (ssh host, default "homelab") and DEPLOY_DIR (path on that host, default
# "Dockers/basic/kindle-dash") pick the target. The .env file (secrets) and data/
# (rendered pages, battery log) on the host are never touched.
set -eu

HOST=${DEPLOY_HOST:-homelab}
DIR=${DEPLOY_DIR:-Dockers/basic/kindle-dash}
SRC=$(cd "$(dirname "$0")/../server" && pwd)

case "${1:-}" in
"") DRY="" ;;
-n) DRY="--dry-run --itemize-changes" ;;
*)
    echo "usage: $0 [-n]" >&2
    exit 2
    ;;
esac

# Reason: the trailing slash on SRC copies the folder's contents; without it --delete
# would sync into DIR/server and wipe everything else in DIR.
# shellcheck disable=SC2086 # DRY is either empty or two separate options
rsync -a --delete $DRY \
    --exclude .env --exclude data --exclude __pycache__ --exclude .pytest_cache \
    "$SRC/" "$HOST:$DIR/"

[ -z "$DRY" ] || exit 0
# shellcheck disable=SC2029 # DIR is meant to expand locally
if ! ssh "$HOST" "test -f '$DIR/.env'"; then
    echo "Copied. Now create $HOST:$DIR/.env from .env.example and run this again." >&2
    exit 1
fi
# Reason: a bind-mount source Docker creates itself is owned by root, and the container
# runs as uid 1000.
# shellcheck disable=SC2029
ssh "$HOST" "cd '$DIR' && mkdir -p data && docker compose up -d --build"
