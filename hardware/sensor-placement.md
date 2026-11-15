# Sensor placement

Updated plan: 12 AM103 inventory units, 4 AM107 sensors, and 3 CT305 current
clamps. Air-quality coverage spans KEH, EOJ, ARK, and SiS. See
[`README.md`](README.md) for the imported inventory and unresolved counts.

## AM103 — indoor air quality

Place in high-use rooms so the dashboard reflects where people actually are:

- Lecture halls / teaching rooms
- Reading rooms
- Common areas / group-study zones

Mount on an interior wall at ~1.5 m, away from:

- direct sunlight and radiators (skews temperature)
- doors/windows (drafts skew humidity and CO₂)
- air intakes/exhausts directly above the unit

Allocate the active units across KEH, EOJ, ARK, and SiS after room selection
and coverage checks. The CSV says 10 active + 3 spares but lists only 12 units;
10 active would leave two spares. Resolve this before final placement.

## AM107 — large auditoriums (4 planned)

The updated inventory assigns four AM107 units to large auditoriums for
occupancy/light alongside environmental monitoring. Record room/building and
validate the measurement position on site. AM107 telemetry is decoded/stored
and its climate readings contribute to air-quality summaries. PIR activity
is kept as a numeric count; occupancy-based energy calculations remain future work.

## CT305 — electricity (1 per building)

- One clamp set per major building (KEH, EOJ, ARK), on the **main distribution panel**.
- Requires **Driftsenheten access approval** (follow-up email sent — see
  `docs/driftsenheten-dialog.md`).
- Mount the 3 clamps on the three incoming phases; confirm orientation so the
  readings are positive.

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
