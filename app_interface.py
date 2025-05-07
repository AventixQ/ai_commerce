import streamlit as st
import os
import re
from dotenv import load_dotenv

load_dotenv()

try:
    from core_processor import run_core_logic
except ImportError:
    st.error("Cannot load file `core_processor.py`. Make sure it exist in this catalog.")
    st.stop()

PROMPTS_FOLDER = "./prompts/"

st.set_page_config(page_title="Company Website Analyzer", layout="wide")
st.title("Company Website Analyzer for Ecommerce Berlin Expo")

prompt_config_map = {
    "Exhibitor Fit Analysis": {
        "file_base": "exhibitor_fit",
        "num_outputs": 2,
        "output_labels": ["Column: Exhibitor fit", "Column: Reason"]
    },
    "Company Name Changer": {
        "file_base": "name_changer",
        "num_outputs": 1,
        "output_labels": ["Column: New company name"]
    }
}

available_prompts_display = []
actual_prompt_files = {}

if not os.path.isdir(PROMPTS_FOLDER):
    st.error(f"Folder does not exist in '{PROMPTS_FOLDER}'. Create it and add .txt files.")
    st.stop()

for display_name, config in prompt_config_map.items():
    full_path = os.path.join(PROMPTS_FOLDER, config["file_base"] + ".txt")
    if os.path.exists(full_path):
        available_prompts_display.append(display_name)
        actual_prompt_files[display_name] = full_path
    else:
        st.warning(f"File  '{display_name}' ({config['file_base']}.txt) was not found in '{PROMPTS_FOLDER}'. Option not available.")

if not available_prompts_display:
    st.error(f"Prompt not found in folder '{PROMPTS_FOLDER}'.")
    st.stop()

st.sidebar.header("⚙️ Main Configuration")

selected_prompt_display_name = st.sidebar.selectbox(
    "Prompt to use:",
    options=available_prompts_display,
    index=0
)
selected_prompt_full_path = actual_prompt_files.get(selected_prompt_display_name)
current_prompt_config = prompt_config_map.get(selected_prompt_display_name, {"num_outputs": 0, "output_labels": []})
num_outputs_for_ui = current_prompt_config.get("num_outputs", 0)
ui_output_labels = current_prompt_config.get("output_labels", [])

st.sidebar.header("📄 Google Sheets Configuration")
gsheet_name_input = st.sidebar.text_input("Google Sheet Name:", value="Test PD")
worksheet_name_input = st.sidebar.text_input("Worksheet Name:", value="Arkusz3")

st.sidebar.header("↔️ Row Range")
start_row_input = st.sidebar.number_input("Start Row:", min_value=1, max_value=1000000, value=2)
end_row_input = st.sidebar.number_input("End Row:", min_value=1, max_value=1000000, value=5)

st.sidebar.header("📊 Column Configuration")
company_input_column_input = st.sidebar.text_input("Row with domain:", value="A", max_chars=2)

output_col_1_val = ""
output_col_2_val = ""
output_col_3_val = ""

default_output_col_values = ["B", "C", "D"]

if num_outputs_for_ui >= 1:
    output_col_1_val = st.sidebar.text_input(
        ui_output_labels[0] if len(ui_output_labels) >= 1 else "First output column",
        value=default_output_col_values[0],
        max_chars=2
    )
if num_outputs_for_ui >= 2:
    output_col_2_val = st.sidebar.text_input(
        ui_output_labels[1] if len(ui_output_labels) >= 2 else "Second output column",
        value=default_output_col_values[1],
        max_chars=2
    )
if num_outputs_for_ui >= 3:
    output_col_3_val = st.sidebar.text_input(
        ui_output_labels[2] if len(ui_output_labels) >= 3 else "Third output column",
        value=default_output_col_values[2],
        max_chars=2
    )

def is_valid_column(col_str):
    if not col_str:
        return True
    return re.fullmatch(r"^[A-Za-z]{1,2}$", col_str) is not None

st.header("▶️ Run Analysis")

log_placeholder = st.empty()
log_messages = []

def ui_log_callback(message):
    print(message)
    log_messages.append(f"{message}\n")
    styled_log_html = f"""
    <div id="log-box" style="
        height: 300px;
        overflow-y: auto;
        background-color: black;
        padding: 10px;
        border: 1px solid #0f0;
        color: #009a22;
        font-family: monospace;
        font-size: 14px;
        white-space: pre-wrap;
    ">
        {''.join(log_messages)}
    """
    log_placeholder.markdown(styled_log_html, unsafe_allow_html=True)

