# IoT device accounts on Noisebridge HA

**TL;DR:** One shared HA user account, reused as MQTT credentials for every IoT device. Don't create one user per device.

## Why this pattern

Adding "smart" devices that talk MQTT to HA — Picos, ESP32s, custom controllers — needs credentials so the Mosquitto add-on accepts the connection. Two anti-patterns to avoid:

- **One HA user per device.** Sounds clean (revocable per-device, blast-radius limited), but unmaintainable at scale. Every device add becomes a click-through in the HA UI, every device removal another one, and the *Users* page becomes a junkyard of `pico-foo`, `esp32-bar`, etc. that nobody remembers commissioning.
- **`anonymous: true` on the Mosquitto add-on.** Zero accounts to maintain — but the Noisebridge wifi is a shared community network. Anyone associated to `Noisebridge` can then publish to any HA topic and trigger anything HA can do. Hard no.

## The pattern

1. **One HA user account**, shared across all IoT devices. Name it something obvious like `devices` or `mqtt-bridge`. Mark it as a regular user (not admin).
2. **One password**, stored in `~/projects/nthmost-systems/.secrets/ha-noisebridge-mqtt.env` on the master Mac, synced to relevant hosts.
3. **Every IoT device** uses those same creds for its MQTT client.

Tradeoffs accepted:
- If any one device is compromised, an attacker has the MQTT creds for all of them. Acceptable for a hackerspace where the LAN is already semi-trusted and the blast radius is "weird LED behaviour".
- Per-device revocation isn't possible — rotating means updating every device. Cadence: rotate annually or after any suspected leak.

## How to add a new device

1. Source the creds locally: `source ~/projects/nthmost-systems/.secrets/ha-noisebridge-mqtt.env`
2. Configure the device's MQTT client with `MQTT_USER` / `MQTT_PASS` from that file, broker at `10.21.0.43:1883` (or whatever `homeassistant.local` resolves to on the LAN).
3. Publish an HA MQTT-discovery message on `homeassistant/<component>/<unique_id>/config` (retained) so HA auto-creates the entity. See [HA MQTT discovery docs](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery).
4. Optionally add the device to `docs/iot-inventory.md` (TODO file) so we know what's on the broker.

## How to remove a device

- Unplug it.
- Send an empty retained message to its discovery topic to remove the entity from HA, e.g.:
  ```
  mosquitto_pub -h 10.21.0.43 -u "$MQTT_USER" -P "$MQTT_PASS" \
    -t "homeassistant/light/sp648e_noisebridge/config" -r -n
  ```

## Rotating credentials

1. Change the password on the `devices` user in HA (Settings → People → Users).
2. Update `~/projects/nthmost-systems/.secrets/ha-noisebridge-mqtt.env`.
3. Push updated creds to every device that uses them (each device project should document its own redeploy step).
