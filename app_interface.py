# app_interface.py
import streamlit as st
import os
import re
from dotenv import load_dotenv
import importlib
import pkgutil
from typing import Dict, Type, List, Any, Optional
from prompt_handlers.base_handler import BasePromptHandler
from core_processor import run_core_logic

load_dotenv()

PROMPTS_FOLDER = "./prompts/"
PROMPT_HANDLERS_PACKAGE_NAME = "prompt_handlers"

st.set_page_config(page_title="Company Website Analyzer", layout="wide")
st.title("Company Website Analyzer for Ecommerce Berlin Expo")

AVAILABLE_PROMPT_HANDLERS: Dict[str, Type[BasePromptHandler]] = {}
PROMPT_CONFIG_MAP: Dict[str, Dict[str, Any]] = {}
ACTUAL_PROMPT_FILES: Dict[str, str] = {}

def load_prompt_handlers_and_configs():
    """
    Dynamically loads prompt handlers from PROMPT_HANDLERS_PACKAGE_NAME package.
    Populates global dictionaries AVAILABLE_PROMPT_HANDLERS, PROMPT_CONFIG_MAP, ACTUAL_PROMPT_FILES.
    """
    if not os.path.isdir(PROMPTS_FOLDER):
        st.error(f"Folder '{PROMPTS_FOLDER}' does not exist.")

    try:
        prompt_handlers_package = importlib.import_module(PROMPT_HANDLERS_PACKAGE_NAME)
        for _, module_name, _ in pkgutil.iter_modules(prompt_handlers_package.__path__):
            if module_name == "base_handler":
                continue
            try:
                module = importlib.import_module(f".{module_name}", package=PROMPT_HANDLERS_PACKAGE_NAME)
                for attribute_name in dir(module):
                    attribute = getattr(module, attribute_name)
                    
                    is_concrete_handler = False
                    if isinstance(attribute, type):
                        if attribute is BasePromptHandler:
                            continue 
                        if issubclass(attribute, BasePromptHandler):
                            is_concrete_handler = True
                        elif attribute.__name__ != "BasePromptHandler" and (
                              hasattr(attribute, "get_config") and callable(getattr(attribute, "get_config")) and
                              hasattr(attribute, "process_llm_response") and callable(getattr(attribute, "process_llm_response")) and
                              hasattr(attribute, "handle_no_content") and callable(getattr(attribute, "handle_no_content")) and
                              hasattr(attribute, "get_prompt_key") and callable(getattr(attribute, "get_prompt_key"))
                        ):
                            is_concrete_handler = True
                            st.info(f"Handler '{attribute_name}' in module '{module_name}' loaded by duck-typing.")
                    
                    if is_concrete_handler:
                        handler_class: Type[BasePromptHandler] = attribute
                        try:
                            if not (hasattr(handler_class, "get_config") and 
                                    hasattr(handler_class, "get_prompt_key")):
                                st.warning(f"Handler class '{attribute_name}' in module '{module_name}' is missing required static methods (get_config or get_prompt_key). Skipping.")
                                continue

                            config: Optional[Dict[str, Any]] = handler_class.get_config()
                            prompt_key: Optional[str] = handler_class.get_prompt_key()

                            if config is None:
                                st.error(f"ERROR: Handler '{attribute_name}' in module '{module_name}' returned None from get_config(). Skipping this handler.")
                                continue
                            if prompt_key is None or not prompt_key.strip():
                                st.error(f"ERROR: Handler '{attribute_name}' w module '{module_name}' returned None or empty string from get_prompt_key(). Skipping this handler.")
                                continue

                            display_name = config.get("display_name")
                            file_base = config.get("file_base")

                            if not display_name or not file_base:
                                st.warning(f"Handler '{attribute_name}' in module '{module_name}' has incomplete configuration. Configuration: {config}. Prompt key: {prompt_key}. Skipping.")
                                continue

                            full_path = os.path.join(PROMPTS_FOLDER, file_base + ".txt")
                            if os.path.exists(full_path):
                                AVAILABLE_PROMPT_HANDLERS[prompt_key] = handler_class
                                PROMPT_CONFIG_MAP[display_name] = config
                                ACTUAL_PROMPT_FILES[display_name] = full_path
                                #st.info(f"✅ Successfully loaded handler: '{display_name}' (key: '{prompt_key}')")
                            else:
                                st.warning(f"Prompt file '{file_base}.txt' for handler '{display_name}' (key: {prompt_key}) not found in '{PROMPTS_FOLDER}'.")
                        except Exception as e_handler_init:
                            handler_prompt_key_attr = getattr(handler_class, 'PROMPT_KEY', 'N/A') if hasattr(handler_class, 'PROMPT_KEY') else 'Nieznany'
                            st.error(f"Error initializing/configuring handler '{attribute_name}' (for prompt key: {handler_prompt_key_attr}) z modułu '{module_name}': {type(e_handler_init).__name__} - {e_handler_init}")
                        break
            except ImportError as e_mod:
                st.error(f"Error importing handler module '{module_name}': {e_mod}")
            except Exception as e_mod_general:
                st.error(f"General module processing error '{module_name}': {e_mod_general}")

    except ImportError as e_pkg:
        st.error(f"Could not import prompt handlers package: '{PROMPT_HANDLERS_PACKAGE_NAME}'. Error: {e_pkg}")
        st.error(f"Make sure the '{PROMPT_HANDLERS_PACKAGE_NAME}' directory exists and contains the file '__init__.py'.")
    except Exception as e_load_general:
        st.error(f"An unexpected error occurred while loading prompt handlers: {e_load_general}")
    
    print(f"DEBUG app_interface.load_prompt_handlers_and_configs: Final Content AVAILABLE_PROMPT_HANDLERS: {list(AVAILABLE_PROMPT_HANDLERS.keys())}")


