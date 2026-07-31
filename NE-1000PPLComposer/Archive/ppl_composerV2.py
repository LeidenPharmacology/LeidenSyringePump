"""
Streamlit Application: NE-1000 Pump PPL Composer
@author: jornb

This app allows users to:
- Configure syringe diameters per pump (supports Terumo 10/20/30/60 mL + Henke 60 mL)
- Compose step-based pump programs including loops (LPS/LOP), pauses (PAS), and rate steps
- Validate assigned volume vs syringe capacity with visual progress indicators
- Export .ppl scripts + execution timeline (CSV) as a ZIP archive

Pump addresses are zero-padded internally (e.g., Pump 1 → "00", Pump 2 → "01", etc.)
"""

import io
import re
import zipfile

import pandas as pd
import streamlit as st
from datetime import timedelta


# =============================================================================
# CONSTANTS & LOOKUP TABLES
# =============================================================================

# Maps human-readable rate/volume units to NE-1000 pump code abbreviations
UNIT_MAP = {
    "mL/hr":  "MH",
    "mL/min": "MM",
    "µL/hr":  "UH",
    "µL/min": "UM",
    "mL":     "ML",
    "µL":     "UL",
}

# Maps syringe inner diameter (mm) to its max usable volume (mL)
# Supports Terumo and Henke-Sass Wolf syringe brands
SYRINGE_MAX_VOLUME = {
    15.8:  10,   # Terumo 10 mL
    20.15: 20,   # Terumo 20 mL
    23.1:  30,   # Terumo 30 mL
    29.7:  60,   # Terumo 60 mL
    26.7:  61,   # Henke-Sass Wolf 60 mL (slightly larger bore)
}

# Maps syringe volume label (shown in UI) to inner diameter in mm
SYRINGE_DIAMETER = {
    "10 ml":       15.8,
    "20 ml":       20.15,
    "30 ml":       23.1,
    "60 ml":       29.7,
    "60 ml Henk":  26.7,
}

# Maps pump display names (1–10) to zero-padded internal address strings
PUMP_NAME_TO_ADDRESS = {str(i): f"{i-1:02d}" for i in range(1, 11)}

# Only the first 4 units in UNIT_MAP are valid rate units (the last 2 are volume-only)
RATE_UNITS = list(UNIT_MAP.keys())[:4]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def flatten_steps(steps: list) -> list:
    """
    Recursively expand LPS/LOP loop blocks into a flat list of steps.

    LPS (Loop Start) marks the beginning of a loop block.
    LOP (Loop) marks the end and specifies how many times to repeat.
    Each LOP pairs with the nearest unmatched LPS (stack-based matching).

    Args:
        steps: Nested list of step tuples, possibly containing LPS/LOP pairs.

    Returns:
        Flat list of step tuples with loops fully expanded.
    """
    def resolve_block(block):
        output = []
        lps_stack = []  # Stack of indices where LPS was encountered
        i = 0

        while i < len(block):
            cmd = block[i][0]

            if cmd == "LPS":
                # Push this loop-start index onto the stack
                lps_stack.append(i)
                i += 1

            elif cmd == "LOP":
                loop_count = block[i][1]

                if not lps_stack:
                    # Unmatched LOP — treat as a no-op and skip
                    output.append(block[i])
                    i += 1
                    continue

                # Extract the inner block between LPS and this LOP
                start = lps_stack.pop()
                inner_block = block[start + 1:i]

                # Recursively resolve nested loops, then repeat `loop_count` times
                expanded = resolve_block(inner_block)
                for _ in range(loop_count):
                    output.extend(expanded)

                i += 1

            else:
                # Regular step — pass through unchanged
                output.append(block[i])
                i += 1

        return output

    return resolve_block(steps)


def calculate_step_timeline(flat_steps: list) -> list[dict]:
    """
    Build a chronological timeline for a flat (already expanded) list of steps.

    Supports:
        - RAT_VOL: computes duration from rate + volume
        - PAS: duration is directly specified in seconds
        - All other steps: zero duration (instantaneous)

    Args:
        flat_steps: Flat list of step tuples (no LPS/LOP).

    Returns:
        List of dicts with keys: Step, Start Time, Duration (s), Description.
    """
    timeline = []
    elapsed_sec = 0.0

    for idx, step in enumerate(flat_steps, start=1):
        cmd = step[0]
        duration_sec = 0.0

        if cmd == "RAT_VOL":
            rate, unit, vol = step[1], step[2], step[3]

            # Normalize rate to mL/hr for duration calculation
            rate_ml_per_hr = {
                "mL/hr":  rate,
                "mL/min": rate * 60,
                "µL/hr":  rate / 1000,
                "µL/min": rate / 1000 * 60,
            }.get(unit, rate)

            duration_sec = (vol / rate_ml_per_hr) * 3600 if rate_ml_per_hr > 0 else 0

        elif cmd == "PAS":
            duration_sec = step[1]  # Already in seconds

        timeline.append({
            "Step":         idx,
            "Start Time":   str(timedelta(seconds=elapsed_sec)),
            "Duration (s)": round(duration_sec, 2),
            "Description":  " ".join(str(x) for x in step),
        })

        elapsed_sec += duration_sec

    return timeline


