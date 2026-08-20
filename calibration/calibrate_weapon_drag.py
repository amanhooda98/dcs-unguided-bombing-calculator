import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import savgol_filter

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
file_path = REPOSITORY_ROOT / 'data' / 'raw' / 'bomb_flight_telemetry.csv'

print("📡 Parsing DCS Telemetry Data...")

# 1. CLEAN AND LOAD THE DATA
# The CSV has "--- NEW DROP ---" separators and headers scattered throughout.
with open(file_path, 'r') as file:
    lines = file.readlines()

clean_data = []
for line in lines:
    if '---' in line:
        continue
    if 'Weapon_Name' in line:
        continue
    parts = line.strip().split(',')
    if len(parts) == 9:
        clean_data.append(parts)

columns = ['Weapon', 'DropID', 'Time', 'PosX', 'PosY_Alt', 'PosZ', 'VelX', 'VelY', 'VelZ']
df = pd.DataFrame(clean_data, columns=columns)

# Convert strings to floats (DropID stays as a grouping key)
for col in columns[2:]:
    df[col] = df[col].astype(float)
df['DropID'] = df['DropID'].astype(int)

print(f"   Loaded {len(df)} rows across {df['DropID'].nunique()} individual drops "
    f"(using DropID from telemetry)")

# 2. PER-DROP PHYSICS PROCESSING
# CRITICAL: every derivative below is computed *within* a single drop's own telemetry.
# Doing this on the whole concatenated file (the old approach) mixes the last frame of
# one drop with the first frame of the next at each boundary, corrupting those rows.
print("⚙️ Processing Aerodynamics per-drop (ISA Atmosphere & Gravity Removal)...")

g = 9.81

def process_drop(d):
    d = d.sort_values('Time').reset_index(drop=True)
    n = len(d)
    if n < 15:
        return d.iloc[0:0]  # too short to smooth/differentiate reliably, discard

    # Smooth velocity components before differentiating - raw frame-to-frame diff()
    # amplifies simulator/logging noise into the acceleration estimate.
    win = min(31, n - (1 - n % 2))  # largest odd window <= n
    win = max(win, 5)
    if win % 2 == 0:
        win -= 1
    d['VelX_s'] = savgol_filter(d['VelX'], win, 3)
    d['VelY_s'] = savgol_filter(d['VelY'], win, 3)
    d['VelZ_s'] = savgol_filter(d['VelZ'], win, 3)

    d['dt'] = d['Time'].diff()
    d['a_X'] = d['VelX_s'].diff() / d['dt']
    d['a_Y'] = d['VelY_s'].diff() / d['dt']
    d['a_Z'] = d['VelZ_s'].diff() / d['dt']

    # True speed (use the smoothed velocity for consistency with the derivative)
    d['V_Total'] = np.sqrt(d['VelX_s']**2 + d['VelY_s']**2 + d['VelZ_s']**2)

    # Remove gravity (9.81 m/s^2) from the vertical (Y) axis to isolate drag-only accel
    d['a_Y_drag'] = d['a_Y'] + g
    d['a_Drag_Total'] = np.sqrt(d['a_X']**2 + d['a_Y_drag']**2 + d['a_Z']**2)

    # ISA atmosphere model (15C / 101325 Pa sea-level reference)
    d['Temp_K'] = 288.15 - (0.0065 * d['PosY_Alt'])
    d['Pressure_Pa'] = 101325 * (1 - 0.0000225577 * d['PosY_Alt'])**5.25588
    d['Rho'] = d['Pressure_Pa'] / (287.05 * d['Temp_K'])

    # Local speed of sound -> Mach number. Drag coefficient is fundamentally a function
    # of Mach (compressibility), not raw velocity, so this is what we fit Kd against.
    d['SpeedOfSound'] = np.sqrt(1.4 * 287.05 * d['Temp_K'])
    d['Mach'] = d['V_Total'] / d['SpeedOfSound']

    # Kd = a_drag / (rho * V^2)   [a_drag = Kd(Mach) * rho * V^2]
    d['Kd'] = d['a_Drag_Total'] / (d['Rho'] * d['V_Total']**2)
    return d