load_prompt_handlers_and_configs()

available_prompts_display = sorted(list(PROMPT_CONFIG_MAP.keys()))

if not available_prompts_display:
    st.error(
        f"No valid prompts found. Check that prompt files exist in '{PROMPTS_FOLDER}', "
        f"that appropriate handlers are defined in package '{PROMPT_HANDLERS_PACKAGE_NAME}', "
        f"and that handlers are properly configured (especially their `get_config()` and `get_prompt_key()` methods)."
    )

st.sidebar.header("⚙️ Main Configuration")

selected_prompt_display_name = st.sidebar.selectbox(
    "Use prompt:",
    options=available_prompts_display,
    index=0 if available_prompts_display else -1,
    disabled=not available_prompts_display
)

selected_prompt_key: Optional[str] = None
current_prompt_config: Dict[str, Any] = {}
selected_prompt_full_path: Optional[str] = None

if selected_prompt_display_name and available_prompts_display:
    current_prompt_config = PROMPT_CONFIG_MAP.get(selected_prompt_display_name, {})
    selected_prompt_full_path = ACTUAL_PROMPT_FILES.get(selected_prompt_display_name)
    
    for key, handler_cls_ref in AVAILABLE_PROMPT_HANDLERS.items():
        try:
            config_from_handler = handler_cls_ref.get_config()
            if config_from_handler: 
                handler_display_name = config_from_handler.get("display_name")
                if handler_display_name == selected_prompt_display_name:
                    selected_prompt_key = key
                    break
        except Exception as e_get_conf_sidebar:
            st.warning(f"Cannot get configuration for handler (key: {key}) when matching sidebar display name: {e_get_conf_sidebar}")


num_outputs_for_ui = current_prompt_config.get("num_outputs", 0)
ui_output_labels: List[str] = current_prompt_config.get("output_labels", [])

st.sidebar.header("📄 Google Sheets Configuration")
gsheet_name_input = st.sidebar.text_input("Google Sheet Name:", value="Test PD")
worksheet_name_input = st.sidebar.text_input("File Name:", value="Arkusz3")

st.sidebar.header("↔️ Rows' range")
start_row_input = st.sidebar.number_input("Start row:", min_value=1, max_value=1000000, value=2, step=1)
end_row_input = st.sidebar.number_input("End row:", min_value=1, max_value=1000000, value=5, step=1)

st.sidebar.header("⬇️ Input column")
company_input_column_input = st.sidebar.text_input("Column with domains:", value="A", max_chars=3)

st.sidebar.header("⬆️ Output columns")
output_col_1_val = ""
output_col_2_val = ""
output_col_3_val = "" 

default_output_col_values = ["B", "C", "D"] 

if num_outputs_for_ui >= 1:
    output_col_1_val = st.sidebar.text_input(
        ui_output_labels[0] if len(ui_output_labels) >= 1 else "First output column",
        value=default_output_col_values[0],
        max_chars=3
    )
