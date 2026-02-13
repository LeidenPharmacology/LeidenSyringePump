import serial
import time
import threading

class NewEraSyringePump:
    _write_lock = threading.Lock()
    
    #Initializes the pump with the correct serial connection
    def __init__(self, serial_connection, address):
        self.pump_address = f"{int(address):02d}"
        self.ser = serial_connection
        print(f"[INIT] Pump initialized with address {self.pump_address}")
    
    #Sending commands with a sleep timer to give the pump time to respond
    def send_command(self, command):
        full_command = f"{self.pump_address}{command}\r\n"
        print(f"[SEND][{self.pump_address}] {full_command.strip()}")
        with NewEraSyringePump._write_lock:
            self.ser.write(full_command.encode())
        time.sleep(0.075)

    #Reads the response of the pump and gives that to the user. Normally not used in the NE-1000 simple controller 
    def read_response(self):
        with NewEraSyringePump._write_lock:
            response = self.ser.readline().decode('utf-8', errors='ignore').strip()
        if response:
            print(f"[RECV][{self.pump_address}] {response}")
        return response

    def verify_presence(self):
        self.send_command("VER")
        return self.read_response()

    def query_address(self):
        self.send_command("ADR")
        return self.read_response()

    def start_pump(self):
        self.send_command("RUN")

    def stop_pump(self):
        full_command = f"{self.pump_address}STP\r\n"
        print(f"[SEND][{self.pump_address}] STP")
        with NewEraSyringePump._write_lock:
            self.ser.write(full_command.encode())
        time.sleep(0.075)
        

    def set_diameter(self, diameter):
        self.send_command(f"DIA {diameter}")

    def set_rate(self, rate, r_units):
        self.send_command(f"RAT {rate} {r_units}")

    def set_volume(self, volume, units):
        self.send_command(f"VOL {volume} {units}")

    def set_direction(self, direction):
        if direction == 0:
            self.send_command("DIR INF")
        elif direction == 1:
            self.send_command("DIR WDR")
        elif direction == 2:
            self.send_command("DIR REV")

    def run_RATE_function(self, rate, rate_units, volume, units, direction):
        print(f"[START][{self.pump_address}] run_RATE_function")
        self.set_rate(rate, rate_units)
        self.set_volume(volume, units)
        self.set_direction(direction)
        self.start_pump()

        if rate_units == "MH" and units == "ML":
            pumping_duration = volume * 3600 / rate
        elif rate_units == "UH" and units == "UL":
            pumping_duration = volume * 3600 / rate
        elif rate_units == "MH" and units == "UL":
            pumping_duration = volume * 3.6 / rate
        elif rate_units == "UH" and units == "ML":
            pumping_duration = volume * 3.6 * 10**6 / rate
        elif rate_units == "MM" and units == "ML":
            pumping_duration = volume * 60 / rate
        elif rate_units == "UM" and units == "UL":
            pumping_duration = volume * 60 / rate
        elif rate_units == "MM" and units == "UL":
            pumping_duration = volume * 0.06 / rate
        elif rate_units == "UM" and units == "ML":
            pumping_duration = volume * 6 * 10**4 / rate
        else:
            raise ValueError(f"Unsupported units combination: {rate_units}, {units}")

        time.sleep(pumping_duration)
        self.stop_pump()
        print(f"[END][{self.pump_address}] run_RATE_function")

    def reset_pump(self):
        self.send_command("RESET")

    def safe_reset(self):
        print(f"[WARN] Skipping full reset to preserve pump address {self.pump_address}")
        self.send_command("STP")
        self.send_command("CLD")  # Clear dispense target
        self.send_command("CLT")  # Clear target volume

    def beep(self):
        self.send_command("BEP")

