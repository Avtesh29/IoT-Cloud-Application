from flask import Flask, render_template
from datetime import datetime
from zoneinfo import ZoneInfo
import textwrap
import requests
import io # For handling image in memory
import base64 # For encoding image
import matplotlib
matplotlib.use('Agg') # IMPORTANT: Use a non-GUI backend for Matplotlib in a web server
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import mplcyberpunk
from mysql.connector import MySQLConnection, Error
from config import read_config

# Constants
LATITUDE = 37.0
LONGITUDE = -122.06

API_URL = "https://api.open-meteo.com/v1/forecast" 

app = Flask(__name__)


# Send Open-Meteo request with params
def getReq(fields):
    try: 
        # Send request for temperature data
        response = requests.get(API_URL, params=fields)
        # Get data
        data = response.json()
    except requests.exceptions.RequestException as e:
        app.logger.error(f"API request failed: {e}")
        return None
    except (KeyError, IndexError, TypeError) as e:
        app.logger.error(f"Error processing API data: {e}")
        return None
    except requests.exceptions.JSONDecodeError:
        app.logger.error(f"Failed to decode JSON. Response: {response.text if response else 'No response'}")
        return None
    return data

# Get All Forecast Values
def getForecast():
    req_fields = {
        'latitude': LATITUDE,
        'longitude': LONGITUDE,
        'hourly': "relative_humidity_2m,soil_moisture_3_to_9cm",
        'daily': "temperature_2m_max,temperature_2m_min,wind_speed_10m_max",
        'timezone': "America/Los_Angeles",
        'temperature_unit': "celsius",
        'wind_speed_unit': "ms",
        'forecast_days': 1
        }
    data = getReq(req_fields) 

    min_t = data['daily']['temperature_2m_min'][0]
    max_t = data['daily']['temperature_2m_max'][0]
    avg_t_forecast = round((max_t + min_t) / 2, 1)

    all_h = data['hourly']['relative_humidity_2m']
    avg_h_forecast = round(sum(all_h) / len(all_h), 1)

    all_s = data['hourly']['soil_moisture_3_to_9cm']
    soil_3_9cm_forecast = round(sum(all_s) / len(all_s), 1) 

    max_w = data['daily']['wind_speed_10m_max'][0]

    return avg_t_forecast, avg_h_forecast, soil_3_9cm_forecast, max_w


# Function to generate the graph image
def create_graph(forecast, ylabel, line_label, title, dates, sr1, sr2, sr3):
    if not forecast:
        return None
    try:
        # plt.style.use('https://github.com/dhaitz/matplotlib-stylesheets/raw/master/pitayasmoothie-light.mplstyle')
        plt.style.use("cyberpunk")

        fig, ax = plt.subplots(figsize=(10, 5)) # Adjust figsize as needed
        # short_dates = [d.split('-', 1)[1] for d in dates] # "YYYY-MM-DD" -> "MM-DD"

        # ax.set_xlim()     # use later for settings x and y axis
        # ax.set_ylim()

        ax.plot(dates, sr1, marker='o', linestyle='-', color="#d606b0", label='Sensor 1 Readings')
        ax.plot(dates, sr2, marker='o', linestyle='-', color="#07E0D6", label='Sensor 2 Readings')
        ax.plot(dates, sr3, marker='o', linestyle='-', color="#003ada", label='Sensor 3 Readings')
        ax.axhline(y=forecast, linestyle='--', color="#d60700", label=line_label)
        
        ax.set_title(title)
        ax.set_xlabel('Dates')
        ax.set_ylabel(ylabel)
        ax.legend()
        ax.grid(True)
        
        # plt.xticks(rotation=45, ha="right") # Rotate x-axis labels for better readability
        plt.tight_layout() # Adjust layout to prevent labels from overlapping
        mplcyberpunk.make_lines_glow()

        # Save it to a BytesIO object
        img_io = io.BytesIO()
        plt.savefig(img_io, format='PNG')
        img_io.seek(0)
        plt.close(fig) # Close the figure to free memory

        # Encode to Base64 string
        img_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
        return img_base64
    except Exception as e:
        app.logger.error(f"Error creating graph: {e}")
        return None
    

