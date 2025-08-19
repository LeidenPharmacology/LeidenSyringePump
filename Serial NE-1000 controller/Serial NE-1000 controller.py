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


def send_commands_to_pump(name, commands):
    for cmd in commands:
        cmd = cmd.strip()
        if cmd and "*" not in cmd:
            Pumpcontroller.NewEraSyringePump.send_command(globals()[name], cmd)

def mainwindow(comlist):
    layout = [
        [sg.T("Select COM port"), sg.Combo(comlist, key= "comselect")],
        [sg.T("Import pump zip file"), sg.FileBrowse(file_types=(('ZIP', '*.zip'),), key='Browse')],
        [sg.B("Save input", button_color= "black on yellow"), sg.B("Start", button_color='green', disabled= True), sg.B("Close", button_color= 'tomato')]
         ]
    return sg.Window('Jasmine: Serial NE-1000 controller', layout, finalize = True) 


comlist = Serialfinder.serial_ports()

window1 = mainwindow(comlist)
window2_active = False

while True:
    window, event, values = sg.read_all_windows()
    
    #Stops everything when user uses the button cancel or closes the window
    if event == 'Close' or  event == sg.WIN_CLOSED:
        if window == window1:
            window.close()
            try:
                shared_serial.close()
                shared_serial = []
            except:
                print("OK")
            break
    
    if event == 'Save input':
        zipppl = values.get("Browse")
        Comport = values.get("comselect")
        
        #Unzipper
        data, lines, vars_dict = Unzipper.read_zip_contents(zipppl)
        
        #using the data gotten to split the lines per pump and 
        pump_jobs={}
        for i in vars_dict:
            if "_script" in i:
                linelist = vars_dict[i]
                i = i.removesuffix("_script")
                i = i.split("_")
                i = ''.join(i)
                pump_jobs[i] = linelist
                
            else:
                df = vars_dict[i]
                df = pd.read_csv(StringIO(df))

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
        
        window['Start'].update(disabled=False)
        window['Start'].update(button_color = 'green')
        
    if event == "Start":
        
        threads = []
    
        for pump in pump_jobs:
            # Assume each 'pump' is a string referring to a global variable
            pump_instance = globals()[pump]
        
            # Create a thread to run the command on this pump
            t = threading.Thread(
                target=Pumpcontroller.NewEraSyringePump.send_command,
                args=(pump_instance, "RUN")
            )
        
            t.start()  # Start the thread
            threads.append(t)  # Keep track of it
        
        # Wait for all threads to complete
        for t in threads:
            t.join()

        