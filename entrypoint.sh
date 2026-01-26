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

# Execute the main command
exec "$@"
