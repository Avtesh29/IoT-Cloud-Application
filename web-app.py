from flask import Flask, render_template
from datetime import datetime
from zoneinfo import ZoneInfo
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
    # print("Forecast: ", data)

    min_t = data['daily']['temperature_2m_min'][0]
    max_t = data['daily']['temperature_2m_max'][0]
    avg_t_forecast = round((max_t + min_t) / 2, 1)
    print(f"Temperature Forecast: Min-{min_t}°C, Max-{max_t}°C, Avg-{avg_t_forecast}°C")

    all_h = data['hourly']['relative_humidity_2m']
    avg_h_forecast = round(sum(all_h) / len(all_h), 1)
    print(f"Humidity Forecast: Avg-{avg_h_forecast} %")

    all_s = data['hourly']['soil_moisture_3_to_9cm']
    soil_3_9cm_forecast = round(sum(all_s) / len(all_s), 1) 
    print(f"Soil Forecast: Avg-{soil_3_9cm_forecast}")

    max_w = data['daily']['wind_speed_10m_max'][0]
    print(f"Wind Speed Forecast: Max-{max_w} m/s")

    return


# Get Weather
def getWeather():
    # Get and format current date information
    current_datetime = datetime.now(ZoneInfo("America/Los_Angeles"))
    formatted_datetime = current_datetime.strftime("%I:%M %p\n%m-%d-%Y\n")

    # UCSC lat and lng
    latitude = 37.0
    longitude = -122.06

    # OpenMeteo API Endpoint
    API_URL = "https://api.open-meteo.com/v1/forecast"

    try: 
        # Send request for temperature data
        response = requests.get(API_URL, params={
            'latitude': latitude,
            'longitude': longitude,
            'daily': "temperature_2m_max,temperature_2m_min",
            'timezone': "America/Los_Angeles",
            'temperature_unit': "celsius"
            })

        # Get data
        data = response.json()

        # Prepare data for the graph (e.g., next 7 days)
        graph_data = {
            'dates': data['daily']['time'], # List of date strings
            'max_temps': data['daily']['temperature_2m_max'], # List of max temps
            'min_temps': data['daily']['temperature_2m_min']  # List of min temps
        }
        
    except requests.exceptions.RequestException as e:
        app.logger.error(f"API request failed: {e}")
        return None
    except (KeyError, IndexError, TypeError) as e:
        app.logger.error(f"Error processing API data: {e}")
        return None
    except requests.exceptions.JSONDecodeError:
        app.logger.error(f"Failed to decode JSON. Response: {response.text if response else 'No response'}")
        return None
    
    return graph_data


def get_averages(max_temps, min_temps):
    avg_temps = []
    for max, min in zip(max_temps, min_temps):
        avg = (max + min) / 2
        avg_temps.append(round(avg, 1))
    return avg_temps


# Function to generate the graph image
def create_temperature_graph(dates, max_temps, min_temps):
    if not dates or not max_temps or not min_temps:
        return None
    try:
        # plt.style.use('https://github.com/dhaitz/matplotlib-stylesheets/raw/master/pitayasmoothie-light.mplstyle')
        plt.style.use("cyberpunk")

        fig, ax = plt.subplots(figsize=(10, 5)) # Adjust figsize as needed
        short_dates = [d.split('-', 1)[1] for d in dates] # "YYYY-MM-DD" -> "MM-DD"
        avg_temps = get_averages(max_temps, min_temps)

        ax.plot(short_dates, max_temps, marker='s', linestyle='--', color='r', label='Max Temp (°C)')
        ax.plot(short_dates, avg_temps, marker='o', linestyle='-', color='g', label='Avg Temp (°C)')
        ax.plot(short_dates, min_temps, marker='s', linestyle='--', color='b', label='Min Temp (°C)')
        
        ax.set_title('Temperature Readings and Forecast')
        ax.set_xlabel('Date')
        ax.set_ylabel('Temperature (°C)')
        ax.legend()
        ax.grid(True)
        
        plt.xticks(rotation=45, ha="right") # Rotate x-axis labels for better readability
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
    

# From https://www.mysqltutorial.org/python-mysql/python-connecting-mysql-databases/
def connect(config):
    # Connect to MySQL database
    conn = None
    try:
        print('Connecting to MySQL database...')
        conn = MySQLConnection(**config)

        if conn.is_connected():
            print('Connection is established.')
        else:
            print('Connection is failed.')
    except Error as error:
        print(error)
    finally:
        if conn is not None and conn.is_connected():
            conn.close()
            print('Connection is closed.')


# Flask Routing
@app.route("/")
@app.route("/home")
def home():
    getTemp()
    config = read_config()
    connect(config)
    daily_forecast_data = getWeather()
    graph_image_base64 = None

    if daily_forecast_data:
        graph_image_base64 = create_temperature_graph(
            daily_forecast_data['dates'],
            daily_forecast_data['max_temps'],
            daily_forecast_data['min_temps']
        )

    if graph_image_base64:
        return render_template('index.html',
                               graph_image=graph_image_base64, 
                               error_message=None)
    else:
        return render_template('index.html',
                               error_message="Could not retrieve weather data.",
                               graph_image=None) 


# Run Server
if __name__ == '__main__':
    getForecast()
    app.run(debug=True, host='0.0.0.0', port=5000)
