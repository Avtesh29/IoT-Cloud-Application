# IoT Cloud Application: End-to-End Sensor Data System

This project (in progress) aims to implement an end-to-end IoT system for collecting environmental data from sensor nodes, storing it in a database, and displaying it via a web application.

It builds upon the foundational sensor data acquisition concepts from the [IoT-Sensor-AsyncIO](https://github.com/Avtesh29/IoT-Sensor-AsyncIO) project and involves a system of multiple Pi4.

The system will involve:
* Setting up a web server (Apache) and a MySQL database (using XAMPP/phpMyAdmin).
* Adapting previous polling and token-ring based Raspberry Pi sensor network configurations to connect to the database and store sensor readings (temperature, humidity, wind speed, soil moisture) with timestamps.
* Developing a Flask web application to retrieve sensor data from the database, fetch corresponding online weather forecast data, and display both on a website with time-series graphs.
