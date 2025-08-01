import serial
import time
import threading
import zipfile  
from pathlib import Path  
from collections import defaultdict 
import re
import FreeSimpleGUI as sg

#custommodules
from Custommodules import Unzipper
from Custommodules import Serialfinder
from Custommodules import Pumpcontroller

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
            break
    
    if event == 'Save input':
        zipppl = values.get("Browse")
        Comport = values.get("comselect")
        
        #Unzipper
        data, lines, vars_dict = Unzipper.read_zip_contents(zipppl)
        
        #using the data gotten to split the lines per pump and 
        pump_jobs={}
        for i in vars_dict:
            linelist = vars_dict[i]
            i = i.removesuffix("_script")
            i = i.split("_")
            i = ''.join(i)
            pump_jobs[i] = linelist

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
        
        #opening seperate pump channels with addresses
        y = 0
        for pump in pump_jobs:
            line = pump_jobs[pump]
            line = line.split('\n')
            name = pump
            globals()[name] =  Pumpcontroller.NewEraSyringePump(shared_serial, y)
            print(name + " Confirms", globals()[name].query_address())
            for x in line:
                x = x.strip()
                if not("*") in x and x:
                    Pumpcontroller.NewEraSyringePump.send_command(globals()[name], x)   
            y= y+1
        
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

        