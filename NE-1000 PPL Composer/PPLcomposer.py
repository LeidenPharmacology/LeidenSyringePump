import streamlit as st
import json
import pandas as pd
import xlsxwriter
import io
import zipfile
import re
from streamlit_autorefresh import st_autorefresh

def flatten_steps(steps):
    flat = []
    i = 0
    while i < len(steps):
        step = steps[i]
        if step[0] == "LPS":
            loop_block = []
            i += 1
            while i < len(steps) and steps[i][0] != "LOP":
                loop_block.append(steps[i])
                i += 1
            if i < len(steps) and steps[i][0] == "LOP":
                loop_count = steps[i][1]
                for _ in range(loop_count):
                    flat.extend(flatten_steps(loop_block))
            else:
                flat.extend(flatten_steps(loop_block))
        else:
            flat.append(step)
        i += 1
    return flat

def calculate_step_timeline(flat_steps):
    timeline = []
    time_sec = 0.0
    for idx, step in enumerate(flat_steps, 1):
        cmd = step[0]
        duration_sec = 0.0

        if cmd == "RAT_VOL":
            rate = step[1]
            vol = step[3]
            unit = step[2]
            if unit == "mL/hr":
                rate_ml_per_hr = rate
            elif unit == "mL/min":
                rate_ml_per_hr = rate * 60
            elif unit == "µL/hr":
                rate_ml_per_hr = rate / 1000
            elif unit == "µL/min":
                rate_ml_per_hr = rate / 1000 * 60
            else:
                rate_ml_per_hr = rate

            duration_sec = (vol / rate_ml_per_hr) * 3600 if rate_ml_per_hr > 0 else 0

        elif cmd == "PAS":
            duration_sec = step[1]

        timeline.append({
            "Step": idx,
            "Start Time": pd.to_timedelta(time_sec, unit="s"),
            "Duration (s)": round(duration_sec, 2),
            "Description": " ".join(str(x) for x in step)
        })

        time_sec += duration_sec

    return timeline

def calculate_total_volume_with_loops(steps):
    def resolve(steps):
        total = 0
        i = 0
        while i < len(steps):
            step = steps[i]
            if step[0] == "LPS":
                loop_block = []
                i += 1
                while i < len(steps) and steps[i][0] != "LOP":
                    loop_block.append(steps[i])
                    i += 1

                if i < len(steps) and steps[i][0] == "LOP":
                    loop_count = steps[i][1]  # e.g., ["LOP", 3]
                    loop_vol = resolve(loop_block)
                    total += loop_vol * loop_count
                else:
                    # Unmatched LPS without LOP: ignore loop semantics
                    total += resolve(loop_block)
            else:
                if step[0] == "RAT_VOL":
                    total += step[3]  # step = ["RAT_VOL", rate, unit, volume, direction]
            i += 1
        return total

    return resolve(steps)

def sanitize_filename(name):
    """Sanitize the filename to remove unsafe characters."""
    name = name.strip()
    name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", name)  # Replace unsafe characters with underscore
    if not name.lower().endswith(".zip"):
        name += ".zip"
    return name[:100]  # Optional: limit to 100 characters

# Configure the Streamlit page layout and title
st.set_page_config(page_title="Magic carpet: NE-1000 PPL Composer", layout="wide")
st.title("Magic carpet: 📿 NE-1000 PPL Step Composer")

# Initialize session state dictionaries to store pump steps and pump headers (diameter info)
if "multi_ppl_steps" not in st.session_state:
    st.session_state.multi_ppl_steps = {}
if "pump_headers" not in st.session_state:
    st.session_state.pump_headers = {}  
if "just_set_diameter" not in st.session_state:
    st.session_state.just_set_diameter = False

# Map human-readable rate units to pump code abbreviations
unit_map = {
    "mL/hr": "MH",
    "mL/min": "MM",
    "µL/hr": "UH",
    "µL/min": "UM",
    "mL": "ML",
    "µL": "UL"
}

# Map pump names (1-10) to zero-padded address strings used internally
pump_name_to_address = {str(i): f"{i-1:02d}" for i in range(1, 11)}

# User selects a pump (1 to 10) via dropdown
user_pump_id = st.selectbox("Pump", list(pump_name_to_address.keys()))

# Convert selected pump to internal address string
real_pump_addr = pump_name_to_address[user_pump_id]

# Advanced mode --> remove warnings 
advancedmode = st.checkbox("Advanced mode?", value = False)

# Show current diameter for selected pump, if set
current_dia = st.session_state.pump_headers.get(real_pump_addr)
if current_dia:
    st.info(f"✅ Current Diameter: {current_dia} mm")
else:
    st.warning("⚠️ No diameter set for this pump.")

# Initialize the steps list for the selected pump if not already present
if real_pump_addr not in st.session_state.multi_ppl_steps:
    st.session_state.multi_ppl_steps[real_pump_addr] = []

