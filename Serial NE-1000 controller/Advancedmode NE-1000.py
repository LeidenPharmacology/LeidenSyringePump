# file: advancedmode_ne_1000.py

import serial
import threading
import FreeSimpleGUI as sg
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta
import time

# custom modules
from Custommodules import Unzipper
from Custommodules import Serialfinder
from Custommodules import Pumpcontroller


# ---- PHASE TRACKING ----
def get_pump_phase(pump_id, schedule, now, sim_start):
    for _, row in schedule.iterrows():
        start = sim_start + row["Start Time"]
        end = start + timedelta(seconds=row["Duration (s)"])
        if start <= now < end:
            remaining = end - now
            elapsed = now - start
            total = end - start
            progress = int((elapsed.total_seconds() / total.total_seconds()) * 100)
            return (f"Phase {int(row['Step'])}: {row['Description']} "
                    f"({str(remaining).split('.')[0]} left)", "white", progress)
        if now < start:
            wait = start - now
            return f"Waiting (starts in {str(wait).split('.')[0]})", "yellow", 0
    return "Completed", "red", 100


def send_commands_to_pump(name, commands):
    print("sending commands")
    for cmd in commands:
        cmd = cmd.strip()
        if cmd and "*" not in cmd:
            print("test")
            print(cmd)
            Pumpcontroller.NewEraSyringePump.send_command(globals()[name], cmd)


def mainwindow(comlist):
    layout = [
        [sg.T("Select COM port"), sg.Combo(comlist, key="comselect")],
        [sg.T("Import pump zip file"), sg.FileBrowse(file_types=(('ZIP', '*.zip'),), key='Browse')],
        [sg.B("Save input", button_color="black on yellow"), sg.P(), sg.B("Close", button_color='tomato')],
    ]
    return sg.Window('Jasmine: Serial NE-1000 controller', layout, finalize=True)


def Pumpwindow(pump_count):
    pump_columns = []

    for i in range(pump_count):
        col = sg.Column([
            [sg.Text(f"Pump{i+1}", size=(40, 1), justification='center', relief='ridge')],
            [sg.Text("Current phase", key=f"PHASE_{i}", size=(40, 1), justification='center', relief='ridge')],
            [sg.ProgressBar(100, orientation='h', size=(25, 20), key=f"PROGRESS_{i}")]
        ], element_justification='center', pad=(10, 10))

        pump_columns.append(col)

    # Put all pump columns in one row
    layout = [
        pump_columns,
        [sg.Push(),
         sg.Button("Start", button_color=("white", "green"), size=(10, 2)),
         sg.Button("Pause", button_color=("white", "purple"), size=(10, 2), disabled=True),
         sg.Button("Resume", button_color=("white", "blue"), size=(10, 2), disabled=True),
         sg.Button("Stop", button_color=("white", "red"), size=(10, 2)),
         sg.Push()]
    ]

    return sg.Window('Genie: NE-1000 Advanced controller', layout, finalize=True)


# ---- MAIN PROGRAM ----
comlist = Serialfinder.serial_ports()

window1 = mainwindow(comlist)
window2 = None
window1_active = True
window2_active = False

pump_jobs = {}
pump_schedules = {}
shared_serial = None
sim_running = False
sim_paused = False
sim_start = None
paused_elapsed = timedelta(0)  # total time already elapsed before pause

