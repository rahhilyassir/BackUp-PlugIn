from flask import Flask, request, jsonify
import os
from datetime import datetime
import json

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
MAX_FILES = None

def load_config():
    """
    Loads the configuration from a JSON file.
    """
    with open('config.json', 'r') as file:
        config = json.load(file)
    return config

def get_timestamped_filename(filename):
    base, ext = os.path.splitext(filename)
    timestamp = datetime.now().strftime("%d-%m-%y_%H-%M-%S")
    return f"{base}_{timestamp}{ext}"

def manage_files():
    files = sorted(os.listdir(UPLOAD_FOLDER), key=lambda x: os.path.getctime(os.path.join(UPLOAD_FOLDER, x)))
    if MAX_FILES is not None and len(files) >= MAX_FILES:
        os.remove(os.path.join(UPLOAD_FOLDER, files[0]))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected for uploading"}), 400

    # Ensure the uploads directory exists
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    # Load configuration
    global MAX_FILES
    config = load_config()
    MAX_FILES = config.get('max_files', None)

    # Manage the files to ensure we only keep the last 'MAX_FILES' uploads
    manage_files()

    # Save the new file with a timestamped filename
    timestamped_filename = get_timestamped_filename(file.filename)
    file_path = os.path.join(UPLOAD_FOLDER, timestamped_filename)
    file.save(file_path)

    return jsonify({"message": "File successfully uploaded", "filename": timestamped_filename}), 201

if __name__ == '__main__':
    app.run(debug=True)