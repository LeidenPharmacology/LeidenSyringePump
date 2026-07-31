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
import math
import re
import zipfile

import pandas as pd
import streamlit as st
from datetime import datetime, timedelta


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
        # stack of output-lists; stack[-1] is the list currently being filled
        # (top level, or the currently-open innermost loop)
        stack = [[]]

        for cmd_step in block:
            cmd = cmd_step[0]

            if cmd == "LPS":
                stack.append([])

            elif cmd == "LOP":
                loop_count = cmd_step[1]
                if len(stack) == 1:
                    # Unmatched LOP — treat as a no-op, same as before
                    stack[-1].append(cmd_step)
                    continue
                inner = stack.pop()
                for _ in range(loop_count):
                    stack[-1].extend(inner)

            else:
                stack[-1].append(cmd_step)

        return stack[0]

    return resolve_block(steps)


def calculate_step_timeline(flat_steps: list) -> list[dict]:
    """
    Build a chronological timeline for a flat (already expanded) list of steps.

    For readability, consecutive PAS steps of identical duration are collapsed
    into a single "Waiting for ..." row spanning their combined duration,
    instead of one row per 60-second pulse.

    Supports:
        - RAT_VOL: computes duration from rate + volume
        - PAS: duration is directly specified in seconds
        - All other steps: zero duration (instantaneous)

    Args:
        flat_steps: Flat list of step tuples (no LPS/LOP).

    Returns:
        List of dicts with keys: Step, Start Time, Duration (s), Description.
    """
    def format_hms(total_sec: float) -> str:
        total_sec = int(round(total_sec))
        h, rem = divmod(total_sec, 3600)
        m, s = divmod(rem, 60)
        parts = []
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        if s or not parts:
            parts.append(f"{s}s")
        return " ".join(parts)

    timeline = []
    elapsed_sec = 0.0
    step_no = 0

    i = 0
    n = len(flat_steps)
    while i < n:
        step = flat_steps[i]
        cmd = step[0]

        if cmd == "PAS":
            # Collapse this run of consecutive identical-duration PAS steps
            pas_duration = step[1]
            run_len = 1
            j = i + 1
            while j < n and flat_steps[j][0] == "PAS" and flat_steps[j][1] == pas_duration:
                run_len += 1
                j += 1

            total_wait_sec = pas_duration * run_len
            step_no += 1
            timeline.append({
                "Step":         step_no,
                "Start Time":   str(timedelta(seconds=elapsed_sec)),
                "Duration (s)": round(total_wait_sec, 2),
                "Description":  f"Waiting for {format_hms(total_wait_sec)} ({run_len} x PAS {pas_duration})",
            })

            elapsed_sec += total_wait_sec
            i = j
            continue

        # Non-PAS step: same handling as before
        duration_sec = 0.0

        if cmd == "RAT_VOL":
            rate, unit, vol = step[1], step[2], step[3]
            rate_ml_per_hr = {
                "mL/hr":  rate,
                "mL/min": rate * 60,
                "µL/hr":  rate / 1000,
                "µL/min": rate / 1000 * 60,
            }.get(unit, rate)
            duration_sec = (vol / rate_ml_per_hr) * 3600 if rate_ml_per_hr > 0 else 0

        step_no += 1
        timeline.append({
            "Step":         step_no,
            "Start Time":   str(timedelta(seconds=elapsed_sec)),
            "Duration (s)": round(duration_sec, 2),
            "Description":  " ".join(str(x) for x in step),
        })

        elapsed_sec += duration_sec
        i += 1

    return timeline


def calculate_total_volume(steps: list) -> float:
    """
    Sum the total dispensed volume across all steps, including (arbitrarily
    nested) loops.

    Implemented by reusing flatten_steps(), which already does correct
    stack-based LPS/LOP matching, then summing the RAT_VOL volumes in the
    fully-expanded list. (A previous single-level version of this function
    mis-handled multi-level nested loops, such as the hour/minute wait
    blocks the PK Infusion Planner builds.)

    Args:
        steps: Possibly nested list of step tuples.

    Returns:
        Total volume in mL (or whatever unit the RAT_VOL steps use).
    """
    flat = flatten_steps(steps)
    return sum(step[3] for step in flat if step[0] == "RAT_VOL")


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
# PK / INFUSION-PLANNER HELPER FUNCTIONS
# =============================================================================

