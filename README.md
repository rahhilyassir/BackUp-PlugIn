# Backup Plugin Documentation

## Overview

The Backup Plugin is a Python-based tool designed to automate the process of backing up a specified file to a remote server at regular intervals. It ensures that only a defined number of the most recent backups are retained on the server by automatically managing and deleting older files as needed. This helps in maintaining an efficient backup system without manual intervention.

## Requirements

- **Python Version**: Python 3.8 or higher
- **Libraries**: requests

## Installation

1. **Set Up a Virtual Environment**

    Create and activate a virtual environment to manage project dependencies:

    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

2. **Install Required Libraries**

    Install the necessary Python libraries using the following command:

    ```sh
    pip install requests
    ```

## Configuration

1. **Create a Configuration File**

    Create a `config.json` file in the root directory of the project with the following structure:

    ```json
    {
      "file_path": "./exampleFile.txt",
      "server_url": "http://your-company-server-url/upload",
      "interval_minutes": 60,
      "max_files": 5
    }
    ```

    - **file_path**: The path to the file you want to back up.
    - **server_url**: The URL of the company's server where the file will be uploaded.
    - **interval_minutes**: The interval (in minutes) at which the file will be uploaded.
    - **max_files**: The maximum number of files to retain on the server.

## Integrating with Your Company's Server

To seamlessly integrate the Backup Plugin with your company's server, follow these simple steps:

1. **Deploy the Script**: Begin by transferring the provided Python script (`backup_server.py`) to your company's server environment.

2. **Install Dependencies**: Ensure that your server environment supports Python 3.8 or higher. If not already available, install the necessary libraries using `pip`. Run the following command in your terminal:

    ```sh
    pip install requests
    ```

3. **Configure the Plugin**: Create a `config.json` file in the same directory as the script. Customize the file path, server URL, interval, and maximum file limit to align with your specific requirements.

4. **Initiate Backup**: Execute the Python script (`backup_server.py`) on your server. This script will systematically upload the designated file to the server URL as specified in the `config.json` file, ensuring consistent and reliable backups.

## Testing

To validate the functionality of the Backup Plugin under controlled conditions, utilize the provided `serverTest.py` file. Run this script alongside the Flask server (`server.py`) to simulate the backup process. Remember to adjust the configuration parameters within the `config.json` file to suit your testing environment.