if num_outputs_for_ui >= 2:
    output_col_2_val = st.sidebar.text_input(
        ui_output_labels[1] if len(ui_output_labels) >= 2 else "Second output column",
        value=default_output_col_values[1],
        max_chars=3
    )
if num_outputs_for_ui >= 3:
    output_col_3_val = st.sidebar.text_input(
        ui_output_labels[2] if len(ui_output_labels) >= 3 else "Third output column",
        value=default_output_col_values[2],
        max_chars=3
    )

log_placeholder = st.empty()
log_messages: List[str] = []

def ui_log_callback(message: str):
    print(message) 
    log_messages.append(f"{message.strip()}\n")
    max_log_lines = 200
    if len(log_messages) > max_log_lines:
        del log_messages[:-max_log_lines]
    log_placeholder.code("".join(log_messages), language="log")

def is_valid_column(col_str: str) -> bool:
    if not col_str:
        return False 
    return re.fullmatch(r"^[A-Za-z]{1,3}$", col_str) is not None

st.markdown("""
    <style>
    div.stButton > button:first-child {
        background-color: #009a22; color: white; margin-top: 20px; margin-bottom: 20px; 
        font-weight: bold; border-radius: 8px; padding: 0.75em 1.5em; 
        transition: background-color 0.3s ease; width: auto; min-width: 200px; 
    }
    div.stButton > button:first-child:hover { background-color: #1e7e34; border-color: #1c7430; }
    div.stButton > button:first-child:disabled { background-color: #cccccc; color: #666666; cursor: not-allowed; }
    .centered-button-container { display: flex; justify-content: center; width: 100%; margin-top: 10px; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="centered-button-container">', unsafe_allow_html=True)
run_button_disabled = not selected_prompt_key or not available_prompts_display
if st.button("Start Analysis", disabled=run_button_disabled, key="run_analysis_button"):
    log_messages.clear()
    ui_log_callback("Initializing analysis...")
    ui_log_callback("Starting input validation...\n")

    valid_input = True
    if not selected_prompt_key or not selected_prompt_full_path:
        ui_log_callback("❌ ERROR: The prompt was not selected correctly or the prompt file/handler does not exist.")
        valid_input = False
    if not gsheet_name_input.strip():
        ui_log_callback("❌ ERROR: Google Sheet name cannot be empty.")
        valid_input = False
    if not worksheet_name_input.strip():
        ui_log_callback("❌ ERROR: Folder name cannot be empty.")
        valid_input = False

    if start_row_input > end_row_input:
        ui_log_callback(f"❌ ERROR: Start row ({start_row_input}) cannot be larger than end row ({end_row_input}).")
        valid_input = False
    
    if not company_input_column_input.strip():
        ui_log_callback(f"❌ ERROR: 'Domain column' cannot be empty.")
        valid_input = False
    elif not is_valid_column(company_input_column_input):
        ui_log_callback(f"❌ ERROR: The value for 'Domain Column' ('{company_input_column_input}') is invalid. It must contain 1-3 letters (e.g. A, AB, ABC).")
        valid_input = False

    temp_output_cols_to_pass = ["", "", ""]

    if num_outputs_for_ui >= 1:
        label = ui_output_labels[0] if len(ui_output_labels) >= 1 else "First output column"
        if not output_col_1_val.strip():
            ui_log_callback(f"❌ ERROR: '{label}' cannot be empty because it is required for this prompt.")
            valid_input = False
        elif not is_valid_column(output_col_1_val):
            ui_log_callback(f"❌ ERROR: The value for '{label}' ('{output_col_1_val}') is invalid. It must contain 1-3 letters.")
            valid_input = False
        else:
            temp_output_cols_to_pass[0] = output_col_1_val.upper()

    if num_outputs_for_ui >= 2:
        label = ui_output_labels[1] if len(ui_output_labels) >= 2 else "Second output column"
        if output_col_2_val.strip() and not is_valid_column(output_col_2_val):
            ui_log_callback(f"❌ ERROR: Value for '{label}' ('{output_col_2_val}') is invalid if provided. Must be 1-3 letters.")
            valid_input = False
        elif output_col_2_val.strip():
            temp_output_cols_to_pass[1] = output_col_2_val.upper()

    if num_outputs_for_ui >= 3:
        label = ui_output_labels[2] if len(ui_output_labels) >= 3 else "Third output column"
        if output_col_3_val.strip() and not is_valid_column(output_col_3_val):
            ui_log_callback(f"❌ ERROR: Value for '{label}' ('{output_col_3_val}') is invalid if provided. Must be 1-3 letters.")
            valid_input = False
        elif output_col_3_val.strip():
            temp_output_cols_to_pass[2] = output_col_3_val.upper()

    defined_output_cols = [col.upper() for col in temp_output_cols_to_pass[:num_outputs_for_ui] if col.strip()]
    if len(defined_output_cols) != len(set(defined_output_cols)):
        ui_log_callback(f"❌ ERROR: Output column names must be unique if specified. Duplicates found in: {defined_output_cols}")
        valid_input = False
    
    if company_input_column_input.upper() in [col for col in defined_output_cols if col]:
        ui_log_callback(f"❌ ERROR: The input column ('{company_input_column_input.upper()}') cannot be the same as any of the output columns.")
        valid_input = False

    creds_file_env = os.getenv("CREDS_FILE")
    openai_api_key_env = os.getenv("OPENAI_API_KEY")

    if not creds_file_env:
        ui_log_callback("❌ ERROR: The CREDS_FILE environment variable (path to Google credentials.json file) is not set. Check your .env file.")
        valid_input = False
    elif not os.path.exists(creds_file_env):
        ui_log_callback(f"❌ ERROR: The Google credentials file '{creds_file_env}' (specified by CREDS_FILE in .env) does not exist.")
        valid_input = False
        
    if not openai_api_key_env:
        ui_log_callback("❌ ERROR: The OPENAI_API_KEY environment variable is not set. Check your .env file.")
        valid_input = False

    if valid_input and selected_prompt_key and selected_prompt_full_path:
        ui_log_callback("✅ Validation completed successfully. Starting processing...\n")
        
        with st.spinner("Processing... This may take a while..."):
            try:
                run_core_logic(
                    prompt_full_path=selected_prompt_full_path,
                    prompt_handler_key=selected_prompt_key,
                    available_handlers=AVAILABLE_PROMPT_HANDLERS,
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
                ui_log_callback("\n--- ✅ PPROCESSING COMPLETED Successfully ---")
                st.success("Processing completed successfully!")
            except ValueError as ve:
                ui_log_callback(f"\n--- ❌ ERROR CONFIGURATION OR VALUES ---")
                ui_log_callback(f"ERROR: {str(ve)}")
                st.error(f"Configuration or value ERROR occurred: {ve}")
            except Exception as e:
                ui_log_callback(f"\n--- ❌ FATAL ERROR DURING PROCESSING ---")
                ui_log_callback(f"Error details: {type(e).__name__} - {str(e)}")
                st.error(f"An unexpected ERROR occurred while processing: {type(e).__name__} - {e}")
    elif valid_input and (not selected_prompt_key or not selected_prompt_full_path):
        ui_log_callback("Internal ERROR: Validation passed but key or prompt path is missing. Aborting.")
        st.error("Internal configuration ERROR. Check the logs or contact support :>.")
    else:
        ui_log_callback("\n❌ Processing aborted due to validation errors.")
        st.error("Please correct the configuration errors listed above and try again.")

st.markdown('</div>', unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Important notes:**\n"
    "- Share your Google Sheet with your service account: `classification-sheets@classification-442812.iam.gserviceaccount.com` (or your specific service account email).\n"
    "- Make sure that the `CREDS_FILE` (path to your Google `credentials.json` file) and `OPENAI_API_KEY` variables are set in the `.env` file in your project root.\n"
    "- Prompt files (`.txt`) should be in the `./prompts/` folder.\n"
    "- The corresponding Python handler files (`_handler.py`) should be in the `./prompt_handlers/` package."
)
st.sidebar.markdown("---")
st.sidebar.info(f"Currently selected prompt key: `{selected_prompt_key}`" if selected_prompt_key else "No prompt selected/loaded.")

if "run_analysis_button_clicked_once" not in st.session_state:
    st.session_state.run_analysis_button_clicked_once = False

if (not st.session_state.run_analysis_button_clicked_once and log_messages) or \
   (not available_prompts_display and log_messages):
    log_placeholder.code("".join(log_messages), language="log")
elif not log_messages:
    log_placeholder.code("Logs will appear here once processing begins or if there are any loading problems.", language="log")

if "run_analysis_button" in st.session_state and st.session_state.run_analysis_button:
    st.session_state.run_analysis_button_clicked_once = True
