@echo off
title IMSCC Module Splitter
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
start "" http://127.0.0.1:5054
python app.py
pause