if st.button("Run Analysis", type="primary"):
    log_messages.clear()
    ui_log_callback("Starting input validation...\n")

    valid_input = True
    if not selected_prompt_full_path:
        ui_log_callback("ERROR: Prompt not selected correctly or file does not exist.")
        valid_input = False
    if not gsheet_name_input.strip():
        ui_log_callback("ERROR: Google Sheet Name cannot be empty.")
        valid_input = False
    if not worksheet_name_input.strip():
        ui_log_callback("ERROR: Worksheet Name cannot be empty.")
        valid_input = False

    if start_row_input > end_row_input:
        ui_log_callback(f"ERROR: Start row ({start_row_input}) cannot be greater than end row ({end_row_input}).")
        valid_input = False
    
    if not is_valid_column(company_input_column_input) or not company_input_column_input.strip():
        ui_log_callback(f"ERROR: Value for 'Row with domain' ('{company_input_column_input}') is invalid or empty. Must be 1 or 2 letters.")
        valid_input = False

    temp_output_cols_to_pass = ["", "", ""]

    if num_outputs_for_ui >= 1:
        label = ui_output_labels[0] if len(ui_output_labels) >= 1 else "First output column"
        if not output_col_1_val.strip():
            ui_log_callback(f"ERROR: '{label}' cannot be empty as it's required for this prompt.")
            valid_input = False
        elif not is_valid_column(output_col_1_val):
            ui_log_callback(f"ERROR: Value for '{label}' ('{output_col_1_val}') is invalid. Must be 1 or 2 letters.")
            valid_input = False
        else:
            temp_output_cols_to_pass[0] = output_col_1_val.upper()

    if num_outputs_for_ui >= 2:
        label = ui_output_labels[1] if len(ui_output_labels) >= 2 else "Second output column"
        if output_col_2_val.strip() and not is_valid_column(output_col_2_val):
            ui_log_callback(f"ERROR: Value for '{label}' ('{output_col_2_val}') is invalid. Must be 1 or 2 letters if provided.")
            valid_input = False
        else:
            temp_output_cols_to_pass[1] = output_col_2_val.upper() if output_col_2_val.strip() else ""


    if num_outputs_for_ui >= 3:
        label = ui_output_labels[2] if len(ui_output_labels) >= 3 else "Kolumna wyjściowa 3"
        if output_col_3_val.strip() and not is_valid_column(output_col_3_val): # Waliduj tylko jeśli niepuste
            ui_log_callback(f"ERROR: Value for '{label}' ('{output_col_3_val}') is invalid. Must be 1 or 2 letters if provided.")
            valid_input = False
        else:
            temp_output_cols_to_pass[2] = output_col_3_val.upper() if output_col_3_val.strip() else ""
    
    creds_file_env = os.getenv("CREDS_FILE")
    openai_api_key_env = os.getenv("OPENAI_API_KEY")

    if not creds_file_env:
        ui_log_callback("CRITICAL ERROR: Environment variable CREDS_FILE (path to Google credentials.json) is not set. Check the .env file.")
        valid_input = False
    elif not os.path.exists(creds_file_env):
        ui_log_callback(f"CRITICAL ERROR: Google credentials file '{creds_file_env}' (specified by CREDS_FILE in .env) does not exist.")
        valid_input = False
        
    if not openai_api_key_env:
        ui_log_callback("CRITICAL ERROR: Environment variable OPENAI_API_KEY is not set. Check the .env file.")
        valid_input = False

    if valid_input:
        ui_log_callback("Validation completed successfully. Starting processing...\n")
        st.balloons()

        with st.spinner("Processing... This may take a while..."):
            try:
                run_core_logic(
                    prompt_full_path=selected_prompt_full_path,
                    num_expected_outputs=num_outputs_for_ui,
                    gsheet_name=gsheet_name_input,
                    worksheet_name=worksheet_name_input,
                    start_row=start_row_input,
                    end_row=end_row_input,
                    company_input_column=company_input_column_input.upper(),
                    first_output_column=temp_output_cols_to_pass[0],
                    second_output_column=temp_output_cols_to_pass[1],
                    third_output_column=temp_output_cols_to_pass[2],
                    log_callback=ui_log_callback
                )
                ui_log_callback("\n--- PROCESSING COMPLETED Successfully ---")
                st.success("Processing completed successfully!")
            except Exception as e:
                ui_log_callback(f"\n--- CRITICAL ERROR DURING PROCESSING ---")
                ui_log_callback(f"Error: {str(e)}")
                st.error(f"An unexpected error occurred: {e}")
    else:
        ui_log_callback("\nProcessing aborted due to validation errors.")
        st.error("Fix the configuration errors and try again.")

st.sidebar.markdown("---")
st.sidebar.markdown("To run code remamber to share your google sheet to email: `classification-sheets@classification-442812.iam.gserviceaccount.com`.")
st.sidebar.markdown("Ensure the `CREDS_FILE` and `OPENAI_API_KEY` variables are set in the `.env` file in the project's root directory.")
st.sidebar.markdown("`CREDS_FILE` is the path to your Google `credentials.json` file.")