RATE_TO_ML_HR = {
    "mL/hr":  1.0,
    "mL/min": 60.0,
    "µL/hr":  0.001,
    "µL/min": 0.06,
}


def rate_to_ml_per_hr(rate: float, unit: str) -> float:
    """Convert a pump rate given in any supported unit to mL/hr."""
    return rate * RATE_TO_ML_HR.get(unit, 1.0)


def ml_per_hr_to_rate(rate_ml_hr: float, unit: str) -> float:
    """Convert a rate expressed in mL/hr back to the requested display unit."""
    factor = RATE_TO_ML_HR.get(unit, 1.0)
    return rate_ml_hr / factor if factor else rate_ml_hr


def required_mass_rate(cmax_mg_l: float, v_central_ml: float, t_inf_h: float,
                        t_half_h: float | None = None) -> float:
    """
    Compute the drug mass-delivery rate (mg/hr) needed to reach a target Cmax
    at the end of a finite infusion of duration t_inf_h, in a one-compartment
    model with volume of distribution v_central_ml.

    If t_half_h is provided, first-order elimination during the infusion is
    accounted for using the standard constant-rate-infusion equation:

        C(t) = (Rate / CL) * (1 - exp(-k * t)),  CL = k * V

    Solved for Rate at t = t_inf_h:

        Rate = Cmax * k * V / (1 - exp(-k * t_inf_h))

    If t_half_h is None (or 0), a simple mass-balance is used instead
    (i.e. elimination during the infusion is assumed negligible):

        Rate = Cmax * V / t_inf_h

    Args:
        cmax_mg_l:    Target peak concentration, mg/L.
        v_central_ml: Central volume of distribution, mL.
        t_inf_h:      Infusion duration, hours.
        t_half_h:     Elimination half-life, hours (optional).

    Returns:
        Required mass delivery rate in mg/hr.
    """
    dose_mg = cmax_mg_l * v_central_ml / 1000.0  # mg/L * mL / 1000 = mg

    if t_half_h and t_half_h > 0 and t_inf_h > 0:
        k = math.log(2) / t_half_h
        x = k * t_inf_h
        if x < 1e-9:
            # Numerically stable limit: (1 - exp(-x)) / x -> 1 as x -> 0
            return dose_mg / t_inf_h
        return cmax_mg_l * v_central_ml / 1000.0 * k / (1 - math.exp(-x))

    if t_inf_h <= 0:
        return 0.0

    return dose_mg / t_inf_h


def compute_clearance_ml_hr(v_central_ml: float, t_half_h: float | None) -> float | None:
    """
    Compute systemic clearance CL = ke * V, where ke = ln(2) / T1/2.

    This is the volumetric "washout" rate a HFIM/chemostat-style system needs
    to replicate at steady state (i.e. the media/waste pump flow rate that
    matches the modeled elimination), expressed in mL/hr.

    Returns None if no half-life is being accounted for (CL is undefined /
    not meaningful without an elimination term).
    """
    if not t_half_h or t_half_h <= 0:
        return None
    k = math.log(2) / t_half_h
    return k * v_central_ml


def pump_rate_from_mass_rate(mass_rate_mg_hr: float, conc_mg_ml: float, unit: str) -> float:
    """Given a required mg/hr delivery and a syringe concentration (mg/mL),
    return the pump volumetric rate in the requested unit."""
    if conc_mg_ml <= 0:
        return 0.0
    rate_ml_hr = mass_rate_mg_hr / conc_mg_ml
    return ml_per_hr_to_rate(rate_ml_hr, unit)


def concentration_from_pump_rate(mass_rate_mg_hr: float, pump_rate: float, unit: str) -> float:
    """Given a required mg/hr delivery and a chosen pump volumetric rate,
    return the syringe concentration (mg/mL) needed."""
    rate_ml_hr = rate_to_ml_per_hr(pump_rate, unit)
    if rate_ml_hr <= 0:
        return 0.0
    return mass_rate_mg_hr / rate_ml_hr


