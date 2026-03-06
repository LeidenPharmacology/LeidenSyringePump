import streamlit as st
import json
import pandas as pd
import io
import zipfile
import re


def sanitize_filename(name):
    name = name.strip()
    name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", name)
    if not name.lower().endswith(".zip"):
        name += ".zip"
    return name[:100]

st.set_page_config(page_title="NE-1000 PPL Composer", layout="wide")
st.title("📟 NE-1000 PPL Step Composer")

if "multi_ppl_steps" not in st.session_state:
    st.session_state.multi_ppl_steps = {}
if "pump_headers" not in st.session_state:
    st.session_state.pump_headers = {}
if "just_set_diameter" not in st.session_state:
    st.session_state.just_set_diameter = False

unit_map = {
    "mL/hr": "MH",
    "mL/min": "MM",
    "\u00b5L/hr": "UH",
    "\u00b5L/min": "UM",
    "mL": "ML",
    "\u00b5L": "UL"
}

pump_name_to_address = {str(i): f"{i-1:02d}" for i in range(1, 11)}
user_pump_id = st.selectbox("Pump", list(pump_name_to_address.keys()))
real_pump_addr = pump_name_to_address[user_pump_id]

current_dia = st.session_state.pump_headers.get(real_pump_addr)
if current_dia:
    st.info(f"\u2705 Current Diameter: {current_dia} mm")
else:
    st.warning("\u26a0\ufe0f No diameter set for this pump.")

if real_pump_addr not in st.session_state.multi_ppl_steps:
    st.session_state.multi_ppl_steps[real_pump_addr] = []

# Step builder UI
st.markdown("### \u2795 Add Step to Pump")
cols = st.columns(6)
step_types = ["RAT_CONT", "RAT_VOL", "PAS", "LOP", "LPS", "BEP"]
labels = ["Rate (cont)", "Rate (vol)", "Pause", "Loop", "LPS", "BEP"]

def make_step(typ):
    if typ == "RAT_CONT":
        return {"type": "RAT_CONT", "rate": 1.0, "unit": "mL/min", "direction": "INF"}
    elif typ == "RAT_VOL":
        return {"type": "RAT_VOL", "rate": 1.0, "unit": "mL/min", "volume": 1.0, "direction": "INF"}
    elif typ == "PAS":
        return {"type": "PAS", "duration": 5}
    elif typ == "LOP":
        return {"type": "LOP", "count": 3}
    elif typ in ["LPS", "BEP"]:
        return {"type": typ}

for i, typ in enumerate(step_types):
    if cols[i].button(labels[i]):
        st.session_state.multi_ppl_steps[real_pump_addr].append(make_step(typ))

st.markdown("###Edit Steps")

steps = st.session_state.multi_ppl_steps[real_pump_addr]

for i, step in enumerate(steps):
    with st.container():
        st.markdown(f"**Step {i+1}: {step['type']}**")
        c1, c2, c3 = st.columns([6, 1, 1])

        if step["type"] == "RAT_CONT":
            step["rate"] = c1.number_input("Rate", value=step["rate"], key=f"rc{i}")
            step["unit"] = c1.selectbox("Units", list(unit_map.keys())[:4], index=0, key=f"ru{i}")
            step["direction"] = c1.selectbox("Dir", ["INF", "WDR", "REV"], key=f"rd{i}")

        elif step["type"] == "RAT_VOL":
            step["rate"] = c1.number_input("Rate", value=step["rate"], key=f"rv{i}")
            step["unit"] = c1.selectbox("Units", list(unit_map.keys())[:4], index=0, key=f"rvu{i}")
            step["volume"] = c1.number_input("Volume", value=step["volume"], key=f"rvol{i}")
            step["direction"] = c1.selectbox("Dir", ["INF", "WDR", "REV"], key=f"rdir{i}")

        elif step["type"] == "PAS":
            step["duration"] = c1.number_input("Duration (s)", value=step["duration"], key=f"p{i}")

        elif step["type"] == "LOP":
            step["count"] = c1.number_input("Loop count", value=step["count"], key=f"l{i}")

        if c2.button("❌", key=f"del_{i}"):
            steps.pop(i)
            st.experimental_rerun()

        if i > 0:
            if c3.button("⬆️", key=f"up_{i}"):
                steps[i - 1], steps[i] = steps[i], steps[i - 1]
                st.experimental_rerun()

# Set diameter
st.markdown("---")
st.markdown("### Set Diameter")
volumeselect = st.selectbox("Volume Syringe", ["10 ml", "20 ml", "30 ml", "60 ml"])
dia_lookup = {"10 ml": 15.8, "20 ml": 20.15, "30 ml": 23.1, "60 ml": 29.7}
dia = dia_lookup[volumeselect]
if st.button("✅ Confirm Diameter"):
    st.session_state.pump_headers[real_pump_addr] = dia
    st.success(f"Diameter set to {dia} mm for Pump {user_pump_id}")

# Check for missing diameters
missing = [str(int(pid)+1) for pid, steps in st.session_state.multi_ppl_steps.items() if steps and pid not in st.session_state.pump_headers]

if missing:
    st.error(f"⛔ Pumps {', '.join(missing)} have steps but no diameter set!")
else:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for pid, steps in st.session_state.multi_ppl_steps.items():
            if not steps or pid not in st.session_state.pump_headers:
                continue
            dia = st.session_state.pump_headers[pid]
            header = [
                f"DIA{dia}",
                f"VOL\tML",
                "TRGFT",
                "AL\t0",
                "PF\t0",
                "BP\t0",
                ";*********************************************************************",
                "", "", "", "",
                ";*********************************************************************"
            ]
            program = []
            for i, step in enumerate(steps):
                phn = f"PHN\t{i+1}"
                fun = ""
                sublines = []
                t = step["type"]
                if t == "RAT_CONT":
                    fun = "FUN\tRAT"
                    sublines = [f"RAT\t{step['rate']}\t{unit_map.get(step['unit'], step['unit'])}", f"DIR\t{step['direction']}"]
                elif t == "RAT_VOL":
                    fun = "FUN\tRAT"
                    sublines = [f"RAT\t{step['rate']}\t{unit_map.get(step['unit'], step['unit'])}", f"VOL\t{step['volume']}", f"DIR\t{step['direction']}"]
                elif t in ["PAS", "LOP"]:
                    val = step.get("duration") or step.get("count")
                    fun = f"FUN\t{t}\t{val}"
                elif t in ["LPS", "BEP"]:
                    fun = f"FUN\t{t}"
                block = [phn, fun] + sublines + ["", "", "", ";*********************************************************************"]
                program.extend(block)

            # Final stop
            program.extend([f"PHN\t{len(steps)+1}", "FUN\tSTP", "", "", "", ";*********************************************************************"])
            full_script = "\n".join(header + program)
            zf.writestr(f"pump_{pid}_script.ppl", full_script)
    zip_buffer.seek(0)

custom_filename = st.text_input("Enter ZIP filename (without .zip)", value="all_pumps_scripts")
safe_filename = sanitize_filename(custom_filename)
if st.download_button("Download All Pumps as ZIP", data=zip_buffer, file_name=safe_filename, mime="application/zip"):
    st.success(f"{safe_filename} is ready to download!")

if st.button("❌ Clear All Steps"):
    st.session_state.multi_ppl_steps.clear()
    st.session_state.pump_headers.clear()