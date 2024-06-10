import os
import json
import logging
import requests
import schedule
import time

# Setup logging
logging.basicConfig(filename='backup.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def read_file(file_path):
    """
    Reads the content of the file at the given path.
    """
    if os.path.exists(file_path):
        with open(file_path, 'rb') as file:
            return file.read()
    else:
        raise FileNotFoundError(f"The file {file_path} does not exist.")

def send_to_server(file_path, server_url):
    """
    Sends the file to the central server.
    """
    try:
        file_data = read_file(file_path)
        files = {'file': (os.path.basename(file_path), file_data)}
        response = requests.post(server_url, files=files)
        response.raise_for_status()  # Raise an error on bad status
        logging.info("File backed up successfully!")
    except FileNotFoundError as e:
        logging.error(e)
    except requests.RequestException as e:
        logging.error(f"Failed to send file to server: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")

def backup_file(file_path, server_url):
    """
    Combines reading the file and sending it to the server.
    """
    send_to_server(file_path, server_url)

def schedule_backup(file_path, server_url, interval_minutes):
    """
    Schedules the backup process to run at regular intervals.
    """
    schedule.every(interval_minutes).minutes.do(backup_file, file_path, server_url)

    while True:
        schedule.run_pending()
        time.sleep(1)

def load_config(config_file):
    """
    Loads the configuration from a JSON file.
    """
    with open(config_file, 'r') as file:
        return json.load(file)

# Load configuration
config = load_config('config.json')
FILE_PATH = config['file_path']
SERVER_URL = f"{config['server_url']}/upload"  # Ensure the correct endpoint
INTERVAL_MINUTES = config['interval_minutes']

# Start the scheduling
schedule_backup(FILE_PATH, SERVER_URL, INTERVAL_MINUTES)