def build_wait_steps(total_seconds: float) -> list:
    """
    Build a nested LPS/PAS/LOP block that pauses for `total_seconds`,
    working around the NE-1000 firmware limit of PAS <= 60 seconds.

    Structure (matches the pump's expected nesting):
        - An "hour" layer, only emitted if there's a whole number of
          60-minute blocks to wait:
              LPS
              LPS
              PAS   60
              LOP   60      (60 x 60s = 1 hour)
              LOP   <hours> (repeat the hour block <hours> times)
        - A "minute" layer, only emitted if there are leftover minutes
          (< 60) to wait:
              LPS
              PAS   60
              LOP   <minutes>
        - A trailing plain PAS, only emitted if there are leftover
          seconds (< 60) to wait.

    Any of the three layers is skipped if its count is zero, so a wait
    of e.g. exactly 90 seconds becomes just [LPS, PAS 60, LOP 1, PAS 30],
    and a wait of exactly 24 h becomes exactly the block you described:
    LPS, LPS, PAS 60, LOP 60, LOP 24.

    Args:
        total_seconds: Total wait duration, in seconds (will be rounded
            to the nearest whole second).

    Returns:
        Flat list of step tuples (not yet nested inside any outer loop).
    """
    total_seconds = int(round(total_seconds))
    if total_seconds <= 0:
        return []

    remainder_sec = total_seconds % 60
    total_minutes = total_seconds // 60
    remainder_minutes = total_minutes % 60
    hours = total_minutes // 60

    steps = []

    if hours > 0:
        steps += [["LPS"], ["LPS"], ["PAS", 60], ["LOP", 60], ["LOP", int(hours)]]

    if remainder_minutes > 0:
        steps += [["LPS"], ["PAS", 60], ["LOP", int(remainder_minutes)]]

    if remainder_sec > 0:
        steps += [["PAS", remainder_sec]]

    return steps


# =============================================================================
# SESSION STATE INITIALISATION
# =============================================================================

# multi_ppl_steps: { pump_address: [ step_tuple, ... ] }
if "multi_ppl_steps" not in st.session_state:
    st.session_state.multi_ppl_steps = {}

# pump_headers: { pump_address: diameter_mm }
if "pump_headers" not in st.session_state:
    st.session_state.pump_headers = {}

# pk_planner_log: list of dicts, one per "Build repeating infusion block" click,
# capturing the inputs and solved outputs for later reference/export
if "pk_planner_log" not in st.session_state:
    st.session_state.pk_planner_log = []


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
# PK INFUSION PLANNER (alternative mode: repeat-dosing built from PK targets)
# =============================================================================

