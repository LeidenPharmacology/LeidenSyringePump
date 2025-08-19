import serial
import time
import FreeSimpleGUI as sg
from Custommodules import Serialfinder

def send_command(cmd: str):
    """Send command to pump and return reply"""
    full_cmd = cmd + "\r"  # must end with carriage return
    shared_serial.write(full_cmd.encode("ascii"))
    time.sleep(0.1)
    try:
        reply = shared_serial.read_all().decode("ascii").strip()
    except:
        reply = "Set"
    return reply

def Mainwindow(comlist):
    adresslist = ["Pump 1", "Pump 2", "Pump 3", "Pump 4", "Pump 5", "Pump 6", "Pump 7", "Pump 8", "Pump 9", "Pump 10"]

    layout = [
        [sg.T("Select Comport"), sg.Combo(comlist, key= "comselect")],
        [sg.T("Pump Name"), sg.Combo(adresslist, key = "adressselect", disabled= True)],
        [sg.B("Connect", key = "Connect"), sg.P(), sg.B("Set adress", key = "set", disabled=True), sg.P(), sg.B("Quit")]
        ]
    
    return sg.Window("Pump setup", layout, finalize = True)


comlist = Serialfinder.serial_ports()

window1 = Mainwindow(comlist)

while True:
    window, event, values = sg.read_all_windows()
    
    # Closing window
    if event == 'Quit' or  event == sg.WIN_CLOSED:
        try:
            shared_serial.close()
            shared_serial = {}
        except:
            print("OK")
        window1.close()
        break
        
    if event == "Connect":
        comport = values.get("comselect")
        
        # Open serial connection
        shared_serial = serial.Serial(
            port=comport,       # Change to your port
            baudrate=19200,
            parity=serial.PARITY_NONE,
            bytesize=8,
            stopbits=1,
            timeout=0.5,
            xonxoff=0,
            rtscts=0
        )
        
        # Setting up the Buttons
        window["set"].update(disabled=False)
        window["adressselect"].update(disabled=False)
        window["comselect"].update(disabled=True)
        window["Connect"].update(disabled=True)
    
    #set command
    if event == "set":
        #hard coded since no energy to do this more elegant
        adressdict = {"Pump 1": "*ADR00", "Pump 2": "*ADR01", "Pump 3": "*ADR02", "Pump 4": "*ADR03", "Pump 5": "*ADR04", "Pump 6": "*ADR05", "Pump 7": "*ADR006", "Pump 8": "*ADR07", "Pump 9": "*ADR08", "Pump 10": "*ADR09"}
        
        pumpselection = values.get("adressselect")
        
        # Example: set pump address to 1
        reply = send_command(adressdict[pumpselection])
        print("Pump replied:", reply)
        
        sg.popup(f"{pumpselection} has been set; Plug in the next pump and set the next address")