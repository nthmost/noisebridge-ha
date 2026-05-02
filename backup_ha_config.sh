#!/bin/bash
# Pull key HA config files from homeassistant.local via beyla jump host.
# Requires SSH access to HA's Advanced SSH addon (port 2222).
#
# First-time setup — add beyla's public key to the HA SSH addon:
#   1. In HA UI: Settings → Add-ons → Advanced SSH & Web Terminal → Configuration
#   2. Paste this key into the "authorized_keys" list:
#      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICti+QmKa2awgdslElfCLLRxlTMTiNUcTg/Bz0iOzTs6 nthmost@Ubuntu
#   3. Save and restart the addon.
# After that, this script runs from any host (including this Mac) via beyla.

set -e

HA_HOST="homeassistant.local"
HA_PORT=2222
HA_USER="hassio"
JUMP="beyla"
DEST="$(dirname "$0")/config"

mkdir -p "$DEST"

scp_ha() {
    scp -o StrictHostKeyChecking=no -o ProxyJump="$JUMP" -P "$HA_PORT" \
        "${HA_USER}@${HA_HOST}:$1" "$2"
}

echo "Pulling HA config from ${HA_HOST}..."

scp_ha /config/configuration.yaml       "$DEST/configuration.yaml"
scp_ha /config/scripts.yaml             "$DEST/scripts.yaml"
scp_ha /config/automations.yaml         "$DEST/automations.yaml"
scp_ha /config/.storage/lovelace.noisebridge  "$DEST/lovelace.noisebridge.json"
scp_ha /config/.storage/lovelace.rooms        "$DEST/lovelace.rooms.json"

echo "Done. Files in $DEST:"
ls -lh "$DEST"

cd "$(dirname "$0")"
if git diff --quiet config/; then
    echo "No changes since last backup."
else
    git add config/
    git commit -m "ha config backup $(date +%Y-%m-%d)"
    git push
    echo "Committed and pushed."
fi
