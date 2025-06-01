import socket
import json
import time
import logging
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
import board
import busio
import adafruit_sht31d
from adafruit_seesaw.seesaw import Seesaw
import adafruit_ads1x15.ads1015 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import simpleio as simpleio

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
clogger = logging.getLogger("(cli)")
clogger.setLevel(level=logging.INFO)

class Client:
    def __init__(self, servers):
        self.servers = servers  # List of (host, port) tuples
        self.data_log = {server: [] for server in servers}  # Store data per server
        self.timestamps = []
        self.numpis = 3
       
        # Initialize sensors for primary Pi
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            self.sht30_sensor = adafruit_sht31d.SHT31D(i2c)
            self.ss_sensor = Seesaw(i2c, addr=0x36)
            self.ads = ADS.ADS1015(i2c)
            self.chan = AnalogIn(self.ads, ADS.P0)
            clogger.info("Primary Pi sensors initialized successfully.")
            self.sensors_initialized = True
        except Exception as e:
            clogger.error(f"Failed to initialize primary Pi sensors: {e}")
            self.sensors_initialized = False
            self.sht30_sensor = None
            self.ss_sensor = None
            self.ads = None
            self.chan = None

    def get_wind_speed(self, voltage):
        """Retrieve wind speed from anemometer voltage."""
        wind_speed = simpleio.map_range(voltage, 0.4, 2.0, 0.0, 32.4)
        return max(0.0, wind_speed)

    def collect_primary_sensor_data(self):
        """Collect sensor data from the primary Pi."""
        data = {}
        if self.sensors_initialized:
            try:
                data["temperature"] = self.sht30_sensor.temperature
                data["humidity"] = self.sht30_sensor.relative_humidity
                data["soil_moisture"] = self.ss_sensor.moisture_read()
                data["soil_temperature"] = self.ss_sensor.get_temp()
                voltage = self.chan.voltage
                data["wind_speed"] = self.get_wind_speed(voltage)
                clogger.info(f"Primary Pi sensor data: {data}")
            except Exception as e:
                clogger.error(f"Error reading primary Pi sensors: {e}")
                data = self.get_default_sensor_data()
        else:
            clogger.warning("Using default values for primary Pi (sensors not initialized)")
            data = self.get_default_sensor_data()
        return data

    def get_default_sensor_data(self):
        """Return default sensor data when sensors aren't available."""
        return {
            "temperature": 0.0,
            "humidity": 0.0,
            "soil_moisture": 0.0,
            "soil_temperature": 0.0,
            "wind_speed": 0.0
        }

    def request_data(self, host, port):
        """Send request to a server and return the response."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((host, port))
                sock.sendall("Requesting data\n".encode())
                data = sock.recv(1024).decode().strip()
                return json.loads(data)
        except Exception as e:
            clogger.error(f"Error connecting to {host}:{port}: {e}")
            if self.numpis > 1:
                self.numpis -= 1
            return {"error": str(e)}

    def collect_data(self):
        """Poll all servers and collect their data plus primary Pi data."""
        timestamp = datetime.now().strftime("%m-%d-%Y %H:%M:%S")
        self.timestamps.append(timestamp)
       
        # Get primary Pi sensor data
        primary_data = self.collect_primary_sensor_data()
        self.primary_sensor_data = primary_data
        clogger.info(f"Collected primary Pi data: {primary_data}")
       
        # Get secondary Pi data
        for host, port in self.servers:
            response = self.request_data(host, port)
            if "error" not in response:
                self.data_log[(host, port)].append(response)
                clogger.info(f"Received data from {host}:{port}: {response}")
            else:
                clogger.error(f"Failed to get data from {host}:{port}: {response['error']}")
                # Add empty data to maintain consistency in data structure
                self.data_log[(host, port)].append(self.get_default_sensor_data())

    def plot_data(self, round_number):
        """Generate and save plots for collected data for the given round."""
        if not self.timestamps:
            clogger.warning("No data to plot.")
            return

        # Use the most recent data point for this round
        # Since round_number is 1-based, get the data at index (round_number - 1)
        idx = round_number - 1
        if idx >= len(self.data_log[self.servers[0]]) or idx >= len(self.data_log[self.servers[1]]):
            clogger.warning(f"Not enough data for round {round_number}.")
            return

        # Extract the latest data for Sec1 and Sec2
        sec1_data = self.data_log[self.servers[0]][idx] if idx < len(self.data_log[self.servers[0]]) else {}
        sec2_data = self.data_log[self.servers[1]][idx] if idx < len(self.data_log[self.servers[1]]) else {}

        # Safely access data with defaults
        temp1 = sec1_data.get("temperature", 0.0)
        temp2 = sec2_data.get("temperature", 0.0)
        hum1 = sec1_data.get("humidity", 0.0)
        hum2 = sec2_data.get("humidity", 0.0)
        soil1 = sec1_data.get("soil_moisture", 0.0)
        soil2 = sec2_data.get("soil_moisture", 0.0)
        wind1 = sec1_data.get("wind_speed", 0.0)
        wind2 = sec2_data.get("wind_speed", 0.0)

        # Primary data (now collected from sensors)
        temp_primary = self.primary_sensor_data.get("temperature", 0.0)
        hum_primary = self.primary_sensor_data.get("humidity", 0.0)
        soil_primary = self.primary_sensor_data.get("soil_moisture", 0.0)
        wind_primary = self.primary_sensor_data.get("wind_speed", 0.0)

        # Compute averages
        # if not temp1:
        #     temp1_add = 0
        # else:
        #     temp1_add = temp1
        # if not temp2:
        #     temp2_add = 0
        # else:
        #     temp2_add = temp2
        # if not hum1:
        #     hum1_add = 0
        # else:
        #     hum1_add = hum1
        # if not hum2:
        #     hum2_add = 0
        # else:
        #     hum2_add = hum2
        # if not soil1:
        #     soil1_add = 0
        # else:
        #     soil1_add = soil1
        # wind1_add = 0 if not wind1 else wind1
        # wind2_add = 0 if not wind1 else wind1


        temp_avg = (temp1 + temp2 + temp_primary) / self.numpis
        hum_avg = (hum1 + hum2 + hum_primary) / self.numpis
        soil_avg = (soil1 + soil2 + soil_primary) / self.numpis
        wind_avg = (wind1 + wind2 + wind_primary) / self.numpis

        # X-axis positions for Sec1, Sec2, Primary, Avg
        x_positions = [1, 2, 3, 4]
        x_labels = ["Sec1", "Sec2", "Primary", "Avg"]

        # Create a single figure with 2x2 subplots
        plt.figure(figsize=(10, 8))

        # Temperature Sensor (Top-Left)
        plt.subplot(2, 2, 1)
        plt.scatter([1], [temp1], color='red', s=100, label='Sec1')
        plt.scatter([2], [temp2], color='green', s=100, label='Sec2')
        plt.scatter([3], [temp_primary], color='blue', s=100, label='Primary')
        plt.scatter([4], [temp_avg], color='black', s=100, label='Avg')
        plt.title('Temperature Sensor')
        plt.ylabel('Temperature (°C)')
        plt.xticks(x_positions, x_labels)
        plt.legend()

        # Humidity Sensor (Top-Right)
        plt.subplot(2, 2, 2)
        plt.scatter([1], [hum1], color='red', s=100, label='Sec1')
        plt.scatter([2], [hum2], color='green', s=100, label='Sec2')
        plt.scatter([3], [hum_primary], color='blue', s=100, label='Primary')
        plt.scatter([4], [hum_avg], color='black', s=100, label='Avg')
        plt.title('Humidity Sensor')
        plt.ylabel('Humidity (%)')
        plt.xticks(x_positions, x_labels)
        plt.legend()

        # Soil Moisture Sensor (Bottom-Left)
        plt.subplot(2, 2, 3)
        plt.scatter([1], [soil1], color='red', s=100, label='Sec1')
        plt.scatter([2], [soil2], color='green', s=100, label='Sec2')
        plt.scatter([3], [soil_primary], color='blue', s=100, label='Primary')
        plt.scatter([4], [soil_avg], color='black', s=100, label='Avg')
        plt.title('Soil Moisture Sensor')
        plt.ylabel('Soil Moisture')
        plt.xticks(x_positions, x_labels)
        plt.legend()

        # Wind Sensor (Bottom-Right)
        plt.subplot(2, 2, 4)
        plt.scatter([1], [wind1], color='red', s=100, label='Sec1')
        plt.scatter([2], [wind2], color='green', s=100, label='Sec2')
        plt.scatter([3], [wind_primary], color='blue', s=100, label='Primary')
        plt.scatter([4], [wind_avg], color='black', s=100, label='Avg')
        plt.title('Wind Sensor')
        plt.ylabel('Wind Speed (m/s)')
        plt.xticks(x_positions, x_labels)
        plt.legend()

        # Adjust layout and save
        plt.tight_layout()
        plt.savefig(f'polling-plot-{round_number}.png', bbox_inches='tight')
        clogger.info(f"Saved plot: polling-plot-{round_number}.png")
        plt.close()

    def run(self):
        """Run the client, polling servers and plotting data."""
        clogger.info("Starting client...")
        for round_num in range(1, 7):  # Collect 6 data points (60 seconds)
            self.numpis = 3
            self.collect_data()
            self.plot_data(round_num)
            clogger.info(f"Round {round_num} completed, plots saved.")
            time.sleep(10)  # Poll every 10 seconds
        clogger.info("Data collection and plotting complete.")

if __name__ == "__main__":
    # Define secondary server addresses
    servers = [
        ("169.233.13.2", 5556),  # Secondary 1
        ("169.233.13.1", 5557)   # Secondary 2
    ]
    client = Client(servers)
    client.run()
