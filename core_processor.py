# core_processor.py
import os
import time
import gspread
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException, ElementNotInteractableException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from openai import OpenAI
import json
import re
from dotenv import load_dotenv
from typing import Callable, Type, Dict, Tuple, List, Any, Optional
from prompt_handlers.base_handler import BasePromptHandler

load_dotenv()

def get_handler_by_key(
    handler_key: str,
    available_handlers_arg: Dict[str, Type[BasePromptHandler]]
) -> "Optional[Type[BasePromptHandler]]":
    """Gets the handler class based on the key from the provided dictionary."""
    return available_handlers_arg.get(handler_key)


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
    log_callback: Callable[[str], None],
    openai_model_name: str = "gpt-4o-mini",
    requests_timeout: int = 10,
    selenium_page_load_timeout: int = 20,
    selenium_sleep_after_load: int = 3
):
    log_callback(f"🚀 Starting core logic with prompt file: {os.path.basename(prompt_full_path)}, handler key: '{prompt_handler_key}', expecting {num_expected_outputs} output(s).")
    #log_callback(f"DEBUG core_processor: Otrzymano 'available_handlers' z kluczami: {list(available_handlers.keys())}")

    handler_class = get_handler_by_key(prompt_handler_key, available_handlers) 
    
    if not handler_class:
        error_msg = f"❌ ERROR: Could not find prompt handler for key: '{prompt_handler_key}' in the provided 'available_handlers'. Available keys: {list(available_handlers.keys())}. Aborting."
        log_callback(error_msg)
        raise ValueError(error_msg)

    try:
        handler_config = handler_class.get_config()
        if handler_config.get("num_outputs") != num_expected_outputs:
            log_callback(
                f"⚠️ Warning: num_expected_outputs from UI ({num_expected_outputs}) "
                f"differs from handler's config ({handler_config.get('num_outputs')}). "
                f"Using UI value ({num_expected_outputs}) for determining the number of GSheet columns to update. "
                "The handler's internal logic should ideally align with its own 'num_outputs' config."
            )
    except Exception as e_cfg:
        error_msg = f"❌ ERROR: Could not get config from handler '{prompt_handler_key}': {e_cfg}. Aborting."
        log_callback(error_msg)
        raise ValueError(error_msg)

    # --- Loading Prompt System ---
    system_message_content = ""
    try:
        with open(prompt_full_path, "r", encoding="utf-8") as f:
            system_message_content = f.read()
        if not system_message_content.strip():
            error_msg = f"❌ ERROR: System prompt file '{prompt_full_path}' is empty. Aborting."
            log_callback(error_msg)
            raise ValueError(error_msg)
        log_callback(f"📄 System prompt loaded successfully from: {os.path.basename(prompt_full_path)}")
    except FileNotFoundError:
        error_msg = f"❌ ERROR: System prompt file not found: {prompt_full_path}. Aborting."
        log_callback(error_msg)
        raise FileNotFoundError(error_msg)
    except Exception as e:
        error_msg = f"❌ ERROR loading system prompt file '{prompt_full_path}': {e}. Aborting."
        log_callback(error_msg)
        raise IOError(error_msg) from e

    # --- OpenAI Client Initialization ---
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        error_msg = "❌ ERROR: OPENAI_API_KEY environment variable not found. Aborting."
        log_callback(error_msg)
        raise ValueError(error_msg)
    try:
        openai_client = OpenAI(api_key=openai_api_key)
        log_callback("🤖 OpenAI client initialized successfully.")
    except Exception as e:
        error_msg = f"❌ ERROR initializing OpenAI client: {e}. Aborting."
        log_callback(error_msg)
        raise RuntimeError(error_msg) from e

    # --- OpenAI Classification Feature ---
    def classify_with_openai_local(text_to_classify: str) -> str:
        if not text_to_classify or not text_to_classify.strip():
            log_callback("⚠️ Warning: No text provided to classify_with_openai_local. LLM will receive empty input.")
            text_to_classify = "No content available for this website."

        user_message_content = f"Please analyze the following website content (or lack thereof) and provide a response based on the instructions you received. Website content: \n{text_to_classify}"
        messages = [
            {"role": "system", "content": system_message_content},
            {"role": "user", "content": user_message_content}
        ]
        try:
            log_callback(f"💬 Sending request to OpenAI model: {openai_model_name}...")
            completion = openai_client.chat.completions.create(
                model=openai_model_name,
                temperature=0, 
                messages=messages
            )
            response_text = completion.choices[0].message.content.strip()
            log_callback(f"✅ OpenAI response received (length: {len(response_text)} chars).")
            return response_text
        except Exception as e:
            log_callback(f"❌ Error during OpenAI API call: {e}")
            return "" 

    # --- Initializing the Google Sheets Client ---
    log_callback("📊 Initializing Google Sheets client...")
    creds_file_path = os.getenv("CREDS_FILE")
    if not creds_file_path:
        error_msg = "❌ ERROR: Credentials file path (CREDS_FILE) not set in .env. Aborting."
        log_callback(error_msg)
        raise ValueError(error_msg)
    if not os.path.exists(creds_file_path):
        error_msg = f"❌ ERROR: Credentials file '{creds_file_path}' does not exist. Aborting."
        log_callback(error_msg)
        raise FileNotFoundError(error_msg)
    
    gc_client = None
    sh_opened = None
    try:
        gc_client = gspread.service_account(filename=creds_file_path)
        sh_opened = gc_client.open(gsheet_name).worksheet(worksheet_name)
        log_callback(f"✅ Connected to Google Sheet: '{gsheet_name}', Worksheet: '{worksheet_name}'.")
    except gspread.exceptions.SpreadsheetNotFound:
        error_msg = f"❌ ERROR: Spreadsheet '{gsheet_name}' not found. Check name and sharing permissions. Aborting."
        log_callback(error_msg)
        raise FileNotFoundError(error_msg)
    except gspread.exceptions.WorksheetNotFound:
        error_msg = f"❌ ERROR: Worksheet '{worksheet_name}' not found in spreadsheet '{gsheet_name}'. Aborting."
        log_callback(error_msg)
        raise FileNotFoundError(error_msg)
    except Exception as e:
        error_msg = f"❌ Error initializing Google Sheets client or opening sheet/worksheet: {e}. Aborting."
        log_callback(error_msg)
        raise RuntimeError(error_msg) from e

    # --- Selenium WebDriver Initialization ---
    log_callback("🌐 Initializing Selenium WebDriver...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080") 
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

    selenium_driver: Optional[webdriver.Chrome] = None
    try:
        service = ChromeService(ChromeDriverManager().install())
        selenium_driver = webdriver.Chrome(service=service, options=chrome_options)
        log_callback("✅ Selenium WebDriver initialized successfully using webdriver-manager.")
    except Exception as e:
        log_callback(f"❌ ERROR initializing Selenium WebDriver with webdriver-manager: {e}")
        log_callback("Ensure you have an internet connection for the first run to download ChromeDriver, or that ChromeDriver is in your PATH.")
        selenium_driver = None 

    # --- Scraping function with Selenium ---
    def get_text_with_selenium_local(url: str) -> Optional[str]:
        nonlocal selenium_driver 
        if not selenium_driver:
            log_callback("⚠️ Selenium driver not available. Cannot scrape with Selenium.")
            return None
        try:
            log_callback(f"Attempting to fetch {url} with Selenium...")
            selenium_driver.set_page_load_timeout(selenium_page_load_timeout)
            selenium_driver.get(url)
            time.sleep(selenium_sleep_after_load) 
            
            if "Just a moment..." in selenium_driver.title or "Cloudflare" in selenium_driver.page_source:
                log_callback(f"⚠️ Possible Cloudflare challenge page detected for {url}. Waiting a bit longer.")
                time.sleep(5) 

            html = selenium_driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            
            for element_type in ["script", "style", "header", "footer", "nav", "aside", "form"]:
                for element in soup.find_all(element_type):
                    element.decompose()
            
            body_tag = soup.find('body')
            text_content = body_tag.get_text(separator=" ", strip=True) if body_tag else soup.get_text(separator=" ", strip=True)

            log_callback(f"✅ Content retrieved with Selenium from {url} (length: {len(text_content)} chars).")
            return text_content
        except (WebDriverException, TimeoutException) as e:
            log_callback(f"❌ Selenium - WebDriver or Timeout error for {url}: {str(e)[:200]}...")
            if selenium_driver:
                log_callback("Attempting to restart Selenium driver once...")
                try:
                    selenium_driver.quit()
                    restarted_service = ChromeService(ChromeDriverManager().install())
                    selenium_driver = webdriver.Chrome(service=restarted_service, options=chrome_options)
                    log_callback("✅ Selenium driver restarted.")
                except Exception as e_restart:
                    log_callback(f"❌ Failed to restart Selenium driver: {e_restart}")
                    selenium_driver = None 
            return None
        except Exception as e:
            log_callback(f"❌ Selenium - Other error for {url}: {str(e)[:200]}...")
            return None

    # --- Main Processing Loop ---
    log_callback(f"📋 Starting processing rows from {start_row} to {end_row}...")
    company_names_data: List[List[str]] = []
    try:
        if end_row < start_row:
            log_callback(f"⚠️ Warning: End row ({end_row}) is less than start row ({start_row}). No rows will be processed.")
            if selenium_driver: selenium_driver.quit()
            return

        company_data_range_str = f"{company_input_column}{start_row}:{company_input_column}{end_row}"
        log_callback(f"Fetching data from Google Sheets range: {company_data_range_str}")
        company_names_data = sh_opened.get(company_data_range_str, value_render_option='UNFORMATTED_VALUE')
        if not company_names_data:
            log_callback(f"⚠️ No data found in range {company_data_range_str}. Ensure the sheet and range are correct.")

    except gspread.exceptions.APIError as e_gs_api_error:
        error_msg = f"❌ Google Sheets API error while fetching data from range {company_data_range_str}: {e_gs_api_error}. Aborting."
        log_callback(error_msg)
        if selenium_driver: selenium_driver.quit()
        raise RuntimeError(error_msg) from e_gs_api_error
    except Exception as e_fetch:
        error_msg = f"❌ Unexpected error while fetching data from Google Sheets: {e_fetch}. Aborting."
        log_callback(error_msg)
        if selenium_driver: selenium_driver.quit()
        raise RuntimeError(error_msg) from e_fetch

    output_columns_config = [
        (first_output_column, "Col1"),
        (second_output_column, "Col2"),
        (third_output_column, "Col3")
    ]

    for i, row_data in enumerate(company_names_data):
        current_row_index = start_row + i
        if current_row_index > end_row:
            log_callback(f"Reached defined end_row ({end_row}). Stopping further processing.")
            break

        company_name_or_domain_input = row_data[0] if row_data and len(row_data) > 0 and row_data[0] else None
        current_outputs: Tuple[str, ...] = tuple([""] * num_expected_outputs)

        if not company_name_or_domain_input or not str(company_name_or_domain_input).strip():
            log_callback(f"Row {current_row_index}: No company name/domain in input column '{company_input_column}', skipping actual processing for this row.")
            if hasattr(handler_class, 'handle_no_input_data') and callable(getattr(handler_class, 'handle_no_input_data')):
                 current_outputs = handler_class.handle_no_input_data(num_expected_outputs, log_callback)
            else:
                temp_outputs_list = [""] * num_expected_outputs
                if num_expected_outputs >= 1:
                    temp_outputs_list[0] = "Error: No input data"
                current_outputs = tuple(temp_outputs_list)
        else:
            company_name_or_domain_input = str(company_name_or_domain_input).strip()
            log_callback(f"\n--- 🔄 Processing company/domain for row {current_row_index}: '{company_name_or_domain_input}' ---")

            url_to_scrape = ""
            if not re.match(r"^[a-zA-Z]+://", company_name_or_domain_input):
                url_to_scrape = "https://" + company_name_or_domain_input
            else:
                url_to_scrape = company_name_or_domain_input
            
            log_callback(f"Normalized URL to scrape: {url_to_scrape}")
            
            text_content: Optional[str] = None
            scraped_with = ""
            REQUESTS_HEADERS = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
            try:
                log_callback(f"Attempting to fetch {url_to_scrape} with Requests...")
                response = requests.get(url_to_scrape, headers=REQUESTS_HEADERS, timeout=requests_timeout, allow_redirects=True)
                response.raise_for_status() 
                
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" in content_type:
                    soup = BeautifulSoup(response.content, "html.parser")
                    for element_type in ["script", "style", "header", "footer", "nav", "aside", "form"]:
                        for element in soup.find_all(element_type):
                            element.decompose()
                    body_tag = soup.find('body')
                    text_content = body_tag.get_text(separator=" ", strip=True) if body_tag else soup.get_text(separator=" ", strip=True)
                    scraped_with = "Requests"
                    log_callback(f"✅ Content retrieved with Requests (length: {len(text_content)} chars).")
                else:
                    log_callback(f"⚠️ Non-HTML content type with Requests for {url_to_scrape}: {content_type}. Will try Selenium if available.")
                    if selenium_driver: 
                        text_content = get_text_with_selenium_local(url_to_scrape)
                        if text_content: scraped_with = "Selenium (after non-HTML with Requests)"
            
            except requests.exceptions.RequestException as e_req:
                log_callback(f"❌ Requests error for {url_to_scrape}: {str(e_req)[:200]}... Will try Selenium if available.")
                if selenium_driver: 
                    text_content = get_text_with_selenium_local(url_to_scrape)
                    if text_content: scraped_with = "Selenium (after Requests error)"
            except Exception as e_gen_req: 
                log_callback(f"❌ Generic error during Requests for {url_to_scrape}: {str(e_gen_req)[:200]}... Will try Selenium if available.")
                if selenium_driver:
                    text_content = get_text_with_selenium_local(url_to_scrape)
                    if text_content: scraped_with = "Selenium (after generic Requests error)"

            if text_content and text_content.strip():
                clean_text = " ".join(filter(None, (line.strip() for line in text_content.splitlines())))
                clean_text = re.sub(r'\s+', ' ', clean_text).strip() 
                max_text_len = 30000 
                if len(clean_text) > max_text_len:
                    log_callback(f"⚠️ Content too long ({len(clean_text)} chars), truncating to {max_text_len} chars for OpenAI.")
                    clean_text = clean_text[:max_text_len]

                classification_result_str = classify_with_openai_local(clean_text)
                current_outputs = handler_class.process_llm_response(classification_result_str, num_expected_outputs, log_callback)
            else: 
                log_callback(f"⚠️ Failed to retrieve meaningful content for {url_to_scrape} using all methods.")
                current_outputs = handler_class.handle_no_content(num_expected_outputs, log_callback)

        # --- Login and Update Spreadsheet ---
        log_message_parts = []
        cells_to_update_batch: List[gspread.Cell] = []

        for idx in range(num_expected_outputs): 
            if idx < len(current_outputs): 
                col_letter = output_columns_config[idx][0]
                col_log_prefix = output_columns_config[idx][1]
                
                if col_letter and col_letter.strip(): 
                    value_to_write = str(current_outputs[idx])
                    log_value_display = (value_to_write[:67] + '...') if len(value_to_write) > 70 else value_to_write
                    log_message_parts.append(f"{col_log_prefix}({col_letter})='{log_value_display}'")
                    
                    try:
                        col_index_for_gspread = gspread.utils.a1_to_rowcol(f"{col_letter}1")[1]
                        cells_to_update_batch.append(
                            gspread.Cell(row=current_row_index, col=col_index_for_gspread, value=value_to_write)
                        )
                    except Exception as e_cell:
                        log_callback(f"❌ Error preparing cell for GSheet update: {col_letter}{current_row_index}, value: '{value_to_write[:50]}...'. Error: {e_cell}")

            elif idx < num_expected_outputs : 
                 col_letter = output_columns_config[idx][0]
                 if col_letter and col_letter.strip(): 
                    log_callback(f"⚠️ Handler did not provide a value for expected output index {idx} (column {col_letter}). Will write empty string.")
                    try:
                        col_index_for_gspread = gspread.utils.a1_to_rowcol(f"{col_letter}1")[1]
                        cells_to_update_batch.append(
                            gspread.Cell(row=current_row_index, col=col_index_for_gspread, value="")
                        )
                    except Exception as e_cell_empty:
                         log_callback(f"❌ Error preparing empty cell for GSheet update: {col_letter}{current_row_index}. Error: {e_cell_empty}")


        if not log_message_parts and not cells_to_update_batch: 
            log_callback(f"Row {current_row_index}: No specific output values generated or no output columns configured for update.")
        elif log_message_parts:
            log_callback(f"➡️ Preparing to update sheet for row {current_row_index}: " + ", ".join(log_message_parts))

        if cells_to_update_batch:
            try:
                sh_opened.update_cells(cells_to_update_batch, value_input_option='USER_ENTERED')
                log_callback(f"✅ Successfully updated Google Sheets for row {current_row_index}.")
            except gspread.exceptions.APIError as e_gs_api:
                log_callback(f"❌ Google Sheets API Error during batch update for row {current_row_index}: Code {e_gs_api.response.status_code} - {e_gs_api.response.json().get('error', {}).get('message', str(e_gs_api))}")
            except Exception as e_gs_update:
                log_callback(f"❌ Error batch updating Google Sheets for row {current_row_index}: {e_gs_update}")
        
        log_callback(f"--- Row {current_row_index} processing finished. Waiting 1 sec... ---")
        time.sleep(1) 

    # --- Finishing and Cleaning ---
    if selenium_driver:
        try:
            selenium_driver.quit()
            log_callback("✅ Selenium WebDriver closed successfully.")
        except Exception as e_quit:
            log_callback(f"⚠️ Error closing Selenium WebDriver: {e_quit}")
            
    log_callback("🎉 Core logic processing finished.")

