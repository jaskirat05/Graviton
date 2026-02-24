#!/bin/sh
# Cross-platform entrypoint for ComfyAutomate
# The container always runs Linux, but host can be Windows/Mac/Linux

# Create directories if they don't exist
mkdir -p /app/templates /app/artifacts

# Fix ownership if HOST_UID and HOST_GID are provided (Linux/Mac)
# On Windows Docker Desktop, file permissions are handled automatically
if [ -n "$HOST_UID" ] && [ -n "$HOST_GID" ]; then
    chown -R "$HOST_UID:$HOST_GID" /app/templates /app/artifacts 2>/dev/null || true
fi

# Wait for Temporal when configured (used by gateway + worker containers).
# Default behavior: enabled when TEMPORAL_ADDRESS is set.
if [ "${WAIT_FOR_TEMPORAL:-1}" = "1" ] && [ -n "$TEMPORAL_ADDRESS" ]; then
    ATTEMPTS="${TEMPORAL_WAIT_ATTEMPTS:-90}"
    DELAY_SECS="${TEMPORAL_WAIT_DELAY_SECS:-2}"
    TIMEOUT_SECS="${TEMPORAL_WAIT_TIMEOUT_SECS:-1.5}"

    echo "Waiting for Temporal at ${TEMPORAL_ADDRESS} (attempts=${ATTEMPTS}, delay=${DELAY_SECS}s)..."

    i=1
    while [ "$i" -le "$ATTEMPTS" ]; do
        if python - "$TEMPORAL_ADDRESS" "$TIMEOUT_SECS" <<'PY'
import socket
import sys

addr = sys.argv[1].strip()
timeout = float(sys.argv[2])

host, sep, port_text = addr.partition(":")
if not sep:
    host = addr
    port = 7233
else:
    try:
        port = int(port_text)
    except ValueError:
        port = 7233

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(timeout)
try:
    s.connect((host, port))
    sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
        then
            echo "Temporal is reachable at ${TEMPORAL_ADDRESS}"
            break
        fi

        if [ "$i" -eq "$ATTEMPTS" ]; then
            echo "Timed out waiting for Temporal at ${TEMPORAL_ADDRESS}"
            exit 1
        fi

        echo "Temporal not ready yet (${i}/${ATTEMPTS}), retrying in ${DELAY_SECS}s..."
        i=$((i + 1))
        sleep "$DELAY_SECS"
    done
fi

# Execute the main command
exec "$@"