processed = [process_drop(g_) for _, g_ in df.groupby('DropID')]
df = pd.concat(processed, ignore_index=True)

# Clean up infinite/NaN values from the frame differences
df = df.replace([np.inf, -np.inf], np.nan).dropna()
# Filter out impact anomalies / near-zero-speed noise (Kd blows up as V -> 0)
df = df[df['V_Total'] > 50]

n_drops = df['DropID'].nunique()
print(f"   Mach range in calibration data: {df['Mach'].min():.2f} - {df['Mach'].max():.2f} "
      f"({(df['Mach'] > 0.8).mean()*100:.0f}% of samples above Mach 0.8 - mostly transonic/supersonic)")

# 3 & 4. GENERATE LUTS AND UPDATE MULTIPLE WEAPONS
import json
import os

print("\n==================================================")
print("📊 GENERATING AERODYNAMIC LOOK-UP TABLES (LUT)")
print("==================================================")

master_json_path = REPOSITORY_ROOT / 'data' / 'processed' / 'weapon_drag_database.json'
js_export_path = REPOSITORY_ROOT / 'docs' / 'weapon_drag_database.js'

# Load the existing master database once
if os.path.exists(master_json_path):
    with open(master_json_path, 'r') as f:
        database = json.load(f)
else:
    database = {}

# Detect all unique weapon types inside the CSV file
unique_weapons = df['Weapon'].unique()
print(f"Detected {len(unique_weapons)} unique weapon(s) in telemetry: {', '.join(unique_weapons)}")

# Loop through each weapon type and process them separately
for raw_weapon_name in unique_weapons:
    weapon_name_clean = str(raw_weapon_name).strip()
    weapon_key = weapon_name_clean.lower().replace(" ", "_").replace("-", "_")
    
    print(f"\n⚙️ Processing {weapon_name_clean}...")
    
    # Isolate only the telemetry frames for THIS specific weapon
    w_df = df[df['Weapon'] == raw_weapon_name].copy()
    
    # ---------------------------------------------------------
    # ADAPTIVE VARIABLE GRID (MIL-STD MULTI-REGIME)
    # ---------------------------------------------------------
    bins_sub = np.arange(0.20, 0.85, 0.02)
    bins_trans = np.arange(0.85, 1.20, 0.005)
    bins_super = np.arange(1.20, 2.50, 0.02)
    
    variable_bins = np.unique(np.concatenate([bins_sub, bins_trans, bins_super]))
    
    min_mach = w_df['Mach'].min()
    max_mach = w_df['Mach'].max()
    active_bins = variable_bins[(variable_bins >= min_mach - 0.02) & (variable_bins <= max_mach + 0.02)]
    
    w_df['Mach_Bucket'] = pd.cut(w_df['Mach'], bins=active_bins)
    lut = w_df.groupby('Mach_Bucket', observed=False)['Kd'].mean().reset_index()
    lut['Mach'] = lut['Mach_Bucket'].apply(lambda x: x.mid).astype(float)
    lut = lut.dropna(subset=['Kd']).sort_values('Mach')[['Mach', 'Kd']]
    
    drag_table = [{"mach": round(row['Mach'], 3), "kd": round(row['Kd'], 6)} for index, row in lut.iterrows()]
    
    database[weapon_key] = {
        "name": weapon_name_clean,
        "dragTable": drag_table
    }
    print(f"✅ Added/Updated LUT for {weapon_key} ({len(drag_table)} data points)")

# Save master JSON and export JavaScript file
with open(master_json_path, 'w') as f:
    json.dump(database, f, indent=4)

js_content = f"// AUTO-GENERATED BY DCS TELEMETRY SCRIPT\n"
js_content += f"const WEAPON_DATABASE = {json.dumps(database, indent=4)};\n"

with open(js_export_path, 'w') as f:
    f.write(js_content)

print("\n==================================================")
print(f"💾 Successfully auto-generated {js_export_path} with {len(database)} total weapon(s)!")
print("==================================================\n")