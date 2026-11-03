# Home Assistant

Home Assistant plays two roles. It is a **data source** for the dashboard (weather,
shopping list, sensors, bins; see [server.md](server.md#configuration)). It can also
**monitor the Kindle** through the server's `/status` endpoint, and show the current
dashboard image.

## Monitoring package

`ha/fridge_kindle.yaml` is a Home Assistant
[package](https://www.home-assistant.io/docs/configuration/packages/). It polls the
server once a minute and needs no token, since `/status` and `/dash.png` are open on
the LAN.

1. Replace `192.168.68.124:8090` in the file with your server's address (it appears
   twice).
2. Copy the file to `<config>/packages/fridge_kindle.yaml`.
3. If `configuration.yaml` does not load packages yet, add:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
4. Check the configuration and restart Home Assistant.

| Entity | Meaning |
|---|---|
| `binary_sensor.fridge_kindle_online` | On while the Kindle keeps to the schedule it announced (with 10 min grace). Quiet hours count as on schedule. |
| `binary_sensor.fridge_kindle_charging` | On while charging |
| `sensor.fridge_kindle_battery` | Battery % at the last check-in |
| `sensor.fridge_kindle_last_seen`, `sensor.fridge_kindle_next_check_in` | Times of the last and next check-in |
| `sensor.fridge_dashboard_rendered` | Time of the last server render |
| `image.fridge_dashboard` | The current dashboard. Home Assistant proxies it, so it also works away from home. |

The image entity re-fetches only when its URL changes, so the URL includes the render
time.

## Dashboard card

```yaml
type: vertical-stack
cards:
  - type: picture-entity
    entity: image.fridge_dashboard
    show_state: false
    show_name: false
  - type: entities
    entities:
      - binary_sensor.fridge_kindle_online
      - sensor.fridge_kindle_battery
      - binary_sensor.fridge_kindle_charging
      - sensor.fridge_kindle_next_check_in
```

## Example automation

This automation notifies you when the Kindle needs charging or has stopped checking in.
Replace `notify.notify` with your own notifier.

```yaml
automation:
  - alias: Fridge Kindle needs attention
    triggers:
      - trigger: numeric_state
        entity_id: sensor.fridge_kindle_battery
        below: 15
        id: battery
      - trigger: state
        entity_id: binary_sensor.fridge_kindle_online
        to: "off"
        for: "00:30:00"
        id: offline
    actions:
      - action: notify.notify
        data:
          message: >-
            {{ 'Fridge Kindle battery at ' ~ states('sensor.fridge_kindle_battery') ~ '%'
               if trigger.id == 'battery' else 'Fridge Kindle stopped checking in' }}
```
