import socket
import selectors
import logging
import types
import json
import board
import busio
import adafruit_sht31d
import adafruit_ads1x15.ads1015 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_seesaw.seesaw import Seesaw
from simpleio import map_range


# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
slogger = logging.getLogger("(srv)")
slogger.setLevel(level=logging.INFO)

# Initialize I2C bus and sensors
i2c = busio.I2C(board.SCL, board.SDA)
sht30_sensor = adafruit_sht31d.SHT31D(i2c)
ss_sensor = Seesaw(i2c, addr=0x36)
ads = ADS.ADS1015(i2c)
chan = AnalogIn(ads, ADS.P0)

def get_wind_speed(voltage):
    """Convert anemometer voltage to wind speed."""
    wind_speed = map_range(voltage, 0.4, 2.0, 0.0, 32.4)
    return wind_speed

class Server:
    def __init__(self, host, port):
        slogger.debug("Initializing server...")
        self.sel = selectors.DefaultSelector()
        self.host = host
        self.port = port
        slogger.info("Server initialized.")

    def run(self):
        slogger.debug("Starting server...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen()
        slogger.info(f"Listening on {self.host}:{self.port}.")
        sock.setblocking(False)
        self.sel.register(sock, selectors.EVENT_READ, data=None)
        slogger.debug("Monitoring set.")
        try:
            while True:
                events = self.sel.select(timeout=None)
                for key, mask in events:
                    if key.data is None:
                        self.accept_wrapper(key.fileobj)
                    else:
                        self.service_connection(key, mask)
        except KeyboardInterrupt:
            slogger.info("Caught keyboard interrupt, exiting...")
        finally:
            self.sel.close()

    def accept_wrapper(self, sock):
        conn, addr = sock.accept()
        slogger.debug(f"Accepted connection from {addr}.")
        conn.setblocking(False)
        data = types.SimpleNamespace(addr=addr, inb=b"", outb=b"")
        events = selectors.EVENT_READ | selectors.EVENT_WRITE
        self.sel.register(conn, events, data=data)

    def service_connection(self, key, mask):
        sock = key.fileobj
        data = key.data
        if mask & selectors.EVENT_READ:
            recv_data = sock.recv(1024)
            if recv_data:
                data.inb += recv_data
                # Check if complete message received
                if b"\n" in data.inb:
                    message = data.inb.decode().strip()
                    if message == "Requesting data":
                        # Collect sensor data
                        try:
                            temp = sht30_sensor.temperature
                            humidity = sht30_sensor.relative_humidity
                            soil_moisture = ss_sensor.moisture_read()
                            soil_temp = ss_sensor.get_temp()
                            voltage = chan.voltage
                            wind_speed = get_wind_speed(voltage)
                            response = {
                                "temperature": temp,
                                "humidity": humidity,
                                "soil_moisture": soil_moisture,
                                "soil_temperature": soil_temp,
                                "wind_speed": wind_speed
                            }
                            data.outb = (json.dumps(response) + "\n").encode()
                        except Exception as e:
                            slogger.error(f"Sensor error: {e}")
                            data.outb = (json.dumps({"error": str(e)}) + "\n").encode()
                    else:
                        data.outb = (json.dumps({"error": "Invalid request"}) + "\n").encode()
                    data.inb = b""  # Clear input buffer
            else:
                slogger.debug(f"Closing connection to {data.addr}")
                self.sel.unregister(sock)
                sock.close()
        if mask & selectors.EVENT_WRITE:
            if data.outb:
                sent = sock.send(data.outb)
                data.outb = data.outb[sent:]
                if not data.outb:
                    self.unregister_and_close(sock)

    def unregister_and_close(self, sock):
        slogger.debug("Closing connection...")
        try:
            self.sel.unregister(sock)
        except Exception as e:
            slogger.error(f"Socket could not be unregistered: {e}")
        try:
            sock.close()
        except OSError as e:
            slogger.error(f"Socket could not close: {e}")

if __name__ == "__main__":
    # Replace with appropriate host and port for each secondary Pi
    # server = Server("169.233.149.210", 5557)  # Secondary 1: 5555, Secondary 2: 5556
    server = Server("169.233.13.1", 5557)
    server.run()
