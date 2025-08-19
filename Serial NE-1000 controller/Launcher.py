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
import subprocess

#custommodules
from Custommodules import Unzipper
from Custommodules import Serialfinder
from Custommodules import Pumpcontroller

def mainwindow():
    layout = [
        [sg.T("What mode do you want to run?")],
        [sg.B("Simple controls", button_color="Green"), sg.P(), sg.B("Advanced controls", button_color="black on yellow"), sg.P(), sg.B("Setup", button_color="black on White"), sg.P(), sg.B("Quit", button_color = "tomato")],
        ]
    
    return sg.Window('Rajah', layout, finalize = True) 


window1 = mainwindow()
while True:
    window, event, values = sg.read_all_windows()
    
    if event == 'Quit' or  event == sg.WIN_CLOSED:
        if window == window1:
            window.close()
            break
        
    if event == "Simple controls":
        window1.hide()
        subprocess.run(["python", "Serial NE-1000 controller.py"])
        window1.UnHide()
        
    if event == "Advanced controls":
        window1.hide()
        subprocess.run(["python", "Advancedmode NE-1000.py"])
        window1.UnHide()
        
    if event == "Setup":
        window1.hide()
        subprocess.run(["python", "Pumpsetup.py"])
        window1.UnHide()