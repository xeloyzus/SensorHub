# Hardware inventory and deployment decisions

Source: [`hardware.csv`](hardware.csv), copied unchanged from the supplied
hardware CSV on 30 October 2026. Prices and product descriptions below are
from that file, not independently verified supplier specifications.

## Confirmed deployment decisions

- NanitesLab runs on a dedicated PC with Linux.
- Three Samsung signage screens use their built-in internet/URL feature to
  open `https://<DOMAIN>/` directly using their integrated browser.
- The Mac Studio is used for other work and is excluded from this deployment.
- The CSV proposes a GMKtec G10 for ChirpStack/MQTT. Whether this is also the
  dedicated Linux server or remains a separate edge node is unresolved.

## Imported equipment

| Equipment | Quantity | Unit price (NOK) | Subtotal (NOK) | Deployment role / status |
|---|---:|---:|---:|---|
| Milesight AM103 | 12 | 2,377 | 28,524 | Air quality across KEH, EOJ, ARK, SiS; spare count inconsistent |
| GMKtec G10 Mini PC (Ryzen 5, 16GB) | 1 | 5,499 | 5,499 | Listed for ChirpStack/MQTT; server/edge split unresolved |
| Milesight CT305 | 3 | 2,259 | 6,777 | One per major building: KEH, EOJ, ARK |
| Milesight UG65 | 3 | 3,469 | 10,407 | Gateways in KEH, EOJ, ARK; measure SiS coverage on site |
| SANDISK WD Black SN7100 SSD (1TB) | 1 | 2,190 | 2,190 | CSV assigns it to the Mac Studio; project role/compatibility unresolved |
| Samsung business signage TV (CSV: `55" 4K BE65F-H`) | 3 | 5,624 | 16,872 | One display per major building; confirm exact model/size and URL player |
| Wall mount | 3 | 999 | 2,997 | One per display |
| Mac Studio | 1 | 32,999 | 32,999 | Outside NanitesLab per user clarification |
| Milesight AM107 | 4 | 3,171 | 12,684 | Large auditoriums; telemetry and climate analytics supported |
| Contingency / miscellaneous | 0 | 15,000 | 0 | Described as a cap; currently contributes zero to the total |

## Budget reconciliation

- Source equipment total: **118,949 NOK**, matching its summary row.
- Source budget: **150,000 NOK**; source balance: **31,051 NOK**.
- Excluding only the Mac Studio row: **85,950 NOK**, leaving **64,050 NOK**.
  This still includes the SSD, whose role needs confirming, and does not add
  a separately priced Linux server if the GMKtec is only an edge node.
- Reserving the stated 15,000 NOK contingency after excluding the Mac Studio
  leaves **49,050 NOK** unallocated. The source CSV has not been rewritten.
- The source marks zero items purchased; this is a plan, not proof of installation.

## Open discrepancies and implementation gaps

1. **AM103 quantity:** quantity is 12, but the notes say 10 active + 3 spares
   (13 total). Ten active would leave two spares within the stated quantity.
2. **Hosting:** the user's Linux PC decision supersedes the Mac Studio hosting
   note. Confirm whether the GMKtec is that PC or a separate edge machine.
3. **SSD:** its source note still targets the Mac Studio. Confirm whether it
   belongs in NanitesLab and check suitability for the selected Linux PC.
4. **Network server:** the repository currently uses UG65 embedded network
   servers and a Mosquitto broker on the application host. ChirpStack and a
   separate edge broker are not deployed by the current Compose configuration;
   edge-to-central buffering/replay is not implemented either.
5. **Sensor support:** migration `0003_sensor_inventory.sql` supports all three
   models and stores the CSV quantities (12/4/3) separately from registrations.
   AM107 climate, PIR activity, light, TVOC, and pressure are decoded/stored;
   energy per occupied hour and ventilation control still require methodology
   and integration work. PIR activity is not a head count or occupied flag.
6. **Buildings:** migration 0003 activates KEH, EOJ, ARK, and SiS. The old Library
   record is archived from discovery while preserving its devices and history.
   Real DevEUIs and room placements still need registering; none are in the CSV.
7. **Displays:** preserve the source description until the exact TV SKU and
   size are confirmed. Verify the served webpage, data refresh, and automatic
   startup using the Samsung screens' built-in URL feature before installation.

See [`../technical-setup.md`](../technical-setup.md) and
[`../docs/signage-setup.md`](../docs/signage-setup.md) for the deployment and screen setup.
See [`../docs/sensor-registration.md`](../docs/sensor-registration.md) for device registration.