while True:
    window, event, values = sg.read_all_windows(timeout=200)  # refresh every 0.5s

    if event == sg.WIN_CLOSED or event in ("Close", "Stop"):
        if window == window1:
            window.close()
            window1_active = False

        elif window == window2 and window2_active:
            for name in pump_jobs:
                Pumpcontroller.NewEraSyringePump.safe_reset(globals()[name])
                time.sleep(0.1)
            window.close()
            if shared_serial:
                shared_serial.close()
            window2_active = False
            window1_active = False
            break

    if event == "Save input":
        zipppl = values.get("Browse")
        Comport = values.get("comselect")

        # Unzipper
        data, lines, vars_dict = Unzipper.read_zip_contents(zipppl)

        pump_jobs = {}
        pump_schedules = {}

        for i in vars_dict:
            if "_script" in i:
                linelist = vars_dict[i]
                i = i.removesuffix("_script")
                i = i.split("_")
                i = ''.join(i)
                pump_jobs[i] = linelist

            else:
                df = pd.read_csv(StringIO(vars_dict[i]))
                pumpnum = []
                for i in df["Pump"]:
                    if i not in pumpnum:
                        pumpnum.append(i)
                    x = "Pump" + str(i)
                    res = df[df["Pump"] == i].copy()

                    # Parse schedule properly
                    res["Start Time"] = pd.to_timedelta(res["Start Time"], errors="coerce")
                    res["Duration (s)"] = pd.to_numeric(res["Duration (s)"], errors="coerce").fillna(0)

                    globals()[x] = res[["Step", "Start Time", "Duration (s)", "Description"]]
                    pump_schedules[x] = globals()[x]

        # serial connection
        shared_serial = serial.Serial(
            port=Comport,
            baudrate=19200,
            parity=serial.PARITY_NONE,
            bytesize=8,
            stopbits=1,
            timeout=0.5,
            xonxoff=0,
            rtscts=0
        )

        time.sleep(0.075)

        y = 0
        threads = []

        for pump in pump_jobs:
            line = pump_jobs[pump].split('\n')
            name = pump
            globals()[name] = Pumpcontroller.NewEraSyringePump(shared_serial, y)
            print(name + " Confirms", globals()[name].query_address())

            thread = threading.Thread(target=send_commands_to_pump, args=(name, line))
            thread.start()
            threads.append(thread)
            y += 1

        for thread in threads:
            thread.join()

        window.close()
        window1_active = False
        window2 = Pumpwindow(len(pump_schedules))
        window2_active = True

    if event == "Start":
        sim_start = datetime.now() - paused_elapsed

        threads = []
        for pump in pump_jobs:
            pump_instance = globals()[pump]
            thread = threading.Thread(
                target=Pumpcontroller.NewEraSyringePump.send_command,
                args=(pump_instance, "RUN")
            )
            thread.start()
            threads.append(thread)

        sim_running = True
        sim_paused = False
        sim_start = datetime.now()
        window['Pause'].update(disabled=False)
        window['Start'].update(disabled=True)
        window['Resume'].update(disabled=True)
        
    if event == "Pause":
        threads = []
        for pump in pump_jobs:
            pump_instance = globals()[pump]
            thread = threading.Thread(
                target=Pumpcontroller.NewEraSyringePump.send_command,
                args=(pump_instance, "STP")
            )
            thread.start()
            threads.append(thread)

        for t in threads:
            t.join()

        pause_time = datetime.now()
        paused_elapsed = pause_time - sim_start

        sim_paused = True
        window['Pause'].update(disabled=True)
        window['Resume'].update(disabled=False)

    if event == "Resume":
        sim_start = datetime.now() - paused_elapsed
        paused = False

        threads = []
        for pump in pump_jobs:
            pump_instance = globals()[pump]
            thread = threading.Thread(
                target=Pumpcontroller.NewEraSyringePump.send_command,
                args=(pump_instance, "RUN")
            )
            thread.start()
            threads.append(thread)

        sim_paused = False
        window['Pause'].update(disabled=False)
        window['Resume'].update(disabled=True)

    # ---- Refresh phases live ----
    if sim_running and not sim_paused and sim_start:
        now = datetime.now()
        for i, (pump, schedule) in enumerate(pump_schedules.items()):
            phase_text, phase_color, progress = get_pump_phase(pump, schedule, now, sim_start)
            window2[f"PHASE_{i}"].update(phase_text, text_color=phase_color)
            window2[f"PROGRESS_{i}"].update_bar(progress)