def calculate_total_volume(steps: list) -> float:
    """
    Recursively sum the total dispensed volume across all steps, including loops.

    LPS/LOP pairs multiply the volume of their inner block by the loop count.

    Args:
        steps: Possibly nested list of step tuples.

    Returns:
        Total volume in mL (or whatever unit the RAT_VOL steps use).
    """
    def resolve(steps):
        total = 0.0
        i = 0

        while i < len(steps):
            step = steps[i]

            if step[0] == "LPS":
                # Collect all steps until the matching LOP
                loop_block = []
                i += 1
                while i < len(steps) and steps[i][0] != "LOP":
                    loop_block.append(steps[i])
                    i += 1

                if i < len(steps) and steps[i][0] == "LOP":
                    loop_count = steps[i][1]
                    total += resolve(loop_block) * loop_count
                else:
                    # No matching LOP found — count the block once
                    total += resolve(loop_block)

            elif step[0] == "RAT_VOL":
                total += step[3]  # Volume is the 4th element

            i += 1

        return total

    return resolve(steps)


def sanitize_filename(name: str) -> str:
    """
    Make a user-provided filename safe for use as a ZIP file.

    - Strips whitespace
    - Replaces any character that isn't alphanumeric, underscore, dash, or dot with '_'
    - Ensures the name ends with '.zip'
    - Truncates to 100 characters

    Args:
        name: Raw filename string from the user.

    Returns:
        Sanitized filename string ending in '.zip'.
    """
    name = name.strip()
    name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", name)
    if not name.lower().endswith(".zip"):
        name += ".zip"
    return name[:100]


def generate_ppl_script(pid: str, steps: list, diameter: float) -> str:
    """
    Generate the full .ppl script text for one pump.

    The script contains:
        1. A header block with syringe diameter, volume unit, and pump settings
        2. One PHN (phase number) block per step
        3. A final STP (stop) phase

    Args:
        pid:      Internal pump address string (e.g., "00").
        steps:    List of step tuples for this pump.
        diameter: Syringe inner diameter in mm.

    Returns:
        Multi-line string representing the complete .ppl program.
    """
    # --- Header block ---
    header_lines = [
        f"DIA{diameter}",
        "VOL\tML",
        "TRGFT",
        "AL\t0",
        "PF\t0",
        "BP\t0",
        ";*********************************************************************",
        "", "", "", "",
        ";*********************************************************************",
    ]

    # --- Phase blocks ---
    program_lines = []

    for i, step in enumerate(steps):
        cmd    = step[0]
        phn    = f"PHN\t{i + 1}"
        fun    = ""
        extras = []  # Additional lines below FUN

        if cmd == "RAT_CONT":
            rate, unit, direction = step[1], UNIT_MAP.get(step[2], step[2]), step[3]
            fun    = "FUN\tRAT"
            extras = [f"RAT\t{rate}\t{unit}", f"DIR\t{direction}"]

        elif cmd == "RAT_VOL":
            rate, unit, vol, direction = step[1], UNIT_MAP.get(step[2], step[2]), step[3], step[4]
            fun    = "FUN\tRAT"
            extras = [f"RAT\t{rate}\t{unit}", f"VOL\t{vol}", f"DIR\t{direction}"]

        elif cmd in ("PAS", "LOP"):
            fun = f"FUN\t{cmd}\t{step[1]}"

        elif cmd in ("LPS", "BEP"):
            fun = f"FUN\t{cmd}"

        # Assemble the phase block with a separator footer
        block = [phn, fun] + extras + ["", "", "", ";*********************************************************************"]
        program_lines.extend(block)

    # --- Final stop phase ---
    stop_block = [
        f"PHN\t{len(steps) + 1}",
        "FUN\tSTP",
        "", "", "",
        ";*********************************************************************",
    ]
    program_lines.extend(stop_block)

    return "\n".join(header_lines + program_lines)


# =============================================================================
# SESSION STATE INITIALISATION
# =============================================================================

# multi_ppl_steps: { pump_address: [ step_tuple, ... ] }
if "multi_ppl_steps" not in st.session_state:
    st.session_state.multi_ppl_steps = {}

