import socket
import json
import time
import logging
import sys
import selectors
import types
import matplotlib.pyplot as plt
import numpy as np
import board
import busio
import adafruit_sht31d
from adafruit_seesaw.seesaw import Seesaw
import adafruit_ads1x15.ads1015 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from simpleio import map_range
from datetime import datetime  # Added for timestamp
# LABEL: Import MySQL Connector
# Where: Top of file, with other imports (originally lines 1-15)
# What: Added import for mysql.connector
# Why: Required to use MySQL Python Connector for database operations (tutorial: "Installing MySQL Connector/Python")
import mysql.connector

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("(token-ring)")
logger.setLevel(level=logging.INFO)

class TokenRingNode:
    def __init__(self, pi_id, host_ip, host_port, next_host_ip, next_host_port, other_host_ip, other_host_port, is_db_connector=False):
        self.pi_id = pi_id  # Pi identifier (1, 2, or 3)
        self.host = host_ip  # This Pi's server host (for receiving)
        self.port = host_port  # This Pi's server port (for receiving)
        self.next_host = next_host_ip  # Next Pi's host (for sending)
        self.next_port = next_host_port  # Next Pi's port (for sending)
        self.other_host = other_host_ip
        self.other_port = other_host_port
        self.plotter = 3
        self.numpis = 3
        self.sel = selectors.DefaultSelector()
        self.round = 0  # Track the round number for plotting
        self.is_db_connector = is_db_connector

        # Initialize sensors
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            self.sht30_sensor = adafruit_sht31d.SHT31D(i2c)
            self.ss_sensor = Seesaw(i2c, addr=0x36)
            self.ads = ADS.ADS1015(i2c)
            self.chan = AnalogIn(self.ads, ADS.P0)
            logger.info(f"Pi #{self.pi_id} sensors initialized.")
        except Exception as e:
            logger.error(f"Pi #{self.pi_id} failed to initialize sensors: {e}")
            self.sht30_sensor = None
            self.ss_sensor = None
            self.ads = None
            self.chan = None

        
        self.db_conn = None
        if self.is_db_connector:
            self.connect_db()


    def connect_db(self):
        try:
            self.db_conn = mysql.connector.connect(
                host="169.233.139.6",  
                user="root",
                password="",  
                database="piSenseDB"
            )
            logger.info(f"Pi #{self.pi_id} connected to piSenseDB database.")
        except mysql.connector.Error as e:
            logger.error(f"Pi #{self.pi_id} failed to connect to piSenseDB: {e}")
            self.db_conn = None

    def collect_sensor_data(self):
        """Collect sensor data from this Pi."""
        data = {}
        if self.sht30_sensor and self.ss_sensor and self.ads and self.chan:
            try:
                data["temperature"] = self.sht30_sensor.temperature
                data["humidity"] = self.sht30_sensor.relative_humidity
                data["soil_moisture"] = self.ss_sensor.moisture_read()
                data["soil_temperature"] = self.ss_sensor.get_temp()
                voltage = self.chan.voltage
                wind_speed = map_range(voltage, 0.4, 2.0, 0.0, 32.4)
                data["wind_speed"] = max(0.0, wind_speed)
                logger.info(f"Pi #{self.pi_id} sensor data: {data}")
            except Exception as e:
                logger.error(f"Pi #{self.pi_id} error reading sensors: {e}")
                data = {
                    "temperature": 0.0,
                    "humidity": 0.0,
                    "soil_moisture": 0.0,
                    "soil_temperature": 0.0,
                    "wind_speed": 0.0
                }
        else:
            data = {
                "temperature": 0.0,
                "humidity": 0.0,
                "soil_moisture": 0.0,
                "soil_temperature": 0.0,
                "wind_speed": 0.0
            }
        return data

    def start_server(self):
        """Start the server to listen for incoming messages."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen()
        logger.info(f"Pi #{self.pi_id} listening on {self.host}:{self.port}.")
        sock.setblocking(False)
        self.sel.register(sock, selectors.EVENT_READ, data=None)
        return sock

    def accept_wrapper(self, sock):
        """Accept incoming connections."""
        sock.settimeout(5)
        conn, addr = sock.accept()
        logger.debug(f"Pi #{self.pi_id} accepted connection from {addr}.")
        conn.setblocking(False)
        data = types.SimpleNamespace(addr=addr, inb=b"", outb=b"")
        events = selectors.EVENT_READ | selectors.EVENT_WRITE
        self.sel.register(conn, events, data=data)

    def service_connection(self, key, mask):
        """Service an existing connection."""
        sock = key.fileobj
        data = key.data
        if mask & selectors.EVENT_READ:
            sock.settimeout(5)
            recv_data = sock.recv(1024)
            if recv_data:
                data.inb += recv_data
                if b"\n" in data.inb:
                    message = data.inb.decode().strip()
                    self.handle_message(message)
                    data.inb = b""
            else:
                logger.debug(f"Pi #{self.pi_id} closing connection to {data.addr}")
                self.sel.unregister(sock)
                sock.close()
        if mask & selectors.EVENT_WRITE:
            if data.outb:
                sent = sock.send(data.outb)
                data.outb = data.outb[sent:]
                if not data.outb:
                    self.sel.unregister(sock)
                    sock.close()

    def handle_message(self, message):
        """Handle incoming messages."""
        logger.info(f"Pi #{self.pi_id} received message: {message}")
        try:
            msg_data = json.loads(message)
        except json.JSONDecodeError:
            logger.error(f"Pi #{self.pi_id} failed to decode message: {message}")
            return

        if msg_data.get("type") == "sensor_data":
            all_data = []
            received_data = msg_data.get("data", [])
            if isinstance(received_data, dict) and "data" in received_data:
                received_data = received_data["data"]
            if not isinstance(received_data, list):
                logger.error(f"Pi #{self.pi_id} received invalid 'data' format: {received_data}")
                all_data = []
            else:
                all_data = received_data

            my_data = self.collect_sensor_data()
            all_data.append({"pi_id": self.pi_id, "measurements": my_data})
            logger.debug(f"Pi #{self.pi_id} updated all_data: {all_data}")

            if self.pi_id == self.plotter:
                self.round += 1
                self.plot_data(all_data)
                self.send_message(None, "continue", self.next_host, self.next_port, (self.pi_id % 3)+1)
            else:
                next_pi_id = (self.pi_id % 3) + 1
                self.send_message(all_data, "sensor_data", self.next_host, self.next_port, pi_id=next_pi_id)
        elif msg_data.get("type") == "kill":
            logger.info(f"Plotting Pi killed, switching plotter...")
            self.plotter = self.plotter - 1
            if self.numpis > 1:
                self.numpis -= 1
            if self.pi_id == self.plotter:
                self.connect_db()
           
        elif msg_data.get("type") == "gone":
            if self.numpis > 1:
                self.numpis -= 1
            logger.info(f"Pi #{self.pi_id} starting round {self.round + 1}")
            self.round += 1
            time.sleep(5)
            my_data = self.collect_sensor_data()
            self.send_message([{"pi_id": self.pi_id, "measurements": my_data}], "sensor_data", self.next_host, self.next_port, pi_id=(self.pi_id+1)%3)
       
        elif msg_data.get("type") == "oneless":
            logger.info(f"One Pi disconnected...")
            if self.numpis > 1:
                self.numpis -= 1

        elif msg_data.get("type") == "continue":
            logger.info(f"Pi #{self.pi_id} starting round {self.round + 1}")
            self.round += 1
            time.sleep(5)
            my_data = self.collect_sensor_data()
            self.send_message([{"pi_id": self.pi_id, "measurements": my_data}], "sensor_data", self.next_host, self.next_port, pi_id=(self.pi_id+1)%3)

    def send_message(self, message, msg_type, next_host, next_port, pi_id):
        """Send a message to the specified Pi."""
        logger.debug(f"Pi #{self.pi_id} attempting to connect to {self.next_host}:{self.next_port}")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((next_host, next_port))
                msg = {"type": msg_type, "data": message}
                sock.sendall((json.dumps(msg) + "\n").encode())
                logger.info(f"Pi #{self.pi_id} sent {msg_type} message to Pi #{pi_id}")
        except Exception as e:
            logger.error(f"Pi #{self.pi_id} failed to send message to Pi #{pi_id}: {e}")
            time.sleep(3)
            logger.info(f"Attempting to send to next Pi...")
            if (next_host != self.other_host and next_port != self.other_port):
                self.send_message(message, msg_type, self.other_host, self.other_port, (pi_id+1)%3)
            else:
                logger.error(f"No Pis detected, shutting down")
                exit(1)

    def plot_data(self, all_data):
        """Plot the accumulated sensor data (called by Pi #3)."""
        if len(all_data) < 2:
            logger.warning(f"Pi #{self.pi_id} insufficient data for plotting: {all_data}")
            return

        pi_data = {d["pi_id"]: d["measurements"] for d in all_data}

        if self.pi_id == self.plotter:
            try:
                cursor = self.db_conn.cursor()
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for pi_id in [1, 2, 3]:
                    data = pi_data.get(pi_id, {})
                    table = f"sensor_readings{pi_id}"
                    query = (f"INSERT INTO {table} (timestamp, temperature, humidity, soil_moisture, wind_speed) "
                             "VALUES (%s, %s, %s, %s, %s)")
                    values = (
                        timestamp,
                        data.get("temperature", 0.0),
                        data.get("humidity", 0.0),
                        data.get("soil_moisture", 0.0),
                        data.get("wind_speed", 0.0)
                    )
                    cursor.execute(query, values)
                    logger.info(f"Pi #{self.pi_id} inserted Pi #{pi_id} data into {table}.")
                self.db_conn.commit()
                logger.info(f"Pi #{self.pi_id} database transaction committed.")
                cursor.close()
            except mysql.connector.Error as e:
                logger.error(f"Pi #{self.pi_id} database error: {e}")
                # Continue token ring even if database fails (robustness)
            except Exception as e:
                logger.error(f"Pi #{self.pi_id} unexpected error during database operation: {e}")

        temp1 = pi_data.get(1, {}).get("temperature", 0.0)
        temp2 = pi_data.get(2, {}).get("temperature", 0.0)
        temp3 = pi_data.get(3, {}).get("temperature", 0.0)

        hum1 = pi_data.get(1, {}).get("humidity", 0.0)
        hum2 = pi_data.get(2, {}).get("humidity", 0.0)
        hum3 = pi_data.get(3, {}).get("humidity", 0.0)

        soil1 = pi_data.get(1, {}).get("soil_moisture", 0.0)
        soil2 = pi_data.get(2, {}).get("soil_moisture", 0.0)
        soil3 = pi_data.get(3, {}).get("soil_moisture", 0.0)

        wind1 = pi_data.get(1, {}).get("wind_speed", 0.0)
        wind2 = pi_data.get(2, {}).get("wind_speed", 0.0)
        wind3 = pi_data.get(3, {}).get("wind_speed", 0.0)

        temp_avg = (temp1 + temp2 + temp3) / self.numpis
        hum_avg = (hum1 + hum2 + hum3) / self.numpis
        soil_avg = (soil1 + soil2 + soil3) / self.numpis
        wind_avg = (wind1 + wind2 + wind3) / self.numpis

        x_positions = [1, 2, 3, 4]
        x_labels = ["Pi #1", "Pi #2", "Pi #3", "Avg"]

        plt.figure(figsize=(10, 8))

        plt.subplot(2, 2, 1)
        plt.scatter([1], [temp1], color='red', s=100, label='Pi #1')
        plt.scatter([2], [temp2], color='green', s=100, label='Pi #2')
        plt.scatter([3], [temp3], color='blue', s=100, label='Pi #3')
        plt.scatter([4], [temp_avg], color='black', s=100, label='Avg')
        plt.title('Temperature Sensor')
        plt.ylabel('Temperature (°C)')
        plt.xticks(x_positions, x_labels)

        plt.subplot(2, 2, 2)
        plt.scatter([1], [hum1], color='red', s=100, label='Pi #1')
        plt.scatter([2], [hum2], color='green', s=100, label='Pi #2')
        plt.scatter([3], [hum3], color='blue', s=100, label='Pi #3')
        plt.scatter([4], [hum_avg], color='black', s=100, label='Avg')
        plt.title('Humidity Sensor')
        plt.ylabel('Humidity (%)')
        plt.xticks(x_positions, x_labels)

        plt.subplot(2, 2, 3)
        plt.scatter([1], [soil1], color='red', s=100, label='Pi #1')
        plt.scatter([2], [soil2], color='green', s=100, label='Pi #2')
        plt.scatter([3], [soil3], color='blue', s=100, label='Pi #3')
        plt.scatter([4], [soil_avg], color='black', s=100, label='Avg')
        plt.title('Soil Moisture Sensor')
        plt.ylabel('Soil Moisture')
        plt.xticks(x_positions, x_labels)

        plt.subplot(2, 2, 4)
        plt.scatter([1], [wind1], color='red', s=100, label='Pi #1')
        plt.scatter([2], [wind2], color='green', s=100, label='Pi #2')
        plt.scatter([3], [wind3], color='blue', s=100, label='Pi #3')
        plt.scatter([4], [wind_avg], color='black', s=100, label='Avg')
        plt.title('Wind Speed Sensor')
        plt.ylabel('Wind Speed (m/s)')
        plt.xticks(x_positions, x_labels)

        plt.tight_layout()
        try:
            plt.savefig(f'token-plot-{self.round}.png', bbox_inches='tight')
            logger.info(f"Pi #{self.pi_id} saved plot: token-plot-{self.round}.png")
        except Exception as e:
            logger.error(f"Pi #{self.pi_id} failed to save plot: {e}")
        plt.close()

    def run(self):
        """Run the token-ring node."""
        server_sock = self.start_server()

        if self.pi_id == 1:
            my_data = self.collect_sensor_data()
            self.send_message([{"pi_id": 1, "measurements": my_data}], "sensor_data", self.next_host, self.next_port, pi_id=2)

        try:
            while True:
                events = self.sel.select(timeout=None)
                for key, mask in events:
                    if key.data is None:
                        self.accept_wrapper(key.fileobj)
                    else:
                        self.service_connection(key, mask)
        except KeyboardInterrupt:
            if self.pi_id == 3:
                self.send_message("Plotter killed", "kill", self.next_host, self.next_port, self.pi_id)
                self.send_message("Plotter killed", "kill", self.other_host, self.other_port, self.pi_id)
                logger.info(f"Pi #{self.pi_id} caught keyboard interrupt, exiting...")
            else:
                self.send_message("Pi killed", "gone", self.next_host, self.next_port, self.pi_id)
                self.send_message("Pi killed", "oneless", self.other_host, self.other_port, self.pi_id)
                logger.info(f"Pi #{self.pi_id} caught keyboard interrupt, exiting...")
        finally:
            self.sel.close()
            server_sock.close()
            if self.db_conn is not None:
                try:
                    self.db_conn.close()
                    logger.info(f"Pi #{self.pi_id} database connection closed.")
                except mysql.connector.Error as e:
                    logger.error(f"Pi #{self.pi_id} error closing database connection: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 9:  # Updated to account for is_db_connector
        print("Usage: python3 token-ring.py <pi_id> <host_ip> <host_port> <next_host_ip> <next_host_port> <other_host_ip> <other_host_port> <is_db_connector>")
        sys.exit(1)

    try:
        pi_id = int(sys.argv[1])
        host_ip = sys.argv[2]
        host_port = int(sys.argv[3])
        next_host_ip = sys.argv[4]
        next_host_port = int(sys.argv[5])
        other_host_ip = sys.argv[6]
        other_host_port = int(sys.argv[7])
        is_db_connector = sys.argv[8].lower() == 'true'
    except ValueError as e:
        print("Error: pi_id, host_port, and next_host_port must be integers, is_db_connector must be 'true' or 'false'")
        sys.exit(1)

    if pi_id not in [1, 2, 3]:
        print("pi_id must be 1, 2, or 3")
        sys.exit(1)

    node = TokenRingNode(
        pi_id=pi_id,
        host_ip=host_ip,    
        host_port=host_port,
        next_host_ip=next_host_ip,
        next_host_port=next_host_port,
        other_host_ip=other_host_ip,
        other_host_port=other_host_port,
        is_db_connector=is_db_connector
    )
    node.run()