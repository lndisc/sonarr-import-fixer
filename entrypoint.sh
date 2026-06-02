#!/bin/sh

echo "Sonarr Fix Imports Container"
echo "============================"
echo "SONARR_URL: $SONARR_URL"
echo "INTERVAL: ${INTERVAL}s"
echo "DRY_RUN: $DRY_RUN"
echo "PUID: ${PUID} / PGID: ${PGID}"
echo ""

# Create group and user matching PUID/PGID
addgroup -g "${PGID}" appgroup 2>/dev/null || true
adduser -D -u "${PUID}" -G appgroup appuser 2>/dev/null || true

# Wait for Sonarr to be available
echo "Waiting for Sonarr to be available..."
until wget -q --spider --header="X-Api-Key: $SONARR_API_KEY" "$SONARR_URL/api/v3/system/status" 2>&1; do
    echo "Sonarr not ready, waiting 10s..."
    sleep 10
done
echo "Sonarr is available!"

# Main loop
while true; do
    echo ""
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Running fix imports..."

    if [ "$DRY_RUN" = "true" ]; then
        su-exec appuser python3 /app/sonarr-fix-imports.py --dry-run
    else
        su-exec appuser python3 /app/sonarr-fix-imports.py
    fi

    echo "$(date '+%Y-%m-%d %H:%M:%S') - Sleeping ${INTERVAL}s..."
    sleep "$INTERVAL"
done
