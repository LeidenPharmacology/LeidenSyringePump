import streamlit as st
import json
import pandas as pd
import io
import zipfile
import re
from streamlit_autorefresh import st_autorefresh

def sanitize_filename(name):
    name = name.strip()
    name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", name)
    if not name.lower().endswith(".zip"):
        name += ".zip"
    return name[:100]

st.set_page_config(page_title="Magic carpet: NE-1000 PPL Composer", layout="wide")
st.title("Magic carpet: 📿 NE-1000 PPL Step Composer")

if "multi_ppl_steps" not in st.session_state:
    st.session_state.multi_ppl_steps = {}
if "pump_headers" not in st.session_state:
    st.session_state.pump_headers = {}
if "just_set_diameter" not in st.session_state:
    st.session_state.just_set_diameter = False

unit_map = {
    "mL/hr": "MH",
    "mL/min": "MM",
    "µL/hr": "UH",
    "µL/min": "UM",
    "mL": "ML",
    "µL": "UL"
}

pump_name_to_address = {str(i): f"{i-1:02d}" for i in range(1, 11)}

user_pump_id = st.selectbox("Pump", list(pump_name_to_address.keys()))
real_pump_addr = pump_name_to_address[user_pump_id]

current_dia = st.session_state.pump_headers.get(real_pump_addr)
if current_dia:
    st.info(f"✅ Current Diameter: {current_dia} mm")
else:
    st.warning("⚠️ No diameter set for this pump.")

if real_pump_addr not in st.session_state.multi_ppl_steps:
    st.session_state.multi_ppl_steps[real_pump_addr] = []

step_type = st.selectbox("Step Type", ["DIA", "RAT (continuous)", "RAT (volume)", "PAS", "LPS", "LOP", "BEP"])
params = []

if step_type == "DIA":
    volumeselect = st.selectbox("Volume Syringe", ["10 ml", "20 ml", "30 ml", "60 ml"])
    dia = {
        "10 ml": 15.8,
        "20 ml": 20.15,
        "30 ml": 23.1,
        "60 ml": 29.7
    }[volumeselect]

    if st.button("✅ Confirm Diameter"):
        st.session_state.pump_headers[real_pump_addr] = dia
        st.success(f"Diameter set to {dia} mm for Pump {user_pump_id}")

elif step_type == "RAT (continuous)":
    rate = st.number_input("Rate", min_value=0.01, format="%0.2f")
    unit = st.selectbox("Rate Units", list(unit_map.keys())[:4])
    direction = st.selectbox("Direction", ["INF", "WDR", "REV"])
    params = ["RAT_CONT", rate, unit, direction]

elif step_type == "RAT (volume)":
    rate = st.number_input("Rate", min_value=0.01, format="%0.2f")
    unit = st.selectbox("Rate Units", list(unit_map.keys())[:4])
    volume = st.number_input("Volume", min_value=0.01, format="%0.2f")
    direction = st.selectbox("Direction", ["INF", "WDR", "REV"])
    params = ["RAT_VOL", rate, unit, volume, direction]

elif step_type == "PAS":
    val = st.number_input("Pause for ... seconds", min_value=1, format="%d")
    params = [step_type, val]

elif step_type == "LOP":
    val = st.number_input("Loop for ... times", min_value=1, format="%d")
    params = [step_type, val]

elif step_type in ["LPS", "BEP"]:
    params = [step_type]

if step_type != "DIA" and st.button("➕ Add Step to Pump"):
    st.session_state.multi_ppl_steps[real_pump_addr].append(params)

syringe_max_volume_map = {
    15.8: 10,
    20.15: 20,
    23.1: 30,
    29.7: 60
}

sorted_pumps = sorted(st.session_state.multi_ppl_steps.items(), key=lambda x: int(x[0]))
cols = st.columns(len(sorted_pumps))

for idx, (pid, steps) in enumerate(sorted_pumps):
    if not steps:
        continue
    user_label = str(int(pid) + 1)
    with cols[idx]:
        st.subheader(f"Pump {user_label}")

        dia = st.session_state.pump_headers.get(pid)
        max_vol = syringe_max_volume_map.get(dia, None)
        assigned_vol = sum(step[3] for step in steps if step[0] == "RAT_VOL")

        if max_vol:
            percent = min(100, (assigned_vol / max_vol) * 100)
            st.caption(f"💧 Assigned Volume: **{assigned_vol:.2f} mL** / Max {max_vol} mL")
            if percent > 100:
                st.error("⛔ Over capacity!")
            elif percent >= 80 and not (percent >= 100):
                st.warning("⚠️ Near capacity")
            st.progress(min(100, int(percent)))
        else:
            st.caption(f"💧 Assigned Volume: **{assigned_vol:.2f} mL**")

        for i, step in enumerate(steps):
            step_display = f"{i+1:02d}. {' '.join(str(x) for x in step)}"
            col1, col2, col3 = st.columns([7, 1, 1])
            col1.text(step_display)
            if i > 0:
                if col2.button("\u2191", key=f"up_{pid}_{i}"):
                    steps[i-1], steps[i] = steps[i], steps[i-1]
            else:
                col2.write("")
            if col3.button("❌", key=f"del_{pid}_{i}"):
                steps.pop(i)
