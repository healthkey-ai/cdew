#!/bin/sh
# Deploy-image entrypoint (#31 Part C).
#
# Render mounts the persistent disk for uploaded originals at runtime, and the
# docs don't promise who owns it. Starting as root, make MEDIA_ROOT exist and
# belong to `appuser`, then drop privileges for the real command — the app
# itself never runs as root. (The pre-deploy `migrate` runs without the disk;
# mkdir just creates an unused local directory there.)
set -eu

if [ "$(id -u)" = "0" ]; then
  if [ -n "${MEDIA_ROOT:-}" ]; then
    mkdir -p "$MEDIA_ROOT"
    chown -R appuser:appuser "$MEDIA_ROOT"
  fi
  exec setpriv --reuid=appuser --regid=appuser --init-groups -- "$@"
fi

exec "$@"
