import serial
import time
import threading

class NewEraSyringePump:
    _write_lock = threading.Lock()

    def __init__(self, serial_connection, address):
        self.pump_address = f"{int(address):02d}"
        self.ser = serial_connection
        print(f"[INIT] Pump initialized with address {self.pump_address}")

    def send_command(self, command):
        full_command = f"{self.pump_address}{command}\r\n"
        print(f"[SEND][{self.pump_address}] {full_command.strip()}")
        with NewEraSyringePump._write_lock:
            self.ser.write(full_command.encode())
        time.sleep(0.075)

    def read_response(self):
        with NewEraSyringePump._write_lock:
            response = self.ser.readline().decode().strip()
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
        self.send_command("STP")

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


# =============================================================================
# # ------- Usage Example ------- #
# 
# shared_serial = serial.Serial(
#     port="COM4",
#     baudrate=19200,
#     parity=serial.PARITY_NONE,
#     bytesize=8,
#     stopbits=1,
#     timeout=0.5,
#     xonxoff=0,
#     rtscts=0
# )
# time.sleep(0.075)
# 
# for addr in range(10):
#     test_pump = NewEraSyringePump(shared_serial, addr)
#     response = test_pump.verify_presence()
#     if response:
#         print(f"Pump {addr:02d} is present: {response}")
#     else:
#         print(f"Pump {addr:02d} not found or no response")
#     time.sleep(0.25)
# 
# pump0 = NewEraSyringePump(shared_serial, 0)
# pump1 = NewEraSyringePump(shared_serial, 1)
# 
# print("Pump 0 confirms: ", pump0.query_address())
# print("Pump 1 confirms: ", pump1.query_address())
# 
# pump0.reset_pump()
# pump0.set_diameter(26.59)
# pump1.safe_reset()
# pump1.set_diameter(26.59)
# 
# pump_jobs = [
#     (pump0, (500, "MH", 4, "ML", 0)),
#     (pump1, (250, "MH", 2, "ML", 1)),
# ]
# 
# threads = []
# for pump, args in pump_jobs:
#     t = threading.Thread(target=pump.run_RATE_function, args=args)
#     t.start()
#     threads.append(t)
# 
# for t in threads:
#     t.join()
# 
# shared_serial.close()
# 
# =============================================================================