# pump_headers: { pump_address: diameter_mm }
if "pump_headers" not in st.session_state:
    st.session_state.pump_headers = {}


# =============================================================================
# PAGE CONFIG & TITLE
# =============================================================================

st.set_page_config(page_title="Magic carpet: NE-1000 PPL Composer", layout="wide")
st.title("Magic carpet: 📿 NE-1000 PPL Step Composer")


# =============================================================================
# PUMP SELECTOR & DIAMETER PANEL
# =============================================================================

# Let the user pick which pump to configure (shown as 1–10, stored as "00"–"09")
user_pump_id   = st.selectbox("Pump", list(PUMP_NAME_TO_ADDRESS.keys()))
real_pump_addr = PUMP_NAME_TO_ADDRESS[user_pump_id]

# Advanced mode suppresses capacity warnings (useful for multi-syringe setups)
advanced_mode = st.checkbox("Advanced mode?", value=False)

# Show the currently configured diameter (if any) for this pump
current_dia = st.session_state.pump_headers.get(real_pump_addr)
if current_dia:
    st.info(f"✅ Current Diameter: {current_dia} mm")
else:
    st.warning("⚠️ No diameter set for this pump.")

# Ensure this pump has an entry in the steps dict
if real_pump_addr not in st.session_state.multi_ppl_steps:
    st.session_state.multi_ppl_steps[real_pump_addr] = []


# =============================================================================
# STEP BUILDER
# =============================================================================

step_type = st.selectbox(
    "Step Type",
    ["DIA", "RAT (continuous)", "RAT (volume)", "PAS", "LPS", "LOP", "BEP"]
)

params = []  # Will hold the constructed step tuple

# --- DIA: set syringe diameter ---
if step_type == "DIA":
    volume_label = st.selectbox("Volume Syringe", list(SYRINGE_DIAMETER.keys()))
    dia = SYRINGE_DIAMETER[volume_label]

    if st.button("✅ Confirm Diameter"):
        st.session_state.pump_headers[real_pump_addr] = dia
        st.success(f"Diameter set to {dia} mm for Pump {user_pump_id}")

# --- RAT (continuous): pump at a fixed rate indefinitely ---
elif step_type == "RAT (continuous)":
    rate      = st.number_input("Rate", min_value=0.01, format="%0.2f")
    unit      = st.selectbox("Rate Units", RATE_UNITS)
    direction = st.selectbox("Direction", ["INF", "WDR", "REV"])
    params    = ["RAT_CONT", rate, unit, direction]

# --- RAT (volume): pump at a fixed rate until a target volume is reached ---
elif step_type == "RAT (volume)":
    rate      = st.number_input("Rate", min_value=0.01, format="%0.2f")
    unit      = st.selectbox("Rate Units", RATE_UNITS)
    volume    = st.number_input("Volume", min_value=0.01, format="%0.2f")
    direction = st.selectbox("Direction", ["INF", "WDR", "REV"])
    params    = ["RAT_VOL", rate, unit, volume, direction]

# --- PAS: pause for N seconds ---
elif step_type == "PAS":
    val    = st.number_input("Pause for ... seconds", min_value=1, format="%d")
    params = ["PAS", val]

# --- LOP: end of loop block, repeat N times ---
elif step_type == "LOP":
    val    = st.number_input("Loop for ... times", min_value=1, format="%d")
    params = ["LOP", val]

# --- LPS / BEP: marker steps with no parameters ---
elif step_type in ("LPS", "BEP"):
    params = [step_type]

# Add the step when the user clicks the button (DIA uses its own confirm button above)
if step_type != "DIA" and st.button("➕ Add Step to Pump"):
    st.session_state.multi_ppl_steps[real_pump_addr].append(params)
    st.rerun()


# =============================================================================
# STEP LIST DISPLAY (one column per active pump)
# =============================================================================

# Only show pumps that have at least one step
active_pumps = [(pid, steps) for pid, steps in
                sorted(st.session_state.multi_ppl_steps.items(), key=lambda x: int(x[0]))
                if steps]

