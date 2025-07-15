import streamlit as st
import json
import pandas as pd
import io
import zipfile
import re
from streamlit_autorefresh import st_autorefresh

def sanitize_filename(name):
    """Sanitize the filename to remove unsafe characters."""
    name = name.strip()
    name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", name)  # Replace unsafe characters with underscore
    if not name.lower().endswith(".zip"):
        name += ".zip"
    return name[:100]  # Optional: limit to 100 characters

# Configure the Streamlit page layout and title
st.set_page_config(page_title="NE-1000 PPL Composer", layout="wide")
st.title("📟 NE-1000 PPL Step Composer")

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
    # For diameter step, user selects syringe volume to determine diameter in mm
    volumeselect = st.selectbox("Volume Syringe", ["10 ml", "20 ml", "30 ml", "60 ml"])
    dia = {
        "10 ml": 15.8,
        "20 ml": 20.15,
        "30 ml": 23.1,
        "60 ml": 29.7
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

# Display the steps added for each pump in separate columns
sorted_pumps = sorted(st.session_state.multi_ppl_steps.items(), key=lambda x: int(x[0]))
cols = st.columns(len(sorted_pumps))

for idx, (pid, steps) in enumerate(sorted_pumps):
    if not steps:
        continue  # Skip pumps with no steps
    user_label = str(int(pid) + 1)  # Convert pump address back to 1-based label
    with cols[idx]:
        st.subheader(f"Pump {user_label}")
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

if missing_dia_pumps:
    st.error(f"⛔ Pumps {', '.join(missing_dia_pumps)} have steps but no diameter set!")
else:
    # Prepare an in-memory ZIP archive for all pump scripts
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        # Iterate pumps and their steps to generate pump program scripts
        for pid, steps in st.session_state.multi_ppl_steps.items():
            # Skip pumps without steps or without diameter info
            if not steps or pid not in st.session_state.pump_headers:
                continue
    
            # Get diameter for pump header
            dia = st.session_state.pump_headers[pid]
    
            # Static header for pump program file
            header = [
                f"DIA{dia}",
                f"VOL\tML",
                "TRGFT",
                "AL\t0",
                "PF\t0",
                "BP\t0",
                ";*********************************************************************",
                "",
                "",
                "",
                "",
                ";*********************************************************************"
            ]
    
            program = []
            # Build the program steps in pump script format
            for i, step in enumerate(steps):
                cmd = step[0]
                phn = f"PHN\t{i+1}"  # Step number line
                fun = ""
                sublines = []
    
                # Format the step based on its command type
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
                    sublines = [f""]
    
                elif cmd in ["LPS", "BEP"]:
                    fun = f"FUN\t{cmd}"
    
                # Compose full block for the step
                block = [phn, fun] + sublines + ["", "", "", ";*********************************************************************"]
                program.extend(block)
    
            # Add final stop step at the end of the program
            phn = f"PHN\t{len(steps)+1}"
            fun = "FUN\tSTP"
            block = [phn, fun, "", "", "", ";*********************************************************************"]
            program.extend(block)
    
            # Combine header and program steps into full script text
            script = "\n".join(header + program)
    
            # Write the script into the ZIP archive as a .ppl file
            filename = f"pump_{pid}_script.ppl"
            zf.writestr(filename, script)
    
    zip_buffer.seek(0)  # Reset pointer to start of the ZIP buffer
    
if "should_refresh" not in st.session_state:
    st.session_state.should_refresh = False

if st.button("Refresh screen"):
    # perform your move-up logic here
    st.session_state.should_refresh = True

if st.session_state.should_refresh:
    st_autorefresh(interval=100, limit=1, key="manual_refresh_trigger")
    st.session_state.should_refresh = False
    
# Let user input a custom filename for the ZIP (without extension)
custom_filename = st.text_input("📁 Enter ZIP filename (without .zip)", value="all_pumps_scripts")

# Sanitize the filename
safe_filename = sanitize_filename(custom_filename)

# Provide a download button for the ZIP archive
if st.download_button(
    label="💾 Download All Pumps as ZIP",
    data=zip_buffer,
    file_name=safe_filename,
    mime="application/zip"
):
    st.success(f"{safe_filename} is ready to download!")

# Button to clear all steps and pump headers from session state
if st.button("❌ Clear All Steps"):
    st.session_state.multi_ppl_steps.clear()
    st.session_state.pump_headers.clear()
