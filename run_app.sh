#!/bin/bash

cd "$(dirname "$0")"
source .venv/bin/activate
streamlit run app_interface.py