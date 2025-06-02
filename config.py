# Config implementation file from https://www.mysqltutorial.org/python-mysql/python-connecting-mysql-databases/
from configparser import ConfigParser

def read_config(filename='app.ini', section='mysql'):    
    # Create a ConfigParser object to handle INI file parsing
    config = ConfigParser()
    
    # Read the specified INI configuration file
    config.read(filename)

    # Initialize an empty dictionary to store configuration data
    data = {}

    # Check if the specified section exists in the INI file
    if config.has_section(section):
        # Retrieve all key-value pairs within the specified section
        items = config.items(section)

        # Populate the data dictionary with the key-value pairs
        for item in items:
            data[item[0]] = item[1]
    else:
        # Raise an exception if the specified section is not found
        raise Exception(f'{section} section not found in the {filename} file')

    # Return the populated data dictionary
    return data

if __name__ == '__main__':
    # Read the configuration from the default section ('mysql') in the 'app.ini' file
    config = read_config()

    # Display the obtained configuration
    print(config)
