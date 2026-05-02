# Pending HA Config Additions

These need to be applied to the live HA instance once SSH access is set up.

## configuration.yaml — add to rest_command section

```yaml
  ft_qr:
    url: "http://beyla:8877/ft/qr"
    method: POST
    content_type: application/json
    payload: '{"url": "https://donate.noisebridge.net", "layer": 5, "duration": 0}'
```

## lovelace.noisebridge — add QR panel to FlaschenTaschen view

Add this card to the `cards` array in the FlaschenTaschen view:

```yaml
- type: vertical-stack
  cards:
    - type: markdown
      content: "## Donate QR Code"
    - type: horizontal-stack
      cards:
        - type: button
          name: Show Donate QR
          icon: mdi:qrcode
          tap_action:
            action: call-service
            service: rest_command.ft_qr
        - type: button
          name: Clear Layer
          icon: mdi:layers-remove
          tap_action:
            action: call-service
            service: rest_command.ft_clear
            service_data:
              layer: 5
```