# Built upon https://www.mysqltutorial.org/python-mysql/python-connecting-mysql-databases/
def fetch_from_DB(config, table_details_list):
    # Connect to database once and fetch last 20 rows from each table
    conn = None
    all_tables_data = {} # To store results for each table

    try:
        print('Connecting to MySQL database for multiple table query...')
        conn = MySQLConnection(**config)

        if conn.is_connected():
            print('Connection established.')
            cursor = conn.cursor(dictionary=True) # Get rows as dictionaries

            for table_name in table_details_list:

                query = f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT 20"
                
                print(f"Executing query for table '{table_name}': {query}")
                cursor.execute(query)
                rows = cursor.fetchall()
                
                all_tables_data[table_name] = rows
                if rows:
                    print(f"Successfully fetched {len(rows)} rows from '{table_name}'.")
                else:
                    print(f"No rows found in table '{table_name}' or it's empty.")
            
            cursor.close()
            print("Cursor closed.")

        else:
            print('Connection failed.')

    except Error as error:
        print(f"Error while connecting to MySQL or executing query: {error}")
        all_tables_data = {} 

    finally:
        if conn is not None and conn.is_connected():
            conn.close()
            print('Connection closed.')
            
    return all_tables_data

# Helper function to calculate sum of list of floats excluding 0 (faulty reading)
def sum_excluding_zero(data_f):
    sum = 0
    size = 0
    for num in data_f:
        if num != 0.0:
            sum += num
            size += 1
    return sum, size


# Used to bin data together to reduce the impact of outliers and faulty readings
def bin_data(data_list, num_bins):
    binned_data = []            # Hold result
    n = len(data_list)          # 20
    bin_size = n // num_bins    # 4

    for index in range(0, n-bin_size+1, bin_size):
        agg, div = sum_excluding_zero(data_list[index : index+bin_size])
        avg_val = round(agg / div, 1) if div != 0 else 0
        binned_data.append(avg_val)

    return binned_data

# Group timestamps for x-axis labeling
def group_timestamps(timestamps, num_bins):
    grouped_timestamps = []     # Hold result
    n = len(timestamps)         # 20
    space = n // num_bins       # 4

    for i in range(0, len(timestamps)-space+1, space):
        x_label = textwrap.fill(f"{timestamps[i]} - {timestamps[i+space-1]}", width=12)
        grouped_timestamps.append(x_label)
    
    return grouped_timestamps