# Select the type of step to add to the pump program
step_type = st.selectbox("Step Type", ["DIA", "RAT (continuous)", "RAT (volume)", "PAS", "LPS", "LOP", "BEP"])

params = []

# Handling each step type input and parameters
if step_type == "DIA":
    # For diameter step, user selects syringe volume to determine diameter in mm and only for Termuno syringes
    volumeselect = st.selectbox("Volume Syringe", ["10 ml", "20 ml", "30 ml", "60 ml", "60 ml Henk"])
    dia = {
        "10 ml": 15.8,
        "20 ml": 20.15,
        "30 ml": 23.1,
        "60 ml": 29.7,
        "60 ml Henk": 26.7,
    }[volumeselect]
    
    # Confirm button sets the diameter for the selected pump in session state
    if st.button("✅ Confirm Diameter"):
        st.session_state.pump_headers[real_pump_addr] = dia
        st.success(f"Diameter set to {dia} mm for Pump {user_pump_id}")

elif step_type == "RAT (continuous)":
    # Continuous rate step: user inputs rate, units, and direction
    rate = st.number_input("Rate", min_value=0.01, format="%0.2f")
    unit = st.selectbox("Rate Units", list(unit_map.keys())[:4])  # Only rate units
    direction = st.selectbox("Direction", ["INF", "WDR", "REV"])
    params = ["RAT_CONT", rate, unit, direction]

elif step_type == "RAT (volume)":
    # Volume-limited rate step: user inputs rate, units, volume, and direction
    rate = st.number_input("Rate", min_value=0.01, format="%0.2f")
    unit = st.selectbox("Rate Units", list(unit_map.keys())[:4])
    volume = st.number_input("Volume", min_value=0.01, format="%0.2f")
    direction = st.selectbox("Direction", ["INF", "WDR", "REV"])
    params = ["RAT_VOL", rate, unit, volume, direction]

elif step_type == "PAS":
    # Pause step: input duration in seconds
    val = st.number_input("Pause for ... seconds", min_value=1, format="%d")
    params = [step_type, val]

elif step_type == "LOP":
    # Loop step: input number of times to loop
    val = st.number_input("Loop for ... times", min_value=1, format="%d")
    params = [step_type, val]

elif step_type in ["LPS", "BEP"]:
    # Steps with no parameters
    params = [step_type]

# Add the constructed step parameters to the pump’s step list when "Add Step" button is clicked
# Diameter steps are handled separately via confirmation button
if step_type != "DIA" and st.button("➕ Add Step to Pump"):
    st.session_state.multi_ppl_steps[real_pump_addr].append(params)

syringe_max_volume_map = {
    15.8: 10,
    20.15: 20,
    23.1: 30,
    26.7: 61,
    29.7: 60
}

# Display the steps added for each pump in separate columns
sorted_pumps = sorted(st.session_state.multi_ppl_steps.items(), key=lambda x: int(x[0]))
cols = st.columns(len(sorted_pumps))

for idx, (pid, steps) in enumerate(sorted_pumps):
    if not steps:
        continue  # Skip pumps with no steps
    user_label = str(int(pid) + 1)  # Convert pump address back to 1-based label
    with cols[idx]:
        st.subheader(f"Pump {user_label}")
    
        dia = st.session_state.pump_headers.get(pid)
        max_vol = syringe_max_volume_map.get(dia, None)
        assigned_vol = sum(step[3] for step in steps if step[0] == "RAT_VOL")
    
        if max_vol:
            raw_percent = (assigned_vol / max_vol) * 100
            percent = min(100, raw_percent)
            st.caption(f"💧 Assigned Volume: **{assigned_vol:.2f} mL** / Max {max_vol} mL")
            if raw_percent > 100 and advancedmode == False:
                st.error("⛔ Over capacity!")
            elif raw_percent == 100 and advancedmode == False:
                st.warning("⛔ At capacity")
            elif raw_percent >= 80 and advancedmode == False:
                st.warning("⚠️ Near capacity")
            st.progress(min(100, int(percent)))
        else:
            st.caption(f"💧 Assigned Volume: **{assigned_vol:.2f} mL**")

        # Display each step with an option to delete it
        for i, step in enumerate(steps):
            step_display = f"{i+1:02d}. {' '.join(str(x) for x in step)}"
            col1, col2, col3 = st.columns([7, 1, 1])
            col1.text(step_display)
            
            # Move Up button - disabled if first step
            if i > 0:
                if col2.button("↑", key=f"up_{pid}_{i}"):
                    steps[i-1], steps[i] = steps[i], steps[i-1]     
            else:
                col2.write("")  # blank for alignment
        
            # Delete button
            if col3.button("❌", key=f"del_{pid}_{i}"):
                steps.pop(i)

