import pandas as pd
import numpy as np
import json
from pathlib import Path
from scipy.signal import savgol_filter

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
file_path = REPOSITORY_ROOT / 'data' / 'raw' / 'bomb_flight_telemetry.csv'
master_json_path = REPOSITORY_ROOT / 'data' / 'processed' / 'weapon_drag_database.json'
js_export_path = REPOSITORY_ROOT / 'docs' / 'weapon_drag_database.js'

print("📡 Parsing DCS Telemetry Data...")

# 1. CLEAN AND LOAD THE DATA
with open(file_path, 'r') as file:
    lines = file.readlines()

clean_data = []
for line in lines:
    if '---' in line or 'Weapon_Name' in line:
        continue
    parts = line.strip().split(',')
    if len(parts) == 9:
        clean_data.append(parts)

columns = ['Weapon', 'DropID', 'Time', 'PosX', 'PosY_Alt', 'PosZ', 'VelX', 'VelY', 'VelZ']
df = pd.DataFrame(clean_data, columns=columns)

for col in columns[2:]:
    df[col] = df[col].astype(float)
df['DropID'] = df['DropID'].astype(int)

print(f"   Loaded {len(df)} rows across {df['DropID'].nunique()} individual drops.")

# 2. PER-DROP PHYSICS PROCESSING
print("⚙️ Processing Aerodynamics per-drop (ISA Atmosphere & Gravity Removal)...")
g = 9.81

def process_drop(d):
    d = d.sort_values('Time').reset_index(drop=True)
    n = len(d)
    if n < 15: return d.iloc[0:0] 

    win = min(31, n - (1 - n % 2))
    win = max(win, 5)
    if win % 2 == 0: win -= 1
        
    d['VelX_s'] = savgol_filter(d['VelX'], win, 3)
    d['VelY_s'] = savgol_filter(d['VelY'], win, 3)
    d['VelZ_s'] = savgol_filter(d['VelZ'], win, 3)

    d['dt'] = d['Time'].diff()
    d['a_X'] = d['VelX_s'].diff() / d['dt']
    d['a_Y'] = d['VelY_s'].diff() / d['dt']
    d['a_Z'] = d['VelZ_s'].diff() / d['dt']

    d['V_Total'] = np.sqrt(d['VelX_s']**2 + d['VelY_s']**2 + d['VelZ_s']**2)
    d['a_Y_drag'] = d['a_Y'] + g
    d['a_Drag_Total'] = np.sqrt(d['a_X']**2 + d['a_Y_drag']**2 + d['a_Z']**2)

    d['Temp_K'] = 288.15 - (0.0065 * d['PosY_Alt'])
    d['Pressure_Pa'] = 101325 * (1 - 0.0000225577 * d['PosY_Alt'])**5.25588
    d['Rho'] = d['Pressure_Pa'] / (287.05 * d['Temp_K'])
    d['SpeedOfSound'] = np.sqrt(1.4 * 287.05 * d['Temp_K'])
    d['Mach'] = d['V_Total'] / d['SpeedOfSound']
    d['Kd'] = d['a_Drag_Total'] / (d['Rho'] * d['V_Total']**2)
    
    return d

processed = [process_drop(g_) for _, g_ in df.groupby('DropID')]
df = pd.concat(processed, ignore_index=True).replace([np.inf, -np.inf], np.nan).dropna()
df = df[df['V_Total'] > 50]

# 3. GENERATE ADAPTIVE LUTS AND DISPERSION
print("\n==================================================")
print("📊 GENERATING DATABASE (LUT + DISPERSION)")
print("==================================================")

database = {}

unique_weapons = df['Weapon'].unique()

for raw_weapon_name in unique_weapons:
    weapon_name_clean = str(raw_weapon_name).strip()
    weapon_key = weapon_name_clean.lower().replace(" ", "_").replace("-", "_")
    w_df = df[df['Weapon'] == raw_weapon_name].copy()
    
    # --- A. ADAPTIVE VARIABLE GRID ---
    bins_sub = np.arange(0.20, 0.85, 0.02)
    bins_trans = np.arange(0.85, 1.20, 0.005) # Dense transonic peak
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
    
    # --- B. STATISTICAL DISPERSION FOOTPRINT ---
    drop_stats = []
    for drop_id, group in w_df.groupby('DropID'):
        first, last = group.iloc[0], group.iloc[-1]
        v0_mag = np.sqrt(first['VelX']**2 + first['VelZ']**2)
        dx, dz = last['PosX'] - first['PosX'], last['PosZ'] - first['PosZ']
        travel_dist = np.sqrt(dx**2 + dz**2)
        
        fwd_range = dx * (first['VelX'] / v0_mag) + dz * (first['VelZ'] / v0_mag)
        cross_track = -dx * (first['VelZ'] / v0_mag) + dz * (first['VelX'] / v0_mag)
        
        speed_group = round(np.sqrt(first['VelX']**2 + first['VelY']**2 + first['VelZ']**2), -1)
        drop_stats.append({'SpeedGroup': speed_group, 'fwd_range': fwd_range, 'cross_track': cross_track, 'dist': travel_dist})
        
    ds_df = pd.DataFrame(drop_stats)
    fwd_vars, cross_vars, ranges = [], [], []
    for _, group in ds_df.groupby('SpeedGroup'):
        if len(group) > 1:
            fwd_vars.append(group['fwd_range'].var())
            cross_vars.append(group['cross_track'].var())
            ranges.append(group['dist'].mean())
            
    if ranges:
        std_fwd_ratio = np.mean([np.sqrt(v) / r for v, r in zip(fwd_vars, ranges)])
        std_cross_ratio = np.mean([np.sqrt(v) / r for v, r in zip(cross_vars, ranges)])
        cep50_ratio = (0.562 * std_fwd_ratio) + (0.615 * std_cross_ratio)
    else:
        cep50_ratio = 0.0041 # Fallback
        
    cep90_ratio = cep50_ratio * 2.146 
    
    database[weapon_key] = {
        "name": weapon_name_clean,
        "dragTable": drag_table,
        "dispersion": { "cep50_ratio": round(cep50_ratio, 6), "cep90_ratio": round(cep90_ratio, 6) }
    }
    print(f"✅ Added {weapon_name_clean} | Data points: {len(drag_table)} | CEP90 Ratio: {cep90_ratio*100:.2f}%")

# 4. EXPORT
with open(master_json_path, 'w') as f:
    json.dump(database, f, indent=4)

with open(js_export_path, 'w') as f:
    f.write(f"// AUTO-GENERATED BY DCS TELEMETRY SCRIPT\nconst WEAPON_DATABASE = {json.dumps(database, indent=4)};\n")

print("\n==================================================")
print(f"💾 Successfully auto-generated {js_export_path}")
print("==================================================\n")