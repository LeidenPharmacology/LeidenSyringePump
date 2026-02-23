# 💉 SerialPump Toolkit

A collection of tools for controlling and programming syringe pumps — specifically the **NE-1000 Series** — via serial communication and custom script generation.

This repository currently includes:

- **NE-1000 PPL Step Composer**: A Streamlit-based UI for visually creating `.PPL` programs.
- **Python Serial Control Module** *(name TBD)*: A Python module to send commands directly to the NE-1000 pumps over a serial interface.

---

## 📟 NE-1000 PPL Step Composer (Streamlit UI)

The **Step Composer** provides a visual way to build `.PPL` programs for the NE-1000 pump series. Users can create steps like:

- Setting syringe diameter
- Continuous rate infusion/withdrawal
- Volume-based infusion
- Pauses, loops, and control commands

### ✅ Features

- Button-based step rearrangement
- Multi-pump support (up to 10 pumps)
- ZIP download of `.PPL` files, one per pump
- Parameter validation (e.g. volume/rate)
- Visual warnings if required settings (e.g. diameter) are missing
- Temporary in-session storage via Streamlit session state

### 🚀 Run the Composer Locally

Make sure you have Python and `streamlit` installed.

```bash
pip install streamlit
streamlit run PPLcomposer.py
```

> 📁 The UI will open in your browser. You can start building pump scripts interactively.

---

## 🧪 Python Serial Pump Control (Work in Progress)

This module will handle **direct serial communication** with NE-1000 pumps via Python, including:

- Detecting connected COM ports
- Sending commands and reading responses
- Executing `.PPL` files
- Batch execution across multiple pumps


### Planned Features

- Realtime pump status polling (WIP)


---

## 📄 License

[MIT License](LICENSE)

---

## 🙏 Acknowledgments

This project is inspired by the need for a more flexible and programmable interface to work with NE-1000 syringe pumps in research and automation settings. Built using [Streamlit](https://streamlit.io/) and `pyserial`.