if active_pumps:
    cols = st.columns(len(active_pumps))

    for col, (pid, steps) in zip(cols, active_pumps):
        human_label = str(int(pid) + 1)  # Convert internal address back to display name

        with col:
            st.subheader(f"Pump {human_label}")

            # --- Volume capacity indicator ---
            diameter = st.session_state.pump_headers.get(pid)
            max_vol  = SYRINGE_MAX_VOLUME.get(diameter)
            total_vol = calculate_total_volume(steps)

            if max_vol:
                raw_pct  = (total_vol / max_vol) * 100
                capped   = min(100, raw_pct)
                st.caption(f"💧 Assigned: **{total_vol:.2f} mL** / Max {max_vol} mL")

                if not advanced_mode:
                    if raw_pct > 100:
                        st.error("⛔ Over capacity!")
                    elif raw_pct == 100:
                        st.warning("⚠️ At capacity")
                    elif raw_pct >= 80:
                        st.warning("⚠️ Near capacity")

                st.progress(int(capped))
            else:
                st.caption(f"💧 Assigned: **{total_vol:.2f} mL** (no max known)")

            # --- Step rows with move-up and delete buttons ---
            for i, step in enumerate(steps):
                label       = f"{i+1:02d}. {' '.join(str(x) for x in step)}"
                c_text, c_up, c_del = st.columns([7, 1, 1])

                c_text.text(label)

                # ↑ Move step up (not available for the first step)
                if i > 0:
                    if c_up.button("↑", key=f"up_{pid}_{i}"):
                        steps[i - 1], steps[i] = steps[i], steps[i - 1]
                        st.rerun()
                else:
                    c_up.write("")  # Empty placeholder to keep column alignment

                # ❌ Delete this step
                if c_del.button("❌", key=f"del_{pid}_{i}"):
                    steps.pop(i)
                    st.rerun()


# =============================================================================
# VALIDATION: pumps with steps but no diameter
# =============================================================================

missing_dia_pumps = [
    str(int(pid) + 1)
    for pid, steps in st.session_state.multi_ppl_steps.items()
    if steps and pid not in st.session_state.pump_headers
]

if missing_dia_pumps:
    st.error(f"⛔ Pumps {', '.join(missing_dia_pumps)} have steps but no diameter set!")


# =============================================================================
# TIMELINE CALCULATION (for CSV export)
# =============================================================================

all_timelines = []

for pid, steps in st.session_state.multi_ppl_steps.items():
    if not steps:
        continue
    flat     = flatten_steps(steps)
    timeline = calculate_step_timeline(flat)
    df       = pd.DataFrame(timeline)
    df.insert(0, "Pump", int(pid) + 1)
    all_timelines.append(df)

final_df = pd.concat(all_timelines, ignore_index=True) if all_timelines else pd.DataFrame()
csv_data = final_df.to_csv(index=False).encode("utf-8")


# =============================================================================
# ZIP GENERATION (scripts + timeline)
# =============================================================================

# Only build the ZIP when all pumps with steps have a diameter configured
if not missing_dia_pumps:
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w") as zf:
        # Add one .ppl file per configured pump
        for pid, steps in st.session_state.multi_ppl_steps.items():
            if not steps or pid not in st.session_state.pump_headers:
                continue

            diameter = st.session_state.pump_headers[pid]
            script   = generate_ppl_script(pid, steps, diameter)
            zf.writestr(f"pump_{pid}_script.ppl", script)

        # Add the combined timeline CSV if any timeline data exists
        if not final_df.empty:
            zf.writestr("timeline.csv", csv_data)

    zip_buffer.seek(0)


# =============================================================================
# VOLUME EXCEEDED WARNINGS
# =============================================================================

if not advanced_mode:
    for pid, steps in st.session_state.multi_ppl_steps.items():
        if not steps or pid not in st.session_state.pump_headers:
            continue

        diameter  = st.session_state.pump_headers[pid]
        max_vol   = SYRINGE_MAX_VOLUME.get(diameter)
        total_vol = calculate_total_volume(steps)

        if max_vol and total_vol > max_vol:
            human_id = str(int(pid) + 1)
            st.error(
                f"⛔ Pump {human_id}: total volume {total_vol:.2f} mL "
                f"exceeds syringe max {max_vol} mL"
            )


# =============================================================================
# DOWNLOAD BUTTONS & CLEAR
# =============================================================================

# Custom filename for the ZIP archive
custom_filename = st.text_input("📁 Enter ZIP filename (without .zip)", value="all_pumps_scripts")
safe_filename   = sanitize_filename(custom_filename)

# Only show download buttons when there is something to download
if not missing_dia_pumps:
    if st.download_button(
        label="💾 Download All Pumps + Timeline ZIP",
        data=zip_buffer,
        file_name=safe_filename,
        mime="application/zip",
    ):
        st.success(f"{safe_filename} is ready to download!")

if not final_df.empty:
    st.download_button(
        label="📄 Download Timeline Only (CSV)",
        data=csv_data,
        file_name="pump_timelines.csv",
        mime="text/csv",
    )

# Reset everything — useful when starting a new experiment
if st.button("❌ Clear All Steps"):
    st.session_state.multi_ppl_steps.clear()
    st.session_state.pump_headers.clear()
    st.rerun()
