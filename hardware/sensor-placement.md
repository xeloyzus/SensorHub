# Sensor placement

Current plan: 12 AM103 sensors across KEH, EOJ, ARK, and SiS. AM107 and CT305
are phased out of the active deployment; their source inventory rows remain
in [`hardware.csv`](hardware.csv) for audit.

## AM103 — indoor air quality

Place in high-use rooms so the dashboard reflects where people actually are:

- Lecture halls / teaching rooms
- Reading rooms
- Common areas / group-study zones

Mount on an interior wall at ~1.5 m, away from:

- direct sunlight and radiators (skews temperature)
- doors/windows (drafts skew humidity and CO₂)
- air intakes/exhausts directly above the unit

Allocate all 12 active units across KEH, EOJ, ARK, and SiS after room selection
and coverage checks. This supersedes the CSV note that says 10 active + 3 spares.

## Phased-out models

AM107 and CT305 are not part of the active deployment. Legacy device records,
decoding, and readings remain supported for data compatibility.

## Gateway (UG65) — 1 per major building

- Central mid-floor/stairwell core, **not** the roof: a central position gives
  a better signal path to all floors and avoids weather exposure.
- Position for an unobstructed path to the sensors, high up in the stairwell.
- Install in KEH, EOJ, and ARK; measure coverage in all target rooms, including
  SiS. Treat overlapping coverage as a placement goal until tested on site.

## Signage screens — 1 per major building

- Three TVs with wall mounts, in KEH, EOJ, and ARK auditoriums/lobbies.
- Configure Samsung's built-in URL feature to open `https://<DOMAIN>/` from
  the Linux server; see [`../docs/signage-setup.md`](../docs/signage-setup.md).

The active database registry covers KEH, EOJ, ARK, and SiS. Migration 0003
preserves existing Library readings under the original archived building ID.
Register each real sensor's DevEUI and room using
[`../docs/sensor-registration.md`](../docs/sensor-registration.md).
