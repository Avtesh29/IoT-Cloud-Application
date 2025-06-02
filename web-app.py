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


app = Flask(__name__)

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

        # Init data, get data, and get code
        weather_data_str = ""
        data = response.json()

        # Get average forecast for today
        max_today = data['daily']['temperature_2m_max'][0]            # Max Temp
        min_today = data['daily']['temperature_2m_min'][0]            # Min Temp
        cels = data['daily_units']['temperature_2m_max']              # Celsius Units
        average_today = (float(max_today) + float(min_today)) / 2     # Average
        weather_data_str = f"{average_today:.1f} {cels}"

        # Prepare data for the graph (e.g., next 7 days)
        graph_data = {
            'dates': data['daily']['time'], # List of date strings
            'max_temps': data['daily']['temperature_2m_max'], # List of max temps
            'min_temps': data['daily']['temperature_2m_min']  # List of min temps
        }
        
    except requests.exceptions.RequestException as e:
        app.logger.error(f"API request failed: {e}")
        return None, formatted_datetime, None # weather_string, date_string, graph_data
    except (KeyError, IndexError, TypeError) as e:
        app.logger.error(f"Error processing API data: {e}")
        return None, formatted_datetime, None
    except requests.exceptions.JSONDecodeError:
        app.logger.error(f"Failed to decode JSON. Response: {response.text if response else 'No response'}")
        return None, formatted_datetime, None
    
    return weather_data_str, formatted_datetime, graph_data

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
        
        ax.set_title('7-Day Temperature Forecast')
        ax.set_xlabel('Date')
        ax.set_ylabel('Temperature (°C)')
        ax.legend()
        ax.grid(True)
        
        plt.xticks(rotation=45, ha="right") # Rotate x-axis labels for better readability
        plt.tight_layout() # Adjust layout to prevent labels from overlapping

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
    config = read_config()
    connect(config)
    weather_string, current_date_formatted, daily_forecast_data = getWeather()
    graph_image_base64 = None

    if daily_forecast_data:
        graph_image_base64 = create_temperature_graph(
            daily_forecast_data['dates'],
            daily_forecast_data['max_temps'],
            daily_forecast_data['min_temps']
        )

    if weather_string:
        return render_template('index.html',
                               w_data=weather_string,
                               f_date=current_date_formatted,
                               graph_image=graph_image_base64, 
                               error_message=None)
    else:
        return render_template('index.html',
                               error_message="Could not retrieve weather data.",
                               graph_image=None) 


# Run Serve
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
