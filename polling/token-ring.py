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
import mysql.connector

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("(token-ring)")
logger.setLevel(level=logging.INFO)

class TokenRingNode:
    def __init__(self, pi_id, host_ip, host_port, next_host_ip, next_host_port, other_host_ip, other_host_port):
        self.pi_id = pi_id  # Pi identifier
        self.host = host_ip
        self.port = host_port  
        self.next_host = next_host_ip  
        self.next_port = next_host_port  
        self.other_host = other_host_ip
        self.other_port = other_host_port
        self.plotter = 3  # Initial plotter Pi (will be reassigned if needed)
        self.numpis = 3
        self.sel = selectors.DefaultSelector()
        self.round = 0  # Track the round number for plotting
        self.is_alone = False  # Track if this Pi is alone in the network
        self.last_successful_send = time.time()  # Track last successful communication
        self.connection_timeout = 10  # Seconds to wait before considering Pi disconnected

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
        if self.pi_id == self.plotter:
            self.connect_db()
       
           
           
    def connect_db(self):
        max_retries = 3
        retry_delay = 5  # seconds
        for attempt in range(max_retries):
            try:
                self.db_conn = mysql.connector.connect(
                    host="169.233.131.154",
                    user="root",
                    password="",
                    database="piSenseDB"
                )
                logger.info(f"Pi #{self.pi_id} connected to piSenseDB database.")
                return
            except mysql.connector.Error as e:
                logger.error(f"Pi #{self.pi_id} failed to connect to piSenseDB (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        logger.error(f"Pi #{self.pi_id} could not connect to piSenseDB after {max_retries} attempts.")
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
            # Reset alone status when receiving data from other Pis
            self.is_alone = False
            self.last_successful_send = time.time()
           
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

            # Only plot and connect to DB if we have multiple Pis and this is the plotter
            if self.pi_id == self.plotter and self.numpis > 1:
                self.round += 1
                self.plot_data(all_data)
                self.send_message(None, "continue", self.next_host, self.next_port, (self.pi_id % 3)+1)
            elif self.numpis > 1:  # Only forward if there are other Pis
                next_pi_id = (self.pi_id % 3) + 1
                self.send_message(all_data, "sensor_data", self.next_host, self.next_port, pi_id=next_pi_id)
            else:
                # If alone, just collect data but don't send anywhere
                logger.info(f"Pi #{self.pi_id} is alone, collecting data but not forwarding")
                self.is_alone = True
               
        elif msg_data.get("type") == "kill":
            logger.info(f"Plotting Pi #{self.plotter} killed, reassigning plotter...")
           
            # Decrement number of Pis first
            if self.numpis > 1:
                self.numpis -= 1
               
                # Assign new plotter by decrementing from current plotter
                old_plotter = self.plotter
                self.plotter = self.plotter - 1 if self.plotter > 1 else 3
               
                # If decremented plotter would be 0, wrap to 3
                if self.plotter <= 0:
                    self.plotter = 3
                   
                logger.info(f"Plotter reassigned from Pi #{old_plotter} to Pi #{self.plotter}")
               
                # If this Pi is the new plotter and we're not alone, connect to DB
                if self.pi_id == self.plotter and self.numpis > 1:
                    logger.info(f"Pi #{self.pi_id} is now the plotter, connecting to database...")
                    self.connect_db()
            else:
                # If only one Pi left, enter alone mode
                self.numpis = 1
                self.is_alone = True
                logger.info(f"Pi #{self.pi_id} is now alone after plotter killed")
                self.disconnect_db()
           
        elif msg_data.get("type") == "gone":
            if self.numpis > 1:
                self.numpis -= 1
           
            # Check if this Pi is now alone
            if self.numpis <= 1:
                logger.info(f"Pi #{self.pi_id} is now alone, entering listening mode")
                self.is_alone = True
                self.disconnect_db()  # Disconnect from DB when alone
                return
               
            logger.info(f"Pi #{self.pi_id} starting round {self.round + 1}")
            self.round += 1
            time.sleep(5)
            my_data = self.collect_sensor_data()
            self.send_message([{"pi_id": self.pi_id, "measurements": my_data}], "sensor_data", self.next_host, self.next_port, pi_id=(self.pi_id+1)%3)
           
            # If this Pi became the plotter, connect to DB
            if self.pi_id == self.plotter and self.numpis > 1:
                logger.info(f"Pi #{self.pi_id} is now the plotter, connecting to database...")
                self.connect_db()
       
        elif msg_data.get("type") == "oneless":
            logger.info(f"One Pi disconnected...")
            if self.numpis > 1:
                self.numpis -= 1
           
            # Check if this Pi is now alone
            if self.numpis <= 1:
                logger.info(f"Pi #{self.pi_id} is now alone, entering listening mode")
                self.is_alone = True
                self.disconnect_db()  # Disconnect from DB when alone
                return
               
            # If this Pi became the plotter, connect to DB
            if self.pi_id == self.plotter and self.numpis > 1:
                logger.info(f"Pi #{self.pi_id} is now the plotter, connecting to database...")
                self.connect_db()

        elif msg_data.get("type") == "continue":
            # Reset alone status when receiving continue message
            self.is_alone = False
            self.last_successful_send = time.time()
           
            logger.info(f"Pi #{self.pi_id} starting round {self.round + 1}")
            self.round += 1
            time.sleep(5)
            my_data = self.collect_sensor_data()
           
            # Only send if not alone
            if self.numpis > 1:
                self.send_message([{"pi_id": self.pi_id, "measurements": my_data}], "sensor_data", self.next_host, self.next_port, pi_id=(self.pi_id+1)%3)
            else:
                logger.info(f"Pi #{self.pi_id} is alone, not forwarding message")
                self.is_alone = True
               
        elif msg_data.get("type") == "reconnect":
            # Handle Pi reconnection
            logger.info(f"Pi reconnected to network")
            self.is_alone = False
            self.numpis += 1
           
            # If this Pi should be the plotter and we have multiple Pis, connect to DB
            if self.pi_id == self.plotter and self.numpis > 1:
                logger.info(f"Pi #{self.pi_id} reconnecting as plotter, connecting to database...")
                self.connect_db()
               
            # Send current data to newly connected Pi
            my_data = self.collect_sensor_data()
            next_pi_id = (self.pi_id % 3) + 1
            self.send_message([{"pi_id": self.pi_id, "measurements": my_data}], "sensor_data", self.next_host, self.next_port, pi_id=next_pi_id)

    def disconnect_db(self):
        """Disconnect from database when Pi becomes alone"""
        if self.db_conn is not None:
            try:
                self.db_conn.close()
                logger.info(f"Pi #{self.pi_id} disconnected from database (alone mode)")
                self.db_conn = None
            except mysql.connector.Error as e:
                logger.error(f"Pi #{self.pi_id} error disconnecting from database: {e}")

    def send_message(self, message, msg_type, next_host, next_port, pi_id):
        """Send a message to the specified Pi."""
        # Don't try to send if we're alone
        if self.is_alone and msg_type in ["sensor_data", "continue"]:
            logger.info(f"Pi #{self.pi_id} is alone, not sending {msg_type} message")
            return
           
        logger.debug(f"Pi #{self.pi_id} attempting to connect to {next_host}:{next_port}")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((next_host, next_port))
                msg = {"type": msg_type, "data": message}
                sock.sendall((json.dumps(msg) + "\n").encode())
                logger.info(f"Pi #{self.pi_id} sent {msg_type} message to Pi #{pi_id}")
                self.last_successful_send = time.time()
        except Exception as e:
            logger.error(f"Pi #{self.pi_id} failed to send message to Pi #{pi_id}: {e}")
           
            # If we can't send to next Pi, try the other Pi
            if (next_host != self.other_host or next_port != self.other_port):
                time.sleep(3)
                logger.info(f"Attempting to send to other Pi...")
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                        sock.settimeout(5)
                        sock.connect((self.other_host, self.other_port))
                        msg = {"type": msg_type, "data": message}
                        sock.sendall((json.dumps(msg) + "\n").encode())
                        logger.info(f"Pi #{self.pi_id} sent {msg_type} message to other Pi")
                        self.last_successful_send = time.time()
                except Exception as e2:
                    logger.error(f"Pi #{self.pi_id} failed to send to other Pi: {e2}")
                    # Both Pis unreachable, assume we're alone
                    if msg_type in ["sensor_data", "continue"]:
                        logger.info(f"Pi #{self.pi_id} cannot reach other Pis, entering alone mode")
                        self.is_alone = True
                        self.numpis = 1
                        self.disconnect_db()
            else:
                # Already tried both, assume alone
                if msg_type in ["sensor_data", "continue"]:
                    logger.info(f"Pi #{self.pi_id} cannot reach any Pi, entering alone mode")
                    self.is_alone = True
                    self.numpis = 1
                    self.disconnect_db()

    def plot_data(self, all_data):
        """Plot the accumulated sensor data (called by the plotter Pi)."""
        if len(all_data) < 1: # Changed from < 2 to < 1
            logger.warning(f"Pi #{self.pi_id} insufficient data for plotting: {all_data}")
            return

        pi_data = {d["pi_id"]: d["measurements"] for d in all_data}

        # Only connect to database if we have multiple Pis and this is the plotter
        if self.pi_id == self.plotter and self.numpis > 1:
            if self.db_conn is not None:
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
                except AttributeError as e:
                    logger.error(f"Pi #{self.pi_id} database connection not initialized: {e}")
                except Exception as e:
                    logger.error(f"Pi #{self.pi_id} unexpected error during database operation: {e}")
            else:
                logger.warning(f"Pi #{self.pi_id} no database connection; skipping database insert.")

        # Plotting logic (unchanged)
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

        # Only start the ring if this is Pi 1 and there are other Pis
        if self.pi_id == 1 and self.numpis > 1:
            my_data = self.collect_sensor_data()
            self.send_message([{"pi_id": 1, "measurements": my_data}], "sensor_data", self.next_host, self.next_port, pi_id=2)

        try:
            while True:
                events = self.sel.select(timeout=1)  # Changed from None to 1 second timeout
               
                # Process any incoming connections/messages
                for key, mask in events:
                    if key.data is None:
                        self.accept_wrapper(key.fileobj)
                    else:
                        self.service_connection(key, mask)
               
                # Check if we've been alone too long and should try to reconnect
                if self.is_alone and time.time() - self.last_successful_send > self.connection_timeout:
                    logger.info(f"Pi #{self.pi_id} in alone mode, just listening for connections...")
                    # Reset timer to avoid spam
                    self.last_successful_send = time.time()
                   
        except KeyboardInterrupt:
            # Send appropriate disconnect messages
            if self.numpis > 1:  # Only send if there are other Pis
                if self.pi_id == self.plotter:
                    self.send_message("Plotter killed", "kill", self.next_host, self.next_port, self.pi_id)
                    self.send_message("Plotter killed", "kill", self.other_host, self.other_port, self.pi_id)
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
    if len(sys.argv) != 8:
        print("Usage: python3 token-ring.py <pi_id> <host_ip> <host_port> <next_host_ip> <next_host_port> <other_host_ip> <other_host_port>")
        sys.exit(1)

    try:
        pi_id = int(sys.argv[1])
        host_ip = sys.argv[2]
        host_port = int(sys.argv[3])
        next_host_ip = sys.argv[4]
        next_host_port = int(sys.argv[5])
        other_host_ip = sys.argv[6]
        other_host_port = int(sys.argv[7])
    except ValueError as e:
        print("Error: pi_id, host_port, and next_host_port must be integers")
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
        other_host_port=other_host_port
    )
    node.run()