# Hardware inventory and deployment decisions

Source: [`hardware.csv`](hardware.csv), copied unchanged from the supplied
hardware CSV on 30 October 2026. Prices and product descriptions below are
from that file, not independently verified supplier specifications.

## Confirmed deployment decisions

- SensorHub runs on a dedicated PC with Linux.
- Three Samsung signage screens use their built-in internet/URL feature to
  open `https://<DOMAIN>/` directly using their integrated browser.
- The Mac Studio is used for other work and is excluded from this deployment.
- The CSV lists a GMKtec G10 for ChirpStack/MQTT. ChirpStack is now configured
  in the NanitesLab Compose stack on the dedicated Linux PC; confirm whether
  the GMKtec is that PC or is no longer needed as a separate edge node.
- Current sensor deployment decision: use 12 AM103 devices only. AM107 and
  CT305 are phased out; their source CSV entries remain unchanged for audit.

## Imported equipment

| Equipment | Quantity | Unit price (NOK) | Subtotal (NOK) | Deployment role / status |
|---|---:|---:|---:|---|
| Milesight AM103 | 12 | 2,377 | 28,524 | Active fleet: air quality across KEH, EOJ, ARK, SiS |
| GMKtec G10 Mini PC (Ryzen 5, 16GB) | 1 | 5,499 | 5,499 | Candidate Linux host for NanitesLab + ChirpStack; confirm actual host |
| Milesight CT305 | 3 | 2,259 | 6,777 | Phased out of active deployment |
| Milesight UG65 | 3 | 3,469 | 10,407 | Gateways in KEH, EOJ, ARK; measure SiS coverage on site |
| SANDISK WD Black SN7100 SSD (1TB) | 1 | 2,190 | 2,190 | CSV assigns it to the Mac Studio; project role/compatibility unresolved |
| Samsung business signage TV (CSV: `55" 4K BE65F-H`) | 3 | 5,624 | 16,872 | One display per major building; confirm exact model/size and URL player |
| Wall mount | 3 | 999 | 2,997 | One per display |
| Mac Studio | 1 | 32,999 | 32,999 | Outside SensorHub per user clarification |
| Milesight AM107 | 4 | 3,171 | 12,684 | Phased out of active deployment |
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

1. **AM103 quantity:** the deployment now uses all 12 AM103 units; this
   supersedes the imported note claiming 10 active + 3 spares.
2. **Hosting:** the user's Linux PC decision supersedes the Mac Studio hosting
   note. Confirm whether the GMKtec is that PC or a separate edge machine.
3. **SSD:** its source note still targets the Mac Studio. Confirm whether it
   belongs in SensorHub and check suitability for the selected Linux PC.
4. **Network server:** ChirpStack and its supporting services are now included
   in the NanitesLab Compose stack. UG65 gateways use Semtech UDP to the
   ChirpStack Gateway Bridge on port 1700; register each matching gateway EUI
   and EU868 radio configuration in ChirpStack. Edge-to-central buffering/replay
   is not implemented.
5. **Sensor scope:** migration `0005_am103_only_deployment.sql` sets the active
   planned inventory to 12 AM103 and phases out AM107/CT305. Their decoder and
   historical-data support remains available without deleting old records.
6. **Buildings:** migration 0003 activates KEH, EOJ, ARK, and SiS. The old Library
   record is archived from discovery while preserving its devices and history.
   Register the 12 AM103 DevEUIs and room placements; none are in the CSV.
7. **Displays:** preserve the source description until the exact TV SKU and
   size are confirmed. Verify the served webpage, data refresh, and automatic
   startup using the Samsung screens' built-in URL feature before installation.

See [`../technical-setup.md`](../technical-setup.md) and
[`../docs/signage-setup.md`](../docs/signage-setup.md) for the deployment and screen setup.
See [`../docs/sensor-registration.md`](../docs/sensor-registration.md) for device registration.
