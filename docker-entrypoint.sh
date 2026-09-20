#!/bin/sh
# Build the mitmdump command from environment variables and run it.
set -e

if [ -z "$JELLYFIN_URL" ]; then
  echo "ERROR: JELLYFIN_URL is required, e.g. -e JELLYFIN_URL=http://192.168.1.50:8096" >&2
  exit 1
fi

# Drop a trailing slash so reverse:URL is clean.
JELLYFIN_URL="${JELLYFIN_URL%/}"

case "$JELLYFIN_URL" in
  http://*|https://*) ;;
  *)
    echo "ERROR: JELLYFIN_URL must start with http:// or https:// (got: $JELLYFIN_URL)" >&2
    exit 1
    ;;
esac

LISTEN_PORT="${LISTEN_PORT:-8080}"

# LOG: events (default) = quiet mitmproxy + addon prints its events;
#      full = log every request; quiet = silent.
LOG="${LOG:-events}"
case "$LOG" in
  full)  FLOW="" ;;
  quiet) FLOW="--set flow_detail=0 --set termlog_verbosity=error" ;;
  *)     LOG="events"; FLOW="--set flow_detail=0 --set termlog_verbosity=warn" ;;
esac

[ "$LOG" != "quiet" ] && echo "jellyfin-force-transcode -> ${JELLYFIN_URL} | listen :${LISTEN_PORT} | rules: ${RULES_FILE:-/addon/rules.json} (none mounted = passthrough) | log: ${LOG}"

# EXTRA_ARGS lets power users append raw mitmdump flags; left unquoted on purpose.
exec mitmdump \
  --mode "reverse:${JELLYFIN_URL}" \
  --listen-host 0.0.0.0 \
  --listen-port "${LISTEN_PORT}" \
  -s /addon/rewrite.py \
  --set connection_strategy=lazy \
  --set stream_large_bodies=1m \
  --set keep_host_header=true \
  ${FLOW} \
  ${EXTRA_ARGS}
