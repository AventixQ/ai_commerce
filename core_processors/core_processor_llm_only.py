import os
import time
from typing import Dict, Type, Callable, Tuple, List, Any, Optional

import gspread
from openai import OpenAI, OpenAIError

from prompt_handlers.base_handler import BasePromptHandler

LLM_MODEL_NAME = "gpt-4o-mini"
LLM_REQUEST_TIMEOUT = 180 

def get_col_index(col_str: str) -> int:
    if not col_str or not col_str.isalpha():
        raise ValueError(f"Invalid column identifier: '{col_str}'. Must contain only letters.")
    num = 0
    for char in col_str.upper():
        num = num * 26 + (ord(char) - ord('A')) + 1
    return num

def run_core_logic(
    prompt_full_path: str,
    prompt_handler_key: str,
    available_handlers: Dict[str, Type[BasePromptHandler]],
    num_expected_outputs: int,
    gsheet_name: str,
    worksheet_name: str,
    start_row: int,
    end_row: int,
    company_input_column: str,
    first_output_column: str,
    second_output_column: str,
    third_output_column: str, 
    log_callback: Callable[[str], None]
):
    log_callback("Initializing core logic.")

    log_callback("Initializing clients and loading resources...")
    creds_file = os.getenv("CREDS_FILE")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not creds_file or not os.path.exists(creds_file):
        log_callback(f"❌ ERROR: Google credentials file not found or not set by CREDS_FILE. Path: {creds_file}")
        raise ValueError(f"Google credentials file not found or not set by CREDS_FILE. Path: {creds_file}")
    if not openai_api_key:
        log_callback("❌ ERROR: OpenAI API key not set by OPENAI_API_KEY.")
        raise ValueError("OpenAI API key not set by OPENAI_API_KEY.")

    try:
        gc = gspread.service_account(filename=creds_file)
        sh = gc.open(gsheet_name)
        worksheet = sh.worksheet(worksheet_name)
        log_callback(f"Successfully connected to Google Sheet: '{gsheet_name}' -> Worksheet: '{worksheet_name}'.")
    except Exception as e:
        log_callback(f"❌ ERROR: Could not connect to Google Sheets: {type(e).__name__} - {e}")
        raise

    try:
        # Pass timeout directly to the client constructor if it's a global timeout for all requests,
        # or to individual request methods if it's per-request.
        # For chat.completions.create, timeout can be passed per request.
        openai_client = OpenAI(api_key=openai_api_key) 
        log_callback(f"OpenAI client initialized for model {LLM_MODEL_NAME}.")
    except Exception as e:
        log_callback(f"❌ ERROR: Could not initialize OpenAI client: {type(e).__name__} - {e}")
        raise

    if prompt_handler_key not in available_handlers:
        log_callback(f"❌ ERROR: Prompt handler for key '{prompt_handler_key}' not found.")
        raise ValueError(f"Handler '{prompt_handler_key}' unavailable.")
    handler_class: Type[BasePromptHandler] = available_handlers[prompt_handler_key]
    log_callback(f"Using prompt handler: {handler_class.__name__}")

    try:
        with open(prompt_full_path, 'r', encoding='utf-8') as f:
            prompt_system_content = f.read() 
        log_callback(f"Successfully loaded prompt template from: {prompt_full_path}")
    except Exception as e:
        log_callback(f"❌ ERROR: Could not read prompt file '{prompt_full_path}': {type(e).__name__} - {e}")
        raise

    output_column_letters_map: List[str] = []
    if num_expected_outputs >= 1 and first_output_column: output_column_letters_map.append(first_output_column)
    if num_expected_outputs >= 2 and second_output_column: output_column_letters_map.append(second_output_column)
    if num_expected_outputs >= 3 and third_output_column: output_column_letters_map.append(third_output_column)
    
    actual_output_column_letters = output_column_letters_map[:num_expected_outputs]
    if len(actual_output_column_letters) < num_expected_outputs:
        log_callback(f"⚠️ WARNING: Prompt expects {num_expected_outputs} outputs, but only {len(actual_output_column_letters)} output columns are configured/valid.")

    output_col_indices = [get_col_index(col_letter) for col_letter in actual_output_column_letters]
    company_input_col_idx = get_col_index(company_input_column)

    log_callback(f"Input column: {company_input_column} (index {company_input_col_idx}). Output columns: {actual_output_column_letters} (indexes {output_col_indices}).")
    log_callback("--- Starting row processing ---")

    for current_row_index in range(start_row, end_row + 1):
        log_callback(f"\nProcessing row {current_row_index}...")
        outputs_for_sheet: Tuple[str, ...] = tuple([""] * num_expected_outputs)

        try:
            domain_or_formula = worksheet.cell(current_row_index, company_input_col_idx).value
            if not domain_or_formula or not str(domain_or_formula).strip():
                log_callback(f"Row {current_row_index}, Col {company_input_column}: Empty input. Skipping.")
                time.sleep(0.1)
                continue
            
            domain_or_formula = str(domain_or_formula).strip()
            log_callback(f"Row {current_row_index}, Col {company_input_column}: Read '{domain_or_formula}'.")
            
            user_message_content = f"Please process the following input based on your instructions: {domain_or_formula}"
            
            messages_for_llm = [
                {"role": "system", "content": prompt_system_content},
                {"role": "user", "content": user_message_content}
            ]

            log_callback(f"Sending request for '{domain_or_formula}' to LLM (model: {LLM_MODEL_NAME})...")
            try:
                completion = openai_client.chat.completions.create(
                    model=LLM_MODEL_NAME,
                    messages=messages_for_llm,
                    timeout=LLM_REQUEST_TIMEOUT 
                )
                
                llm_response_str = ""
                if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
                    llm_response_str = completion.choices[0].message.content.strip()
                else:
                    log_callback(f"⚠️ WARNING: LLM response structure not as expected or content is empty for '{domain_or_formula}'. Response: {completion}")

                if not llm_response_str:
                     log_callback(f"⚠️ WARNING: LLM returned empty content for '{domain_or_formula}'.")
                     llm_response_str = "" 

                log_callback(f"Received LLM response. Processing with handler '{handler_class.__name__}'...")
                outputs_for_sheet = handler_class.process_llm_response(
                    llm_response_str, num_expected_outputs, log_callback
                )

            except OpenAIError as e: 
                error_detail = str(e)
                if hasattr(e, 'response') and e.response is not None and hasattr(e.response, 'text'):
                    error_detail = f"{e} - API Response: {e.response.text}"
                log_callback(f"❌ OpenAI API Error for '{domain_or_formula}': {type(e).__name__} - {error_detail}")
                outputs_for_sheet = tuple([f"LLM Error: {type(e).__name__}"] * num_expected_outputs)
            except Exception as e: 
                log_callback(f"❌ Unexpected error during LLM call or handler processing for '{domain_or_formula}': {type(e).__name__} - {e}")
                outputs_for_sheet = tuple([f"Processing error: {type(e).__name__}"] * num_expected_outputs)
        
        except Exception as e_row_setup:
            log_callback(f"❌ Error setting up data for row {current_row_index} (input: '{domain_or_formula if 'domain_or_formula' in locals() else 'N/A'}'): {type(e_row_setup).__name__} - {e_row_setup}")
            outputs_for_sheet = tuple([f"Row setup error: {type(e_row_setup).__name__}"] * num_expected_outputs)


        if len(outputs_for_sheet) != num_expected_outputs:
             log_callback(f"⚠️ WARNING: Handler returned {len(outputs_for_sheet)} values, expected {num_expected_outputs}. Padding/truncating.")
             outputs_for_sheet = (list(outputs_for_sheet) + [""] * num_expected_outputs)[:num_expected_outputs]

        cells_to_update: List[gspread.Cell] = []
        try:
            for i, col_idx in enumerate(output_col_indices):
                if i < len(outputs_for_sheet):
                    cell_value = outputs_for_sheet[i]
                    cells_to_update.append(gspread.Cell(row=current_row_index, col=col_idx, value=str(cell_value if cell_value is not None else "")))
            
            if cells_to_update:
                worksheet.update_cells(cells_to_update, value_input_option='USER_ENTERED')
                log_callback(f"Row {current_row_index}: Sheet updated with results.")
        
        except Exception as e_sheet_update: 
            log_callback(f"❌ Error updating sheet for row {current_row_index}: {type(e_sheet_update).__name__} - {e_sheet_update}")
        finally:
            log_callback(f"Finished processing row {current_row_index}. Waiting 1 sec...")
            time.sleep(1) 

    log_callback("\n--- All rows processed. Core logic finished. ---")