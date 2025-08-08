import pandas as pd
from datetime import datetime, timedelta
import time
import os
import zipfile

# ---- CONFIG ----
ZIP_PATH = "pump_package.zip"  # zip file containing the CSV and other files
CSV_NAME_IN_ZIP = "pump_schedule.csv"  # name of the CSV inside the zip
SIM_START_DATETIME = datetime.now()
REFRESH_INTERVAL = 1  # seconds

# ---- LOAD CSV FROM ZIP ----
with zipfile.ZipFile(ZIP_PATH) as archive:
    with archive.open(CSV_NAME_IN_ZIP) as csvfile:
        df = pd.read_csv(csvfile)

# ---- PREPARE DATA ----
df["Start Time"] = pd.to_timedelta(df["Start Time"])
df.sort_values(by=["Pump", "Start Time"], inplace=True)

# ---- GROUP BY PUMPS ----
pump_groups = df.groupby("Pump")

# ---- FUNCTION TO GET CURRENT PHASE ----
def get_pump_phase(pump_id, schedule, now):
    base_start = SIM_START_DATETIME
    for _, row in schedule.iterrows():
        start = base_start + row["Start Time"]
        end = start + timedelta(seconds=row["Duration (s)"])
        if start <= now < end:
            remaining = end - now
            return {
                "phase": int(row["Step"]),
                "desc": row["Description"],
                "time_left": remaining,
            }
    return None

# ---- MAIN LOOP ----
try:
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        now = datetime.now()
        print(f"Current Time: {now:%Y-%m-%d %H:%M:%S}\n")

        for pump_id, schedule in pump_groups:
            phase_info = get_pump_phase(pump_id, schedule, now)
            if phase_info:
                print(f"Pump {pump_id}: Phase {phase_info['phase']} - {phase_info['desc']}")
                print(f"  Time left: {str(phase_info['time_left']).split('.')[0]}")
            else:
                print(f"Pump {pump_id}: All phases completed")

        time.sleep(REFRESH_INTERVAL)

except KeyboardInterrupt:
    print("\nTimer stopped.")