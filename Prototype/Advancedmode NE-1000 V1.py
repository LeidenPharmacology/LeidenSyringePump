import serial
import time
import threading
import zipfile  
from pathlib import Path  
from collections import defaultdict 
import re
import FreeSimpleGUI as sg
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta
import time

#custommodules
from Custommodules import Unzipper
from Custommodules import Serialfinder
from Custommodules import Pumpcontroller

# ---- PHASE TRACKING ----
def get_pump_phase(pump_id, schedule, now, sim_start):
    for _, row in schedule.iterrows():
        start = sim_start + row["Start Time"]   # row["Start Time"] is a timedelta
        end = start + timedelta(seconds=row["Duration (s)"])
        if start <= now < end:
            remaining = end - now
            return f"Phase {int(row['Step'])}: {row['Description']} ({str(remaining).split('.')[0]} left)", "green"
        if now < start:
            wait = start - now
            return f"Waiting (starts in {str(wait).split('.')[0]})", "yellow"
    return "Completed", "red"

def send_commands_to_pump(name, commands):
    for cmd in commands:
        cmd = cmd.strip()
        if cmd and "*" not in cmd:
            Pumpcontroller.NewEraSyringePump.send_command(globals()[name], cmd)

def mainwindow(comlist):
    layout = [
        [sg.T("Select COM port"), sg.Combo(comlist, key= "comselect")],
        [sg.T("Import pump zip file"), sg.FileBrowse(file_types=(('ZIP', '*.zip'),), key='Browse')],
        [sg.B("Save input", button_color= "black on yellow"), sg.P(), sg.B("Close", button_color= 'tomato')]
         ]
    return sg.Window('Jasmine: Serial NE-1000 controller', layout, finalize = True)

def Pumpwindow(pump_count):
    pump_rows = []

    # Pump labels
    pump_labels = [sg.Text(f"Pump{i+1}", size=(30, 1), justification='center', relief='ridge') for i in range(pump_count)]
    pump_rows.append(pump_labels)
    
    # Current phase labels
    phase_labels = [sg.Text("Current phase", key=f"PHASE_{i}", size=(30, 1), justification='center', relief='ridge') for i in range(pump_count)]
    pump_rows.append(phase_labels)
    
    # Control buttons
    controls = [
        sg.Button("Start", button_color=("white", "green"), size=(10, 2)),
        sg.Button("Pause", button_color=("white", "purple"), size=(10, 2), disabled= True),
        sg.Button("Stop", button_color=("white", "red"), size=(10, 2))
    ]
    pump_rows.append([sg.Push(), *controls, sg.Push()])

    layout = pump_rows
    
    return sg.Window('Genie: NE-1000 Advanced controller', layout, finalize = True)

comlist = Serialfinder.serial_ports()

window1 = mainwindow(comlist)
window2 = None
pump_jobs={}
window2_active = False
pump_schedules = {}

while True:
    window, event, values = sg.read_all_windows(timeout=500)
    
    if event == 'Close' or event == 'Stop' or sg.WIN_CLOSED:
        if window == window1:
            window.close()
            window1_active = False
            
        elif window == window2 and window2_active == True:
            for name in pump_jobs:
                Pumpcontroller.NewEraSyringePump.safe_reset(globals()[name])
                time.sleep(0.1)
            window.close()
            shared_serial.close()
            window2_active = False
            window1_active = False
            window.close()
            break
            
            
    if event == 'Save input':
        zipppl = values.get("Browse")
        Comport = values.get("comselect")
        
        #Unzipper
        data, lines, vars_dict = Unzipper.read_zip_contents(zipppl)
        
        #using the data gotten to split the lines per pump and 
        pump_jobs={}
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
                    x = i
                    x = "Pump"+ str(x)
                
                res = df[df["Pump"] == i].copy()
                
                # Ensure Start Time is a timedelta
                res["Start Time"] = pd.to_timedelta(res["Start Time"], errors="coerce")
                
                # Ensure Duration is numeric (seconds)
                res["Duration (s)"] = pd.to_numeric(res["Duration (s)"], errors="coerce").fillna(0)
                
                pump_schedules[x] = res
                
        #start of the preparations for serial connections
        shared_serial = serial.Serial(
            port= Comport,
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
        
            # Create and start a thread to send commands for this pump
            thread = threading.Thread(target=send_commands_to_pump, args=(name, line))
            thread.start()
            threads.append(thread)

            y += 1

        
        # Wait for all threads to finish
        for thread in threads:
            thread.join()
        
        window.close()
        window1_active = False
        window2 = Pumpwindow(2)
        window2_active = True
    
    if event == "Start":
        sim_start = datetime.now()
        Started = True
        threads = []
    
        for pump in pump_jobs:
            # Assume each 'pump' is a string referring to a global variable
            pump_instance = globals()[pump]
        
            # Create a thread to run the command on this pump
            thread = threading.Thread(
                target=Pumpcontroller.NewEraSyringePump.send_command,
                args=(pump_instance, "RUN")
            )
        
            thread.start()  # Start the thread
            threads.append(thread)  # Keep track of it
        
# =============================================================================
#         # Wait for all threads to complete
#         for t in threads:
#             t.join()
# =============================================================================
        
        #when start is pressed pause must be done
        window['Pause'].update(disabled=False)
        window['Start'].update(disabled=True)

        
    if event == "Pause":
        threads = []
        
        # Similar to the start command the pause command can just be send once. And needs to be done according to each pumpcontroller instance. Therefore we need to use the global as the pump instance.
        for pump in pump_jobs:
            pump_instance = globals()[pump]
            
            thread = threading.Thread(
                target=Pumpcontroller.NewEraSyringePump.send_command,
                args=(pump_instance, "STP")
            )
            
            thread.start()  # Start the thread
            threads.append(thread)  # Keep track of it
        
# =============================================================================
#         # Wait for all threads to complete
#         for t in threads:
#             t.join()
# =============================================================================
        
        #when Pause is pressed, Start must be enabled to be pressed. 
        window['Pause'].update(disabled=True)
        window['Start'].update(disabled=False)
        
        if window2_active and window == window2 and Started == True:
            print("active")
            now = datetime.now()
            for i, (pump, schedule) in enumerate(pump_schedules.items()):
                phase_text, phase_color = get_pump_phase(pump, schedule, now, sim_start)
                window2[f"PHASE_{i}"].update(phase_text, text_color=phase_color)
        