with st.expander("🧮 PK Infusion Planner — build a repeating infusion from Cmax / Vd / T½", expanded=False):

    st.caption(
        "Use this when you don't want to hand-enter a rate. Give the PK targets below, "
        "and either a pump rate or a syringe concentration — the tool solves for the "
        "other one, then builds the LPS / RAT_VOL / PAS / LOP block for you."
    )

    # --- Repeat scheduling ---
    st.markdown("**1. Repeat schedule**")
    col_y, col_n = st.columns(2)
    with col_y:
        interval_h = st.number_input("Repeat every … hours (y)", min_value=0.01, value=6.0, format="%0.2f")
    with col_n:
        n_repeats = st.number_input("Number of repeats", min_value=1, value=4, step=1)

    # --- Duration or volume for the infusion itself ---
    st.markdown("**2. Each infusion event — define by duration or by volume**")
    dose_def_mode = st.radio(
        "Define this infusion by:",
        ["Duration (h)", "Volume (mL)"],
        horizontal=True,
        key="pk_dose_def_mode",
    )

    if dose_def_mode == "Duration (h)":
        t_inf_h = st.number_input("Infusion duration z (h)", min_value=0.01, value=1.0, format="%0.2f")
        target_volume_ml = None
    else:
        target_volume_ml = st.number_input("Infusion volume (mL)", min_value=0.01, value=5.0, format="%0.2f")
        t_inf_h = st.number_input(
            "Infusion duration used for the Cmax calculation (h)",
            min_value=0.01, value=1.0, format="%0.2f",
            help="The PK equation still needs a target duration to solve for the required rate. "
                 "The volume above is what actually gets loaded/run; if it doesn't match "
                 "rate × duration, the achieved Cmax will differ from the target — a warning "
                 "will be shown below.",
        )

    # --- PK targets ---
    st.markdown("**3. PK targets**")
    col_cmax, col_vc = st.columns(2)
    with col_cmax:
        cmax = st.number_input("Cmax (mg/L)", min_value=0.01, value=10.0, format="%0.2f")
    with col_vc:
        v_central = st.number_input("V central (mL)", min_value=0.01, value=250.0, format="%0.2f")

    use_half_life = st.checkbox("Account for elimination (T½)", value=True)
    t_half = None
    if use_half_life:
        t_half = st.number_input("T½ (h)", min_value=0.0001, value=4.0, format="%0.2f")

    # --- Solve for rate or concentration ---
    st.markdown("**4. Solve for pump rate or syringe concentration**")
    solve_mode = st.radio(
        "I know the:",
        ["Syringe drug concentration (solve for pump rate)", "Pump infusion rate (solve for syringe concentration)"],
        key="pk_solve_mode",
    )

    pump_unit = st.selectbox("Pump rate unit", RATE_UNITS, key="pk_pump_unit")

    known_conc = known_rate = None
    if solve_mode.startswith("Syringe"):
        known_conc = st.number_input("Syringe drug concentration (mg/mL)", min_value=0.0001, value=1.0, format="%0.4f")
    else:
        known_rate = st.number_input(f"Pump infusion rate ({pump_unit})", min_value=0.0001, value=5.0, format="%0.4f")

    direction = st.selectbox("Direction", ["INF", "WDR", "REV"], key="pk_direction")

    # --- Compute ---
    mass_rate_mg_hr = required_mass_rate(cmax, v_central, t_inf_h, t_half)

    if solve_mode.startswith("Syringe"):
        solved_pump_rate = pump_rate_from_mass_rate(mass_rate_mg_hr, known_conc, pump_unit)
        solved_conc = known_conc
    else:
        solved_pump_rate = known_rate
        solved_conc = concentration_from_pump_rate(mass_rate_mg_hr, known_rate, pump_unit)

    rate_ml_hr = rate_to_ml_per_hr(solved_pump_rate, pump_unit)

    # Volume actually delivered by rate x duration, vs. the user's target volume (if given)
    computed_volume_ml = rate_ml_hr * t_inf_h

    if target_volume_ml is not None:
        step_volume_ml = target_volume_ml
        achieved_duration_h = target_volume_ml / rate_ml_hr if rate_ml_hr > 0 else 0
    else:
        step_volume_ml = computed_volume_ml
        achieved_duration_h = t_inf_h

    clearance_ml_hr = compute_clearance_ml_hr(v_central, t_half if use_half_life else None)

    st.divider()
    st.markdown("**Results**")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Required mass rate", f"{mass_rate_mg_hr:.4g} mg/hr")
    r2.metric("Pump rate", f"{solved_pump_rate:.4g} {pump_unit}")
    r3.metric("Syringe concentration", f"{solved_conc:.4g} mg/mL")
    if clearance_ml_hr is not None:
        r4.metric("Clearance (CL)", f"{clearance_ml_hr/60:.4g} mL/min")
    else:
        r4.metric("Clearance (CL)", "n/a")

    st.caption(
        f"Volume for this infusion step: **{step_volume_ml:.3f} mL**, "
        f"actual run duration: **{achieved_duration_h:.3f} h**."
    )

    if clearance_ml_hr is not None:
        st.info(
            f"💧 **Media/waste pump target:** to hold this system at steady state, the "
            f"medium-in / waste-out pump should run at roughly "
            f"**{clearance_ml_hr / 60:.4g} mL/min**— **Recommendation**-run the waste out a bit higher then the media in pump  "
            f"**Elimination rate**  is CL = ln(2)/T½ × V_central, "
            f"i.e. the volumetric washout rate that reproduces the modeled elimination. "
            f"This is independent of the drug pump rate above; it's driven purely by V_central and T½."
        )
    else:
        st.caption(
            "ℹ️ Enable 'Account for elimination (T½)' above to get a clearance-based "
            "media/waste pump rate suggestion."
        )

    if target_volume_ml is not None and abs(target_volume_ml - computed_volume_ml) > 1e-6:
        st.warning(
            f"⚠️ The requested volume ({target_volume_ml:.3f} mL) does not match rate × duration "
            f"({computed_volume_ml:.3f} mL for {t_inf_h:.3f} h). The pump will actually run for "
            f"{achieved_duration_h:.3f} h instead of {t_inf_h:.3f} h, so the true Cmax achieved "
            f"will differ from your {cmax} mg/L target."
        )

    if interval_h * 3600 < achieved_duration_h * 3600:
        st.error("⛔ The infusion duration is longer than the repeat interval (y) — the pump would "
                 "never finish one dose before the next is due. Increase y or shorten the infusion.")

    st.markdown("**5. Add to pump**")

    wait_seconds = max(0, interval_h * 3600 - achieved_duration_h * 3600)
    wait_steps = build_wait_steps(wait_seconds)

    preview_block = (
        [["LPS"], ["RAT_VOL", round(solved_pump_rate, 4), pump_unit, round(step_volume_ml, 4), direction]]
        + wait_steps
        + [["LOP", int(n_repeats)]]
    )
    existing_phase_count = len(st.session_state.multi_ppl_steps.get(real_pump_addr, []))
    total_phase_count = existing_phase_count + len(preview_block) + 1  # +1 for the final STP phase

    st.caption(f"This will add **{len(preview_block)} phases** to Pump {user_pump_id} "
               f"(program would then have **{total_phase_count} phases total**, incl. final STOP).")
    if total_phase_count > 41:
        st.warning(
            "⚠️ Many NE-1000 firmware revisions cap a program at 41 phases. "
            f"{total_phase_count} would exceed that — double check your pump's actual limit "
            "before uploading."
        )

    if st.button("➕ Build repeating infusion block on this pump"):
        st.session_state.multi_ppl_steps[real_pump_addr].extend(preview_block)

        st.session_state.pk_planner_log.append({
            "Timestamp":               datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Pump":                    user_pump_id,
            "Repeat every (h)":        interval_h,
            "Number of repeats":       int(n_repeats),
            "Dose defined by":         dose_def_mode,
            "Infusion duration (h) [target/used for Cmax calc]": t_inf_h,
            "Target volume input (mL)": target_volume_ml if target_volume_ml is not None else "",
            "Cmax (mg/L)":             cmax,
            "V central (mL)":          v_central,
            "Elimination accounted":   use_half_life,
            "T1/2 (h)":                t_half if t_half is not None else "",
            "Solved for":              "Pump rate" if solve_mode.startswith("Syringe") else "Syringe concentration",
            "Direction":               direction,
            "Required mass rate (mg/hr)": round(mass_rate_mg_hr, 6),
            "Pump rate":               round(solved_pump_rate, 6),
            "Pump rate unit":          pump_unit,
            "Syringe concentration (mg/mL)": round(solved_conc, 6),
            "Step volume (mL)":        round(step_volume_ml, 4),
            "Actual run duration (h)": round(achieved_duration_h, 4),
            "Clearance CL (mL/hr)":    round(clearance_ml_hr, 4) if clearance_ml_hr is not None else "",
            "Clearance CL (mL/min)":   round(clearance_ml_hr / 60, 4) if clearance_ml_hr is not None else "",
        })

        st.success(
            f"Added a repeating infusion block to Pump {user_pump_id}: "
            f"{solved_pump_rate:.4g} {pump_unit} for {step_volume_ml:.3f} mL, "
            f"every {interval_h:g} h, ×{int(n_repeats)}."
        )
        st.rerun()

    if st.session_state.pk_planner_log:
        st.markdown("**Planner history**")
        planner_log_df = pd.DataFrame(st.session_state.pk_planner_log)
        st.dataframe(planner_log_df, use_container_width=True, hide_index=True)

        planner_log_csv = planner_log_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📄 Download PK planner settings + results (CSV)",
            data=planner_log_csv,
            file_name="pk_infusion_planner_log.csv",
            mime="text/csv",
            key="download_pk_planner_log",
        )

        if st.button("🗑️ Clear planner history"):
            st.session_state.pk_planner_log = []
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

        # Add the PK infusion planner's settings/results log, if any entries exist
        if st.session_state.pk_planner_log:
            planner_log_csv_for_zip = pd.DataFrame(st.session_state.pk_planner_log).to_csv(index=False).encode("utf-8")
            zf.writestr("pk_infusion_planner_log.csv", planner_log_csv_for_zip)

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
    st.session_state.pk_planner_log = []
    st.rerun()