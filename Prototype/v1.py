import serial
import time

class NewEraSyringePump:
    def __init__(self, serial_connection, address):
        self.pump_address = f"{int(address):02d}"
        self.ser = serial_connection

    def send_command(self, command):
        full_command = f"{self.pump_address}{command}\r\n"
        self.ser.write(full_command.encode())
        time.sleep(0.075)

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

    def reset_pump(self):
        self.send_command("RESET")

    def beep(self):
        self.send_command("BEP")


# ------- Usage Example ------- #

# Open a single serial connection
shared_serial = serial.Serial(
    port="COM4",
    baudrate=19200,
    parity=serial.PARITY_NONE,
    bytesize=8,
    stopbits=1,
    timeout=0.5,
    xonxoff=0,
    rtscts=0
)
time.sleep(0.075)

# Instantiate pumps with the same serial connection
pump0 = NewEraSyringePump(shared_serial, 0)
pump1 = NewEraSyringePump(shared_serial, 1)

# Setup pump0
pump0.reset_pump()
pump0.set_diameter(26.59)
pump0.run_RATE_function(500, "MH", 4, "ML", 0)

# Pause
time.sleep(10)

# Setup pump1
pump1.reset_pump()
pump1.set_diameter(26.59)
pump1.run_RATE_function(200, "MH", 2, "ML", 1)

# Clean exit
pump0.reset_pump()
pump1.reset_pump()
shared_serial.close()