# Check for pumps that have steps but no diameter
missing_dia_pumps = [
    str(int(pid) + 1)  # convert back to human-readable pump ID
    for pid, steps in st.session_state.multi_ppl_steps.items()
    if steps and pid not in st.session_state.pump_headers
]

#quick and dirty way to fix the refresh of the changes. Maybe in the future the rerun function is back
#First start with getting the variable to initialize
if "should_refresh" not in st.session_state:
    st.session_state.should_refresh = False

if st.button("Refresh screen"):
    # IF this button is pressed the state should be to true
    st.session_state.should_refresh = True

#this check is to see if the refresh is true causing an manual refresh that should not repeat
if st.session_state.should_refresh:
    #again placeholder as true refresh is not automatic or easy
    st_autorefresh(interval=100, limit=1, key="manual_refresh_trigger")
    st.session_state.should_refresh = False
    

# Let user input a custom filename for the ZIP (without extension)
custom_filename = st.text_input("📁 Enter ZIP filename (without .zip)", value="all_pumps_scripts")

# Sanitize the filename
safe_filename = sanitize_filename(custom_filename)

all_timelines = []
for pid, steps in st.session_state.multi_ppl_steps.items():
    if not steps:
        continue
    flat = flatten_steps(steps)
    timeline = calculate_step_timeline(flat)
    df = pd.DataFrame(timeline)
    df.insert(0, "Pump", int(pid) + 1)
    all_timelines.append(df)

final_df = pd.concat(all_timelines, ignore_index=True) if all_timelines else pd.DataFrame()
csv_data = final_df.to_csv(index=False).encode("utf-8")

if missing_dia_pumps:
    st.error(f"⛔ Pumps {', '.join(missing_dia_pumps)} have steps but no diameter set!")
else:
    # Prepare an in-memory ZIP archive for all pump scripts
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        # Write individual .ppl files
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
                cmd = step[0]
                phn = f"PHN\t{i+1}"
                fun = ""
                sublines = []
    
                if cmd == "RAT_CONT":
                    fun = "FUN\tRAT"
                    rate, unit, dirc = step[1], unit_map.get(step[2], step[2]), step[3]
                    sublines = [f"RAT\t{rate}\t{unit}", f"DIR\t{dirc}"]
    
                elif cmd == "RAT_VOL":
                    fun = "FUN\tRAT"
                    rate, unit, vol, dirc = step[1], unit_map.get(step[2], step[2]), step[3], step[4]
                    sublines = [f"RAT\t{rate}\t{unit}", f"VOL\t{vol}", f"DIR\t{dirc}"]
    
                elif cmd in ["PAS", "LOP"]:
                    fun = f"FUN\t{cmd}\t{step[1]}"
                    sublines = [""]
    
                elif cmd in ["LPS", "BEP"]:
                    fun = f"FUN\t{cmd}"
    
                block = [phn, fun] + sublines + ["", "", "", ";*********************************************************************"]
                program.extend(block)
    
            # Final stop
            phn = f"PHN\t{len(steps)+1}"
            fun = "FUN\tSTP"
            block = [phn, fun, "", "", "", ";*********************************************************************"]
            program.extend(block)
    
            script = "\n".join(header + program)
            zf.writestr(f"pump_{pid}_script.ppl", script)
    
        # ✅ Add the timeline CSV into the ZIP
        if not final_df.empty:
            zf.writestr("timeline.csv", csv_data)
        
    zip_buffer.seek(0)  # Reset buffer

volume_exceeded_errors = []

for pid, steps in st.session_state.multi_ppl_steps.items():
    if not steps or pid not in st.session_state.pump_headers:
        continue

    diameter = st.session_state.pump_headers[pid]
    max_volume = syringe_max_volume_map.get(diameter)
    if not max_volume:
        continue

    total_vol = calculate_total_volume_with_loops(steps)
    if total_vol > max_volume and advancedmode == False :
        human_pid = str(int(pid) + 1)
        volume_exceeded_errors.append(
            f"\u26d4 Pump {human_pid} total volume {total_vol:.2f} mL exceeds syringe max {max_volume} mL"
        )


# Show warnings if any
for err in volume_exceeded_errors:
    st.error(err)

# 🟩 Unified download button for ZIP (pumps + timeline)
if st.download_button(
    label="💾 Download All Pumps + Timeline ZIP",
    data=zip_buffer,
    file_name=safe_filename,
    mime="application/zip"
):
    st.success(f"{safe_filename} is ready to download!")

# 🟨 Separate button for CSV only download
if not final_df.empty:
    st.download_button(
        label="📄 Download Timeline Only (CSV)",
        data=csv_data,
        file_name="pump_timelines.csv",
        mime="text/csv"
    )


# Button to clear all steps and pump headers from session state
if st.button("❌ Clear All Steps"):
    st.session_state.multi_ppl_steps.clear()
    st.session_state.pump_headers.clear()
