#!/bin/bash
# Pull key HA config files from homeassistant.local via beyla.
# Requires beyla's SSH key in the HA Advanced SSH addon authorized_keys.
#
# First-time setup — add beyla's public key to the HA SSH addon:
#   1. In HA UI: Settings → Add-ons → Advanced SSH & Web Terminal → Configuration
#   2. Paste this key into the "authorized_keys" list:
#      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICti+QmKa2awgdslElfCLLRxlTMTiNUcTg/Bz0iOzTs6 nthmost@Ubuntu
#   3. Save and restart the addon.
#
# Note: SCP via ProxyJump requires the local machine's key in HA's authorized_keys.
# Instead, this script SSHes into beyla first, then cats each file over stdout.

set -e

HA_PORT=2222
HA_USER="hassio"
HA_HOST="homeassistant.local"
JUMP="beyla"
DEST="$(dirname "$0")/config"

mkdir -p "$DEST"

pull_ha() {
    ssh "$JUMP" "ssh -p $HA_PORT $HA_USER@$HA_HOST 'cat $1'" > "$2"
}

echo "Pulling HA config from ${HA_HOST} via ${JUMP}..."

pull_ha /config/configuration.yaml       "$DEST/configuration.yaml"
pull_ha /config/scripts.yaml             "$DEST/scripts.yaml"
pull_ha /config/automations.yaml         "$DEST/automations.yaml"
pull_ha /config/.storage/lovelace.noisebridge  "$DEST/lovelace.noisebridge.json"
pull_ha /config/.storage/lovelace.rooms        "$DEST/lovelace.rooms.json"

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
