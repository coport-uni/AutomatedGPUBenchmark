#!/usr/bin/env bash
# Container entrypoint. It only prepares writable scratch directories
# and then replaces itself with the command, so signals reach the
# command directly; `docker run --init` supplies the zombie reaper.
set -euo pipefail

mkdir -p "${MPLCONFIGDIR:-/tmp/matplotlib}"

exec "$@"
