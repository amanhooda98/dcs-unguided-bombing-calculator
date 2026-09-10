# DCS Unguided Bombing Calculator

[![Validate](https://github.com/amanhooda98/dcs-unguided-bombing-calculator/actions/workflows/validate.yml/badge.svg)](https://github.com/amanhooda98/dcs-unguided-bombing-calculator/actions/workflows/validate.yml)

A browser-based, simulator-oriented trajectory calculator for unguided bombs in DCS World. The project uses recorded DCS telemetry to fit an empirical, Mach-dependent drag model and then predicts a bomb's trajectory from a user-defined release state.

> **Scope:** This is a DCS World simulation tool, not a real-world weapons calculator. Its accuracy depends on the quality of the telemetry, the calibration envelope, the atmosphere and wind assumptions, and the release inputs.

## Live calculator

Open the [GitHub Pages calculator](https://amanhooda98.github.io/dcs-unguided-bombing-calculator/), select a weapon profile, enter the release and atmospheric conditions, and choose **Generate Firing Solution**.

## What the project does

1. Reads recorded bomb-flight telemetry from `data/raw/bomb_flight_telemetry.csv`.
2. Groups samples by individual drop and sorts them by time.
3. Smooths measured velocity and differentiates it to estimate acceleration.
4. Removes gravity from the vertical acceleration and infers aerodynamic drag.
5. Converts the inferred drag into an empirical `Kd(M)` lookup table for each weapon.
6. Loads the generated table in the browser.
7. Integrates a three-degree-of-freedom point-mass trajectory using gravity, wind, atmospheric density, and Mach-dependent drag.
8. Reports forward range, cross-track drift, time of flight, impact velocity, impact Mach, and a pilot-style steering brief.

```text
DCS telemetry CSV
      ↓
Clean and group individual drops
      ↓
Smooth velocity → differentiate → remove gravity
      ↓
Estimate drag factor Kd at each Mach sample
      ↓
Bin and interpolate Kd(M) → weapon database
      ↓
Browser loads generated database
      ↓
Create release state and wind profile
      ↓
Integrate trajectory with RK4, Δt = 0.01 s
      ↓
Resolve final position into range and cross-track drift
```

## Model assumptions

The calculator is a **3-DoF point-mass model**. It tracks only position and translational velocity along the DCS world axes. It does not model attitude, lift, fin forces, spin, tumbling, fuze behaviour, terrain collision, or a weapon-specific release impulse.

The model assumes that the bomb is acted on by:

- Gravity.
- Aerodynamic drag opposite the relative airflow.
- A user-provided horizontal wind profile.
- An idealized atmosphere whose temperature, pressure, density, and speed of sound depend on altitude.

## DCS coordinate system and telemetry

The repository uses the DCS world Cartesian convention:

- `x`: north, in metres.
- `y`: up/altitude, in metres.
- `z`: east, in metres.
- Velocity components are in metres per second.
- Time is in seconds.

The telemetry fields used by the calibration process are:

| Model quantity | CSV field | Meaning |
|---|---|---|
| `t` | `Time_s` or `Time` | Seconds since release |
| `x` | `PosX` | North position/displacement, m |
| `y` | `PosY_Alt` | Altitude, m |
| `z` | `PosZ` | East position/displacement, m |
| `vx` | `VelX` | North velocity, m/s |
| `vy` | `VelY_Vert` or `VelY` | Vertical velocity, m/s |
| `vz` | `VelZ` | East velocity, m/s |
| weapon | `Weapon_Name` or `Weapon` | Weapon identifier |
| drop | `DropID` | Individual bomb release |

Separators such as `--- NEW DROP ---` and repeated headers are ignored. Keeping drops separate is essential: a derivative must never connect the end of one bomb release to the beginning of another.

## 1. Calibrating drag from DCS telemetry

### 1.1 Smooth the measured velocity

Frame-level simulator data contains numerical noise. For each drop, the calibration script applies a third-order Savitzky–Golay filter to each velocity component:

$$
\tilde v_x=S(v_x),\qquad \tilde v_y=S(v_y),\qquad \tilde v_z=S(v_z)
$$

The smoothed velocity is used for differentiation; it is not intended to change the underlying physical trajectory.

### 1.2 Differentiate velocity

For adjacent samples:

$$
\Delta t=t_i-t_{i-1}
$$

$$
 a_x=\frac{\tilde v_{x,i}-\tilde v_{x,i-1}}{\Delta t},\qquad
 a_y=\frac{\tilde v_{y,i}-\tilde v_{y,i-1}}{\Delta t},\qquad
 a_z=\frac{\tilde v_{z,i}-\tilde v_{z,i-1}}{\Delta t}
$$

The measured acceleration contains both gravity and aerodynamic drag. Because positive `y` is upward, gravity is `-g`; therefore the drag-only vertical component is:

$$
 a_{y,drag}=a_y+g
$$

with:

$$
 g=9.81\ \mathrm{m/s^2}
$$

The inferred drag acceleration magnitude is:

$$
 a_D=\sqrt{a_x^2+a_{y,drag}^2+a_z^2}
$$

### 1.3 Derive the empirical drag factor

The conventional drag force is:

$$
 F_D=\frac12\rho V^2 C_D A
$$

Using Newton's second law, `F = ma`:

$$
 a_D=\frac{F_D}{m}=\frac{C_DA}{2m}\rho V^2
$$

The telemetry does not independently provide bomb mass `m`, reference area `A`, or aerodynamic coefficient `CD`. The project therefore combines them into one fitted quantity:

$$
\boxed{K_d(M)=\frac{C_D(M)A}{2m}}
$$

The calibration equation becomes:

$$
 a_D=K_d(M)\rho V^2
$$

and each valid telemetry sample produces:

$$
\boxed{K_d=\frac{a_D}{\rho V^2}}
$$

`Kd` is **not** the dimensionless coefficient `CD`. It is an empirical area-to-mass drag factor whose value varies with Mach number and represents the weapon's observed drag response in DCS.

### Worked substitution

For an illustrative sample:

- Drag acceleration: `aD = 18 m/s²`
- Air density: `ρ = 0.90 kg/m³`
- Speed: `V = 250 m/s`

$$
K_d=\frac{18}{0.90\times250^2}
$$

$$
K_d=\frac{18}{56,250}=0.00032\ \mathrm{m^2/kg}
$$

This is an example of the arithmetic. The actual calibration uses values calculated from every valid telemetry row.

Samples with invalid values or total speed below `50 m/s` are discarded because dividing by `V²` becomes unstable at low speed.

## 2. Atmosphere and Mach number

The calibration and flight model use an ISA-style atmosphere. The reference constants are:

| Constant | Value |
|---|---:|
| Sea-level temperature, `T0` | `288.15 K` for calibration; user-entered °C converted to K in the browser |
| Sea-level pressure, `p0` | `101325 Pa` |
| Specific gas constant, `R` | `287.05 J/(kg·K)` |
| Gravity, `g` | `9.81 m/s²` |
| Lapse rate, `L` | `0.0065 K/m` |
| Ratio of specific heats, `γ` | `1.4` |

Below 11 km, temperature is:

$$
T(h)=T_0-Lh
$$

Pressure is:

$$
 p(h)=p_0\left(1-\frac{Lh}{T_0}\right)^{g/(RL)}
$$

Density follows from the ideal-gas relationship:

$$
\rho(h)=\frac{p(h)}{RT(h)}
$$

The local speed of sound is:

$$
 a(h)=\sqrt{\gamma RT(h)}
$$

Mach number is:

$$
 M=\frac{V}{a(h)}
$$

Mach is used as the lookup variable because drag changes with compressibility, particularly near the transonic region. The calibration script bins samples by Mach and stores the mean `Kd` for each bin. The browser linearly interpolates between adjacent lookup-table points.

## 3. Release state and wind

All user inputs are converted to SI units before integration:

$$
V_{m/s}=\frac{V_{km/h}}{3.6}=V_{kt}\times0.514444
$$

For initial speed `V0`, heading `ψ`, and the calculator's pitch/dive input `θ`, the initial velocity is resolved into DCS axes:

$$
 v_x=V_0\cos(-\theta)\sin\psi
$$

$$
 v_y=V_0\sin(-\theta)
$$

$$
 v_z=V_0\cos(-\theta)\cos\psi
$$

Angles are converted from degrees to radians. The negative pitch sign is intentional: it converts the screen input convention into the DCS vertical-velocity convention.

Each wind layer is converted from speed and direction into horizontal components:

$$
 w_x=W\sin\phi,\qquad w_z=W\cos\phi
$$

The four layers are sorted by altitude. The calculator uses linear interpolation between the upper layers, logarithmic interpolation between 500 m and 10 m, and a linear reduction toward zero below 10 m. This is an approximation of the near-surface wind profile, not a full atmospheric boundary-layer model.

## 4. Trajectory equations

At every integration step, the solver obtains the wind at the bomb's current altitude and subtracts it from the bomb's ground/world velocity:

$$
\mathbf v_{rel}=\mathbf v-\mathbf w
$$

$$
V_{rel}=\sqrt{(v_x-w_x)^2+v_y^2+(v_z-w_z)^2}
$$

The solver then calculates local temperature, density, speed of sound, Mach, and interpolated `Kd`:

$$
 a_D=K_d(M)\rho V_{rel}^2
$$

Drag acts opposite the relative-airflow vector. The acceleration is:

$$
\boxed{\mathbf a=-a_D\frac{\mathbf v_{rel}}{V_{rel}}+(0,-g,0)}
$$

Component form:

$$
 a_x=-a_D\frac{v_x-w_x}{V_{rel}}
$$

$$
 a_y=-a_D\frac{v_y}{V_{rel}}-g
$$

$$
 a_z=-a_D\frac{v_z-w_z}{V_{rel}}
$$

This is why wind is not simply added as a fixed sideways distance: wind changes the relative airflow, which changes both the magnitude and direction of drag throughout the flight.

## 5. Numerical integration: classical RK4

The state vector is:

$$
\mathbf s=(x,y,z,v_x,v_y,v_z)
$$

The equations of motion can be written as:

$$
\dot x=v_x,\quad \dot y=v_y,\quad \dot z=v_z
$$

$$
\dot v_x=a_x,\quad \dot v_y=a_y,\quad \dot v_z=a_z
$$

The browser uses classical fourth-order Runge–Kutta with a fixed step of:

$$
\Delta t=0.01\ \mathrm{s}
$$

For `s' = f(t,s)`, one RK4 step is:

$$
 k_1=f(t,s)
$$

$$
 k_2=f\left(t+\frac{\Delta t}{2},s+\frac{k_1\Delta t}{2}\right)
$$

$$
 k_3=f\left(t+\frac{\Delta t}{2},s+\frac{k_2\Delta t}{2}\right)
$$

$$
 k_4=f(t+\Delta t,s+k_3\Delta t)
$$

$$
\boxed{s_{next}=s+\frac{\Delta t}{6}(k_1+2k_2+2k_3+k_4)}
$$

The implementation evaluates acceleration at the four intermediate positions and velocities before applying the weighted update. This is more accurate and stable for this changing-drag problem than a single Euler step.

### One-step substitution

Suppose one component currently has:

- `vx = 200 m/s`
- `ax = -4 m/s²`
- `Δt = 0.01 s`

The first RK4 position slope is:

$$
 k_{1,x}=v_x=200
$$

The first half-step position estimate is:

$$
 x_2=x+\frac{200\times0.01}{2}=x+1\ \mathrm{m}
$$

The solver performs the same calculation for all six state variables, recalculates acceleration at each intermediate state, and then applies the RK4 weighted average.

Integration stops when the bomb reaches the target elevation (`y <= target elevation`) or after 120 seconds.

## 6. Impact point and pilot outputs

At the end of integration, the final horizontal displacement is:

$$
D=\sqrt{x^2+z^2}
$$

The angular difference between the displacement vector and the entered heading is:

$$
\Delta\psi=\operatorname{atan2}(x,z)-\psi
$$

The calculator resolves the displacement into forward range and cross-track drift:

$$
R_f=D\cos\Delta\psi
$$

$$
D_c=D\sin\Delta\psi
$$

Positive cross-track displacement is reported as right (`R`); negative displacement is reported as left (`L`). The pilot correction reverses this sign: if the bomb lands right of the target line, the aircraft must offset left, and vice versa.

The displayed outputs are:

- **Forward range:** distance to travel along the intended heading before release.
- **Cross-track drift:** lateral displacement caused by the release geometry and wind.
- **Time of flight:** simulated time until target elevation is reached.
- **Impact velocity:** final speed and Mach number.
- **DIS:** forward release distance for the GNS-style brief.
- **OBS:** target course/heading.
- **XTK:** cross-track correction.

The target is treated as an altitude crossing, not an intersection with a terrain mesh.

## 7. Dispersion estimate

For each calibrated drop, the calibration script calculates range and cross-track displacement relative to the initial horizontal velocity. Drops are grouped by rounded initial speed. When a group contains multiple drops, the script estimates standard deviations and normalizes them by mean travel distance.

The resulting empirical values are stored as `cep50_ratio` and `cep90_ratio` and are used to display a rough dispersion footprint.

This is not a formal weapon CEP study. It assumes the recorded dispersion is representative of the future release scenario and does not independently model uncertainty in altitude, speed, wind, heading, or pilot input.

## 8. Measured data, fitted values, and assumptions

| Quantity | Source |
|---|---|
| Position, velocity, and time | DCS telemetry |
| Weapon identity and drop grouping | Telemetry fields and drop separators |
| Acceleration | Smoothed velocity differentiated over time |
| Gravity | Fixed `9.81 m/s²` constant |
| Temperature, pressure, and density | Atmospheric equations |
| Speed of sound and Mach | Atmospheric temperature and gas model |
| `Kd(M)` | Empirical fit from DCS telemetry |
| Release altitude, speed, pitch, and heading | User input |
| Wind profile | Four user-entered layers |
| Integration | Classical RK4, `0.01 s` step |
| Bomb mass, reference area, and `CD` separately | Not available; absorbed into `Kd` |

### Limitations

- Calibration currently uses recorded world/ground velocity directly; it does not explicitly subtract calibration wind before fitting `Kd`.
- Strong calibration winds may therefore be partially absorbed into the fitted drag response.
- The atmosphere is idealized and does not include humidity, weather, or map-specific conditions.
- Lookup-table values are clamped at the first and last calibrated Mach points. The UI warns when the simulated trajectory leaves that envelope.
- The target is an altitude crossing rather than terrain collision.
- The model is deterministic and does not randomly sample release errors.
- The result is only as reliable as the calibration data and the similarity between the calibration and planned release conditions.

## Calibration and development

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

Install dependencies:

```bash
uv sync
```

Regenerate the weapon database:

```bash
uv run python calibration/calibrate_weapon_drag.py
```

Run tests:

```bash
uv run python -m unittest discover --start-directory tests --pattern 'test_*.py'
```

Validate that calibration produces reproducible generated artifacts:

```bash
uv run python calibration/calibrate_weapon_drag.py
git diff --exit-code -- data/processed/weapon_drag_database.json docs/weapon_drag_database.js
```

The calibration script writes:

- `data/processed/weapon_drag_database.json`
- `docs/weapon_drag_database.js`

The browser application is client-side and requires `docs/weapon_drag_database.js` to remain beside `docs/index.html`.

## Repository layout

```text
.
├── calibration/
│   └── calibrate_weapon_drag.py
├── data/
│   ├── raw/bomb_flight_telemetry.csv
│   └── processed/weapon_drag_database.json
├── docs/
│   ├── index.html
│   └── weapon_drag_database.js
├── tests/test_artifacts.py
├── .github/workflows/validate.yml
├── pyproject.toml
├── uv.lock
└── README.md
```

## License and contributions

Contributions that improve telemetry quality, calibration validation, numerical stability, documentation, or test coverage are welcome through pull requests.
