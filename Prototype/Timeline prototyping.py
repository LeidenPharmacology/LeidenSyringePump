from pathlib import Path
from typing import List, Dict
import re

def parse_ppl_phases(ppl_text: str) -> List[Dict]:
    phases = []
    current_phase = {}
    lines = ppl_text.splitlines()

    for line in lines:
        if line.startswith("PHN"):
            if current_phase:
                phases.append(current_phase)
            current_phase = {"PHN": int(line.split()[1])}
        elif line.startswith("FUN"):
            current_phase["FUN"] = line.split()[1]
        elif line.startswith("RAT"):
            parts = line.split()
            try:
                current_phase["RAT"] = float(parts[1])
                current_phase["RAT_UNIT"] = parts[2]
            except (IndexError, ValueError):
                continue
        elif line.startswith("VOL"):
            parts = line.split()
            try:
                vol_value = float(parts[1])
                current_phase["VOL"] = vol_value
            except (IndexError, ValueError):
                continue
        elif line.startswith("DIR"):
            current_phase["DIR"] = line.split()[1]

    if current_phase:
        phases.append(current_phase)

    return phases

def calculate_phase_durations(phases: List[Dict]) -> List[Dict]:
    timeline = []
    current_time = 0.0  # in minutes

    for phase in phases:
        rate_mlph = phase.get("RAT", 0)
        vol_ml = phase.get("VOL", 0)
        unit = phase.get("RAT_UNIT", "")

        if unit.upper() == "MH":  # µL/h
            rate_mlph = rate_mlph / 1000

        if rate_mlph > 0:
            duration_hr = vol_ml / rate_mlph
            duration_min = duration_hr * 60
        else:
            duration_min = 0

        phase_summary = {
            "Phase": phase.get("PHN"),
            "Function": phase.get("FUN"),
            "Direction": phase.get("DIR", ""),
            "Rate (mL/h)": round(rate_mlph, 3),
            "Volume (mL)": vol_ml,
            "Duration (min)": round(duration_min, 2),
            "Start (min)": round(current_time, 2),
            "End (min)": round(current_time + duration_min, 2)
        }
        timeline.append(phase_summary)
        current_time += duration_min

    return timeline

def print_timeline(timeline: List[Dict]):
    print("\nPump Phase Timeline:")
    print("=" * 60)
    for phase in timeline:
        print(f"Phase {phase['Phase']}: {phase['Function']} - {phase['Direction']} | "
              f"Rate: {phase['Rate (mL/h)']} mL/h | Volume: {phase['Volume (mL)']} mL")
        print(f"    Start: {phase['Start (min)']} min --> End: {phase['End (min)']} min" )
        print("-" * 60)

# Example usage:
with open("C://Users//jornb//Documents//GitHub//Serialpump//test ppl//pump_00_script.ppl") as f:
    ppl_content = f.read()
    phases = parse_ppl_phases(ppl_content)
    timeline = calculate_phase_durations(phases)
    print_timeline(timeline)
