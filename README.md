# DCS Unguided Bombing Calculator

[![Validate](https://github.com/amanhooda98/dcs-unguided-bombing-calculator/actions/workflows/validate.yml/badge.svg)](https://github.com/amanhooda98/dcs-unguided-bombing-calculator/actions/workflows/validate.yml)
[![Live Calculator](https://img.shields.io/badge/live-calculator-2ea44f?logo=github)](https://amanhooda98.github.io/dcs-unguided-bombing-calculator/)

Calibration pipeline and standalone targeting computer for unguided air-to-ground weapons in DCS World.

## What it does

1. `data/raw/bomb_flight_telemetry.csv` contains recorded bomb trajectories exported from DCS World.
2. `calibration/calibrate_weapon_drag.py` groups telemetry into individual drops, smooths velocity with a Savitzky-Golay filter, differentiates each drop, removes gravity from the vertical acceleration, and estimates Mach-dependent drag (`Kd`).
3. The script bins each weapon's drag values by Mach number, updates `data/processed/weapon_drag_database.json`, and emits the browser-ready `docs/weapon_drag_database.js` database.
4. `docs/index.html` loads that database and integrates a three-degree-of-freedom point-mass trajectory at 10 ms steps. It accounts for relative air velocity, ISA-style density and speed of sound, four wind layers, gravity, and interpolated weapon drag coefficients.
5. The calculator reports forward release range, crosswind drift, time of flight, impact velocity, and a GNS 430-style OBS/XTK execution brief. It warns when the simulated Mach range exceeds calibrated telemetry.

## Science and 3-DoF point-mass model

The calculator treats the bomb as a point mass with three translational degrees of freedom: position and velocity along the DCS `x`, `y`, and `z` axes. It does not simulate bomb attitude, fin forces, lift, spin, or rotation. The bomb is affected by gravity and aerodynamic drag, while the aircraft's release state and the atmosphere determine its initial conditions.

### 1. DCS telemetry inputs

Each telemetry row supplies one measured state of the bomb during a drop:

| Model value | DCS CSV column | Meaning |
| --- | --- | --- |
| $t$ | `Time_s` / `Time` | Time since the drop began, in seconds |
| $x$ | `PosX` | DCS position on the first horizontal axis, in metres |
| $y$ | `PosY_Alt` | DCS altitude, in metres |
| $z$ | `PosZ` | DCS position on the second horizontal axis, in metres |
| $v_x$ | `VelX` | Velocity along `x`, in m/s |
| $v_y$ | `VelY_Vert` / `VelY` | Vertical velocity along `y`, in m/s |
| $v_z$ | `VelZ` | Velocity along `z`, in m/s |
| weapon | `Weapon_Name` / `Weapon` | Weapon profile used to group calibration data |
| drop | separator or `DropID` | Individual release used to prevent derivatives crossing drop boundaries |

The legacy eight-column CSV in this repository has no `DropID`. The calibration script increments an internal drop number whenever it sees `--- NEW DROP ---`. The newer nine-column format can provide `DropID` directly.

The telemetry provides position and velocity; it does not directly provide mass, reference area, drag coefficient, air density, or speed of sound. Those quantities are supplied by the atmospheric model or absorbed into the empirical drag factor described below.

### 2. Extracting aerodynamic drag from DCS data

Raw simulator samples contain frame-to-frame noise. For each drop, the script first applies a Savitzky-Golay filter to each velocity component, producing $v_{x,s}$, $v_{y,s}$, and $v_{z,s}$. It then estimates acceleration from adjacent samples:

$$
a_x = \frac{v_{x,s}(t_i)-v_{x,s}(t_{i-1})}{t_i-t_{i-1}},\quad
a_y = \frac{v_{y,s}(t_i)-v_{y,s}(t_{i-1})}{t_i-t_{i-1}},\quad
a_z = \frac{v_{z,s}(t_i)-v_{z,s}(t_{i-1})}{t_i-t_{i-1}}
$$

The smoothed total speed is:

$$
V = \sqrt{v_{x,s}^2+v_{y,s}^2+v_{z,s}^2}
$$

The measured vertical acceleration includes gravity. With the repository's positive-downward/altitude convention, the script removes gravity from the acceleration estimate by calculating:

$$
a_{y,drag}=a_y+g
$$

where $g=9.81\ \mathrm{m/s^2}$. The magnitude attributed to drag is then:

$$
a_{drag}=\sqrt{a_x^2+a_{y,drag}^2+a_z^2}
$$

The usual drag equation is:

$$
F_D=\frac{1}{2}\rho V^2 C_D A
$$

and, after dividing by bomb mass $m$:

$$
a_D=\frac{C_D A}{2m}\rho V^2
$$

This project combines the unknown weapon geometry, mass, and drag coefficient into one empirical ballistic factor:

$$
a_D=K_d(M)\rho V^2
$$

Therefore each valid telemetry sample produces:

$$
K_d=\frac{a_{drag}}{\rho V^2}
$$

`Kd` is not the dimensionless aerodynamic $C_D$ by itself. It represents the complete drag response per unit mass for the weapon as observed in DCS. The script discards invalid values and samples below 50 m/s because division by $V^2$ becomes unstable near impact or near-zero speed.

### 3. Atmosphere and Mach number

The calibration script uses a standard sea-level reference atmosphere: $T_0=288.15\ \mathrm{K}$, $p_0=101325\ \mathrm{Pa}$, gas constant $R=287.05\ \mathrm{J/(kg\cdot K)}$, and lapse rate $L=0.0065\ \mathrm{K/m}$. At altitude $h$:

$$
T(h)=T_0-Lh
$$

$$
p(h)=p_0\left(1-\frac{Lh}{T_0}\right)^{g/(RL)}
$$

$$
\rho(h)=\frac{p(h)}{R T(h)}
$$

The local speed of sound is calculated using the ratio of specific heats $\gamma=1.4$:

$$
a(h)=\sqrt{\gamma R T(h)}
$$

Mach number is:

$$
M=\frac{V}{a(h)}
$$

Mach is used instead of raw speed because compressibility and transonic shock effects make a bomb's drag change significantly around Mach 1. The script groups samples into Mach bins of width 0.02 and averages their $K_d$ values. The result is stored in `data/processed/weapon_drag_database.json` and copied into the browser-ready JavaScript file.

### 4. Release state used by the calculator

The browser calculator does not replay a telemetry row as the release state. It takes the pilot's planned release values from the form:

| Calculator input | Model value | Unit/conversion |
| --- | --- | --- |
| Release Altitude | initial $y$ | metres MSL |
| True Airspeed | initial speed magnitude | km/h converted to m/s by dividing by 3.6 |
| Pitch / Dive Angle | initial flight-path angle | degrees converted to radians |
| Target Attack Heading | horizontal direction | degrees converted to radians |
| Target Elevation | stopping altitude | metres MSL |
| Base Temperature | $T_0$ for the flight model | degrees Celsius converted to Kelvin |
| Four wind rows | wind-layer speeds and directions | m/s and degrees |
| Selected weapon | $K_d(M)$ look-up table | loaded from `docs/weapon_drag_database.js` |

The initial velocity is resolved into the DCS axes:

$$
v_x=V_0\cos(-\theta)\sin(\psi),\quad
v_y=V_0\sin(-\theta),\quad
v_z=V_0\cos(-\theta)\cos(\psi)
$$

where $V_0$ is the entered true airspeed, $\theta$ is pitch/dive angle, and $\psi$ is heading. The negative sign follows the calculator's screen convention for pitch and vertical `y` velocity.

### 5. Wind-relative drag and numerical integration

The four entered wind directions are converted to horizontal components:

$$
w_x=W\sin(\phi),\qquad w_z=W\cos(\phi)
$$

The calculator interpolates between the 8000 m, 2000 m, 500 m, and 10 m layers. Between 500 m and 10 m it uses a logarithmic boundary-layer profile; below 10 m it linearly reduces wind toward zero. At every 0.01-second step, drag uses air-relative velocity:

$$
v_{rel,x}=v_x-w_x,\quad v_{rel,y}=v_y,\quad v_{rel,z}=v_z-w_z
$$

$$
V_{rel}=\sqrt{v_{rel,x}^2+v_{rel,y}^2+v_{rel,z}^2}
$$

The calculator recomputes temperature, pressure, density, speed of sound, Mach, and interpolated $K_d$ at the bomb's current altitude and relative speed. It then calculates:

$$
a_{drag}=K_d\rho V_{rel}^2
$$

and applies drag opposite the relative-air-velocity vector:

$$
v_x\leftarrow v_x-a_{drag}\frac{v_{rel,x}}{V_{rel}}\Delta t
$$

$$
v_y\leftarrow v_y-\left(a_{drag}\frac{v_{rel,y}}{V_{rel}}+g\right)\Delta t
$$

$$
v_z\leftarrow v_z-a_{drag}\frac{v_{rel,z}}{V_{rel}}\Delta t
$$

Position is advanced using the updated velocity:

$$
x\leftarrow x+v_x\Delta t,\quad
y\leftarrow y+v_y\Delta t,\quad
z\leftarrow z+v_z\Delta t
$$

The loop ends when $y$ reaches target elevation or after 120 seconds. The final horizontal displacement is converted into forward range and crosswind drift relative to the entered heading. The calculator also reports time of flight, impact speed, impact Mach, and whether any part of the trajectory went outside the calibrated Mach range.

### 6. What is measured versus assumed

| Value | Origin in this project |
| --- | --- |
| Position, velocity, time | Directly from DCS telemetry during calibration |
| Weapon identity and drop grouping | DCS telemetry fields or drop separators |
| Smoothed acceleration | Derived from telemetry velocity and time |
| Gravity $g$ | Fixed model constant: 9.81 m/s² |
| Temperature, pressure, density | Derived atmospheric model |
| Speed of sound and Mach | Derived from atmospheric temperature and speed |
| $K_d(M)$ | Empirically derived from DCS telemetry, then binned by Mach |
| Release altitude, speed, pitch, heading | User-entered planned aircraft state |
| Wind profile | User-entered four-layer approximation |
| Time step | Fixed numerical setting: 0.01 s |
| Bomb mass, area, and $C_D$ | Not separately available; absorbed into $K_d$ |

This distinction is important: the DCS data calibrates the weapon's observed drag response, but the calculator still supplies the release scenario and environmental assumptions. Calibration data should ideally be collected across the intended speed and altitude envelope. The current calibration path also does not subtract wind from telemetry before estimating $K_d$, so strong calibration winds can be partially absorbed into the fitted drag values.

## Run the calibration pipeline

From the repository root, with Python 3.11 or newer:

```bash
python -m pip install -e .
python calibration/calibrate_weapon_drag.py
```

The command overwrites `data/processed/weapon_drag_database.json` and `docs/weapon_drag_database.js` with the latest LUTs. Paths are resolved relative to the script, so the command can be run from any working directory.

## Run the targeting computer

Open `docs/index.html` in a browser, or use the [live GitHub Pages calculator](https://amanhooda98.github.io/dcs-unguided-bombing-calculator/). It is a zero-dependency client-side application; `docs/weapon_drag_database.js` must remain beside the HTML file.

## Repository layout

```text
.
├── calibration/
│   └── calibrate_weapon_drag.py       # Telemetry cleaning and drag-LUT generation
├── data/
│   ├── raw/bomb_flight_telemetry.csv  # DCS-exported flight samples
│   └── processed/weapon_drag_database.json
├── docs/
│   ├── index.html                      # GitHub Pages entry point
│   └── weapon_drag_database.js        # Generated browser data
├── .github/workflows/validate.yml
├── pyproject.toml
└── README.md
```

## Repository contents

- `data/raw/bomb_flight_telemetry.csv`: raw DCS trajectory telemetry.
- `calibration/calibrate_weapon_drag.py`: aerodynamic extraction and LUT generator.
- `data/processed/weapon_drag_database.json`: persistent human-readable weapon database.
- `docs/weapon_drag_database.js`: generated JavaScript database consumed by the calculator.
- `docs/index.html`: responsive targeting interface and GitHub Pages entry point.