# DCS Unguided Bombing Calculator

Calibration pipeline and standalone targeting computer for unguided air-to-ground weapons in DCS World.

## What it does

1. `bomb_flight_telemetry.csv` contains recorded bomb trajectories exported from DCS World.
2. `calibrate_weapon_drag.py` groups telemetry into individual drops, supports both legacy and `DropID` CSV layouts, smooths velocity with a Savitzky-Golay filter, differentiates each drop, removes gravity from the vertical acceleration, and estimates Mach-dependent drag (`Kd`).
3. The script bins each weapon's drag values by Mach number, updates `weapon_drag_database.json`, and emits the browser-ready `weapon_drag_database.js` database.
4. `ballistic_targeting_calculator.html` loads that database and integrates a three-degree-of-freedom point-mass trajectory at 10 ms steps. It accounts for relative air velocity, ISA-style density and speed of sound, four wind layers, gravity, and interpolated weapon drag coefficients.
5. The calculator reports forward release range, crosswind drift, time of flight, impact velocity, and a GNS 430-style OBS/XTK execution brief. It warns when the simulated Mach range exceeds calibrated telemetry.

## Run the calibration pipeline

From this directory, with Python 3.11 or newer and the dependencies from the parent project's `pyproject.toml` installed:

```bash
python calibrate_weapon_drag.py
```

The command overwrites `weapon_drag_database.json` and `weapon_drag_database.js` with the latest LUTs. The script expects to be run from this directory.

## Run the targeting computer

Open `ballistic_targeting_calculator.html` in a browser. It is a zero-dependency client-side application; `weapon_drag_database.js` must remain beside the HTML file.

## Repository contents

- `bomb_flight_telemetry.csv`: raw DCS trajectory telemetry.
- `calibrate_weapon_drag.py`: aerodynamic extraction and LUT generator.
- `weapon_drag_database.json`: persistent human-readable weapon database.
- `weapon_drag_database.js`: generated JavaScript database consumed by the calculator.
- `ballistic_targeting_calculator.html`: responsive targeting interface and numerical integrator.