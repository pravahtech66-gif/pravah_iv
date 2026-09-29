#!/bin/bash
cd "$(dirname "$0")/.."
echo "Starting Pravah PIV Velocity Analyzer..."
echo "Installing/checking dependencies..."
pip install -r requirements.txt -q
echo "Launching app at http://localhost:5002"
cd rtsp
python app_stream.py
