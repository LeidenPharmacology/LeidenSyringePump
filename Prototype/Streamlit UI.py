import streamlit as st
import json

st.set_page_config(page_title="NE-1000 PPL Composer", layout="centered")
st.title("📟 NE-1000 PPL Step Composer")

# Store steps in session state
if "ppl_steps" not in st.session_state:
    st.session_state.ppl_steps = []

unit_map = {
    "mL/hr": "MH",
    "mL/min": "MM",
    "µL/hr": "UH",
    "µL/min": "UM",
    "mL": "ML",
    "µL": "UL"
}

step_type = st.selectbox("Step Type", ["DIA", "RAT", "VOL", "DIR", "RUN", "STP", "DEL", "REP"])

# Dynamic inputs based on step type
params = []
if step_type == "DIA":
    val = st.number_input("Diameter (mm)", min_value=0.1, format="%0.2f")
    params = [val]

elif step_type == "RAT":
    rate = st.number_input("Rate", min_value=0.01, format="%0.2f")
    unit = st.selectbox("Rate Units", list(unit_map.keys())[:4])
    params = [rate, unit]

elif step_type == "VOL":
    vol = st.number_input("Volume", min_value=0.01, format="%0.2f")
    unit = st.selectbox("Volume Units", list(unit_map.keys())[4:])
    params = [vol, unit]

elif step_type == "DIR":
    direction = st.selectbox("Direction", ["INF", "WDR", "REV"])
    params = [direction]

elif step_type == "DEL":
    delay = st.number_input("Delay Time (s)", min_value=0.1, format="%0.1f")
    params = [delay]

elif step_type == "REP":
    count = st.number_input("Repeat Count", min_value=1, format="%d")
    params = [count]

# Add step
if st.button("➕ Add Step"):
    st.session_state.ppl_steps.append((step_type, params))

# Step list
if st.session_state.ppl_steps:
    st.subheader("🪜 Current Steps")
    for i, (cmd, args) in enumerate(st.session_state.ppl_steps):
        readable = [unit if unit not in unit_map else unit for unit in args]
        st.text(f"{i+1:02d}. {cmd} {' '.join(str(a) for a in readable)}")

    # Export
    ppl_text = "\n".join(
        f"{cmd} {' '.join(str(unit_map.get(a, a)) for a in args)}"
        for cmd, args in st.session_state.ppl_steps
    )
    st.subheader("📄 Generated PPL Script")
    st.code(ppl_text, language="text")

    st.download_button("💾 Download .ppl", ppl_text, file_name="pump_script.ppl")

# Clear
if st.button("❌ Clear Steps"):
    st.session_state.ppl_steps.clear()
