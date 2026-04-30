#!/usr/bin/env bash
set -euo pipefail

cd /app/src
exec python3 -m carriers_sync
