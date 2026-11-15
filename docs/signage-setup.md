# Samsung signage URL setup

Three signage screens in KEH, EOJ, and ARK display the webpage served by the
dedicated Linux PC. Each screen uses Samsung's built-in internet/URL feature
to open `https://<DOMAIN>/` directly using its integrated browser. The Mac
Studio is outside this deployment.

The CSV lists Samsung business TVs; confirm the exact SKU/size and test the
webpage on their integrated URL feature before installation. These instructions describe
required behaviour without assuming a particular vendor menu or firmware.

## 1. Prepare the server URL

During local setup, `bash run.sh --local` serves the app at
`http://localhost:8080` on the server PC. The HTTP configuration accepts network
hostnames/current DHCP addresses as well. On a Samsung screen, use
`http://SERVER_NETWORK_NAME:8080/` or the PC's current network IP with port 8080.
`localhost` on the TV points to the TV, not the Linux server. The final domain
can be configured later in `.env`.

1. Start the Linux server stack using the [`README`](../README.md) quick start.
2. Configure the approved public HTTPS endpoint/domain with UiS IT.
3. Check these URLs from the network used by the screens:

   | URL | Purpose |
   |---|---|
   | `https://<DOMAIN>/` | Display webpage opened directly by the Samsung screens |
   | `https://<DOMAIN>/overview` | Interactive dashboard |
   | `https://<DOMAIN>/mobile` | Mobile view |
   | `https://<DOMAIN>/health` | Server health check |
   | `https://<DOMAIN>/api/system/status` | Data mode and refresh interval |

Confirm `mode: live` and `data_source: timescaledb`, then check recent sensor
timestamps. The API always uses the database. A reachable
webpage alone does not prove that sensor ingestion works.

## 2. Configure each Samsung screen

1. Connect the screen to the approved network and set its clock correctly.
2. Set the built-in URL feature's startup address to `https://<DOMAIN>/`.
3. Enable full-screen landscape display and test fit/readability at the actual
   resolution, with no clipping, browser chrome, or overscan.
4. Set startup after power loss and the display schedule appropriate to the
   building. Prevent sleep/screensavers from interrupting the agreed schedule.
5. Configure the Samsung screen's URL reload/recovery behaviour if available.
   The webpage itself refreshes sensor data using `DISPLAY_REFRESH_SECONDS`
   (default 60 seconds). This controls how often the webpage requests new data.

Scripts, charts, fonts, and QR images are served by the local app. The display
only needs access to the dashboard server. D3 is bundled with its license.

## 3. Verify on the actual screens

- Check both landscape and portrait orientations after rotating the screen.
  The page adapts automatically without a reload: landscape shows building
  cards side by side, and portrait uses two columns. Charts redraw to fit.
  Phone-sized or very short windows allow scrolling within the active scene.
- All scenes render and rotate without requiring a mouse/keyboard.
- Values, freshness, and source status refresh after a real gateway uplink.
- Source and freshness labels match the actual sensor readings.
- Charts render, text is readable, and the correct domain is shown.
- Set `PUBLIC_BASE_URL` to a phone-reachable HTTP(S) origin if the display uses
  a different internal address. Check that `/api/system/status` reports the
  expected `dashboard_url`, and scan the generated `/qr/dashboard.png` image.
- The mobile URL works from a phone outside the campus network if public
  access is intended. Verify that the displayed QR code opens the final URL.
- After screen power loss, the screen returns to the configured URL.
- After a network outage or Linux server restart, the display resumes data
  updates; record any screen-specific recovery action that is needed.

Record each screen's location, model/firmware, startup URL, network connection,
display schedule, and recovery settings for handover.

## Refresh configuration

Set `DISPLAY_REFRESH_SECONDS` in the Linux server's `.env` to preserve any
custom refresh interval, then recreate the API container to apply the setting:

```bash
docker compose up -d api
```

Clients of `/api/system/status` should read `display_refresh_seconds` for this
interval. Each screen continues to open the main webpage URL.