# Flask Routing
@app.route("/")
@app.route("/home")
def home():
    # Configure Database Settings
    config = read_config()
    
    # Fetch from all 3 tables
    tables_details_list = [
        "sensor_readings1",
        "sensor_readings2",
        "sensor_readings3"
    ]
    # all_tables_data contains a dictionary -> key: table name, value: list of dictionaries each representing a row
    all_tables_data = fetch_from_DB(config, tables_details_list)

    sr1_data = all_tables_data['sensor_readings1']
    sr2_data = all_tables_data['sensor_readings2']
    sr3_data = all_tables_data['sensor_readings3']

    timestamps = []
    sr1_temps, sr2_temps, sr3_temps, avg_temps = [], [], [], []
    sr1_hums, sr2_hums, sr3_hums, avg_hums = [], [], [], []
    sr1_soils, sr2_soils, sr3_soils, avg_soils = [], [], [], []
    sr1_winds, sr2_winds, sr3_winds, avg_winds = [], [], [], []

    # Go through each row starting from the first of the 20 readings
    # "Bin" groups of 4 together to deal with outliers, etc.
    # Assume valid size of 20 everytime (handled in fetch_from_DB())
    for entry1, entry2, entry3 in zip(sr1_data[::-1], sr2_data[::-1], sr3_data[::-1]):
        # Get timestamp (should be the same for each table so just pick from any table)
        timestamps.append(entry3['timestamp'].strftime("%B %d, %I:%M:%S %p"))
        # Append for sensor readings 1
        sr1_temps.append(entry1['temperature'])
        sr1_hums.append(entry1['humidity'])
        sr1_soils.append(entry1['soil_moisture'])
        sr1_winds.append(entry1['wind_speed'])
        # Append for sensor readings 2
        sr2_temps.append(entry2['temperature'])
        sr2_hums.append(entry2['humidity'])
        sr2_soils.append(entry2['soil_moisture'])
        sr2_winds.append(entry2['wind_speed'])
        # Append for sensor readings 3
        sr3_temps.append(entry3['temperature'])
        sr3_hums.append(entry3['humidity'])
        sr3_soils.append(entry3['soil_moisture'])
        sr3_winds.append(entry3['wind_speed'])
    
    print("Timestamps: ", timestamps)
    print("Temperatures: ", sr1_temps, sr2_temps, sr3_temps)
    print("Humidities: ", sr1_hums, sr2_hums, sr3_hums)
    print("Soil Moistures: ",sr1_soils, sr2_soils, sr3_soils)
    print("Wind Speeds: ", sr1_winds, sr2_winds, sr3_winds)

    # Group timestamps to represent bounds of bins
    timestamps_g = group_timestamps(timestamps, num_bins=5)
    # Bin sensor readings 1 
    sr1_bin_t = bin_data(sr1_temps,num_bins=5)
    sr1_bin_h = bin_data(sr1_hums,num_bins=5)
    sr1_bin_s = bin_data(sr1_soils,num_bins=5)
    sr1_bin_w = bin_data(sr1_winds,num_bins=5)
    # Bin sensor readings 2
    sr2_bin_t = bin_data(sr2_temps,num_bins=5)
    sr2_bin_h = bin_data(sr2_hums,num_bins=5)
    sr2_bin_s = bin_data(sr2_soils,num_bins=5)
    sr2_bin_w = bin_data(sr2_winds,num_bins=5)
    # Bin sensor readings 3 
    sr3_bin_t = bin_data(sr3_temps,num_bins=5)
    sr3_bin_h = bin_data(sr3_hums,num_bins=5)
    sr3_bin_s = bin_data(sr3_soils,num_bins=5)
    sr3_bin_w = bin_data(sr3_winds,num_bins=5)

    print("Grouped Timestamps: ", timestamps_g)
    print("Binned Temperatures: ", sr1_bin_t, sr2_bin_t, sr3_bin_t)
    print("Binned Humidities: ", sr1_bin_h, sr2_bin_h, sr3_bin_h)
    print("Binned Soil Moistures: ",sr1_bin_s, sr2_bin_s, sr3_bin_s)
    print("Binned Wind Speeds: ", sr1_bin_w, sr2_bin_w, sr3_bin_w)


    # Gather all forecast data in one API call
    avg_t_forecast, avg_h_forecast, soil_3_9cm_forecast, max_w = getForecast()
    temp_graph_image_base64, hum_graph_image_base64, soil_graph_image_base64, wind_graph_image_base64 = None, None, None, None

    # Graph if forecast info returned
    if avg_t_forecast:
        temp_graph_image_base64 = create_graph(
            forecast=avg_t_forecast,
            ylabel="Temperature (°C)",
            line_label=f"Avg. Temp. Forecast ({avg_t_forecast}°C)",
            title="Temperature Readings and Forecast",
            dates=timestamps_g,
            sr1=sr1_bin_t,
            sr2=sr2_bin_t,
            sr3=sr3_bin_t,
            )
    if avg_h_forecast:
        hum_graph_image_base64 = create_graph(
            forecast=avg_h_forecast,
            ylabel="Humidity (%)",
            line_label=f"Avg. Humidity Forecast ({avg_h_forecast}%)",
            title="Humidity Readings and Forecast",
            dates=timestamps_g,
            sr1=sr1_bin_h,
            sr2=sr2_bin_h,
            sr3=sr3_bin_h,
            )
    if soil_3_9cm_forecast:
        soil_graph_image_base64 = create_graph(
            forecast=soil_3_9cm_forecast,
            ylabel="Soil Moisture at 3-9 cm (m³/m³)",
            line_label=f"Avg Soil Mositure at 3-9 cm Forecast ({soil_3_9cm_forecast}m³/m³)",
            title="Soil Mositure Readings and Forecast",
            dates=timestamps_g,
            sr1=sr1_bin_s,
            sr2=sr2_bin_s,
            sr3=sr3_bin_s,
            )
    if max_w:
        wind_graph_image_base64 = create_graph(
            forecast=max_w,
            ylabel="Wind Speed (m/s)",
            line_label=f"Max Wind Speed Forecast ({max_w}m/s)",
            title="Wind Speed Readings and Forecast",
            dates=timestamps_g,
            sr1=sr1_bin_w,
            sr2=sr2_bin_w,
            sr3=sr3_bin_w,
            )

    return render_template('index.html',
                            temp_graph_image=temp_graph_image_base64, 
                            hum_graph_image=hum_graph_image_base64,
                            soil_graph_image=soil_graph_image_base64,
                            wind_graph_image=wind_graph_image_base64,
                            error_message=None)


# Run Server
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
