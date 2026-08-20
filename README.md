# DCS Point-Mass Targeting Engine

Calibration pipeline and standalone targeting computer for unguided air-to-ground weapons in DCS World.

## What it does

1. `Bomb_Telemetry.csv` contains recorded bomb trajectories exported from DCS World.
2. `3d_space_based_curve_plot.py` groups telemetry into individual drops, supports both legacy and `DropID` CSV layouts, smooths velocity with a Savitzky-Golay filter, differentiates each drop, removes gravity from the vertical acceleration, and estimates Mach-dependent drag (`Kd`).
3. The script bins each weapon's drag values by Mach number, updates `weapons_master.json`, and emits the browser-ready `weapons.js` database.
4. `ballastics_calculator_3d.html` loads that database and integrates a three-degree-of-freedom point-mass trajectory at 10 ms steps. It accounts for relative air velocity, ISA-style density and speed of sound, four wind layers, gravity, and interpolated weapon drag coefficients.
5. The calculator reports forward release range, crosswind drift, time of flight, impact velocity, and a GNS 430-style OBS/XTK execution brief. It warns when the simulated Mach range exceeds calibrated telemetry.

## Run the calibration pipeline

From this directory, with Python 3.11 or newer and the dependencies from the parent project's `pyproject.toml` installed:

```bash
python 3d_space_based_curve_plot.py
```

The command overwrites `weapons_master.json` and `weapons.js` with the latest LUTs. The script expects to be run from this directory.

## Run the targeting computer

Open `ballastics_calculator_3d.html` in a browser. It is a zero-dependency client-side application; `weapons.js` must remain beside the HTML file.

## Repository contents

- `Bomb_Telemetry.csv`: raw DCS trajectory telemetry.
- `3d_space_based_curve_plot.py`: aerodynamic extraction and LUT generator.
- `weapons_master.json`: persistent human-readable weapon database.
- `weapons.js`: generated JavaScript database consumed by the calculator.
- `ballastics_calculator_3d.html`: responsive targeting interface and numerical integrator.