import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter

file_path = 'Bomb_Telemetry.csv'

print("📡 Parsing DCS Telemetry Data...")

# 1. CLEAN AND LOAD THE DATA
# The CSV has "--- NEW DROP ---" and headers scattered throughout, plus (as of the
# updated logger) a DropID column. We support BOTH the new 9-column format
# (Weapon,DropID,Time,PosX,PosY,PosZ,VelX,VelY,VelZ) and legacy 8-column files
# (no DropID) by inferring a drop id from the "--- NEW DROP ---" separators instead.
with open(file_path, 'r') as file:
    lines = file.readlines()

clean_data = []
legacy_drop_id = -1
has_drop_id_col = None
for line in lines:
    if '---' in line:
        legacy_drop_id += 1
        continue
    if 'Weapon_Name' in line:
        continue
    parts = line.strip().split(',')
    if has_drop_id_col is None:
        has_drop_id_col = (len(parts) == 9)
    if has_drop_id_col and len(parts) == 9:
        clean_data.append(parts)
    elif not has_drop_id_col and len(parts) == 8:
        # legacy format: no DropID column in the file, insert the inferred one
        clean_data.append([parts[0], str(legacy_drop_id)] + parts[1:])

columns = ['Weapon', 'DropID', 'Time', 'PosX', 'PosY_Alt', 'PosZ', 'VelX', 'VelY', 'VelZ']
df = pd.DataFrame(clean_data, columns=columns)

# Convert strings to floats (DropID stays as a grouping key)
for col in columns[2:]:
    df[col] = df[col].astype(float)
df['DropID'] = df['DropID'].astype(int)

print(f"   Loaded {len(df)} rows across {df['DropID'].nunique()} individual drops "
      f"({'DropID column found' if has_drop_id_col else 'DropID inferred from --- NEW DROP --- markers'})")

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

mach_resolution = 0.02
master_json_path = "weapons_master.json"
js_export_path = "weapons.js"

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
    
    # Create Mach bins covering the exact flight range of THIS weapon
    min_mach = np.floor(w_df['Mach'].min() / mach_resolution) * mach_resolution
    max_mach = np.ceil(w_df['Mach'].max() / mach_resolution) * mach_resolution
    bins = np.arange(min_mach, max_mach + mach_resolution, mach_resolution)
    
    # Group into buckets and calculate the LUT
    w_df['Mach_Bucket'] = pd.cut(w_df['Mach'], bins=bins)
    lut = w_df.groupby('Mach_Bucket')['Kd'].mean().reset_index()
    lut['Mach'] = lut['Mach_Bucket'].apply(lambda x: x.mid).astype(float)
    lut = lut.dropna(subset=['Kd']).sort_values('Mach')[['Mach', 'Kd']]
    
    # Format the table for JavaScript
    drag_table = [{"mach": round(row['Mach'], 2), "kd": round(row['Kd'], 6)} for index, row in lut.iterrows()]
    
    # Update the database dictionary for this specific weapon
    database[weapon_key] = {
        "name": weapon_name_clean,
        "dragTable": drag_table
    }
    print(f"✅ Added/Updated LUT for {weapon_key} ({len(drag_table)} data points)")

# Save the master JSON back to the disk
with open(master_json_path, 'w') as f:
    json.dump(database, f, indent=4)

# Generate the massive JavaScript file containing all weapons
js_content = f"// AUTO-GENERATED BY DCS TELEMETRY SCRIPT\n"
js_content += f"const WEAPON_DATABASE = {json.dumps(database, indent=4)};\n"

with open(js_export_path, 'w') as f:
    f.write(js_content)

print("\n==================================================")
print(f"💾 Successfully auto-generated {js_export_path} with {len(database)} total weapon(s)!")
print("==================================================\n")