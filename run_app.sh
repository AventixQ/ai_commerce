#!/bin/bash

cd "$(dirname "$0")"
source .venv/bin/activate
streamlit run main_app.py