import os
import time
import gspread
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from openai import OpenAI
import json
import re
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

def run_core_logic(
    prompt_full_path: str,
    num_expected_outputs: int,
    gsheet_name: str,
    worksheet_name: str,
    start_row: int,
    end_row: int,
    company_input_column: str,
    first_output_column: str,
    second_output_column: str,
    third_output_column: str,
    log_callback,
    openai_model_name: str = "gpt-4o-mini",
    requests_timeout: int = 4,
    selenium_page_load_timeout: int = 10,
    selenium_sleep_after_load: int = 2
):
    log_callback(f"Starting core logic with prompt: {prompt_full_path}, expecting {num_expected_outputs} output(s).")

    if not (1 <= num_expected_outputs <= 3):
        log_callback(f"ERROR: num_expected_outputs must be between 1 and 3. Received: {num_expected_outputs}. Aborting.")
        return

    prompt_filename = os.path.basename(prompt_full_path).lower()
    prompt_type = None
    if "exhibitor_fit" in prompt_filename:
        prompt_type = "exhibitor_fit"
    elif "name_changer" in prompt_filename:
        prompt_type = "name_changer"

    if prompt_type is None:
        log_callback(f"ERROR: Unknown prompt type for file: {prompt_filename}. Cannot apply specific processing rules.")
    log_callback(f"Determined prompt type: {prompt_type}")

    system_message_content = ""
    try:
        with open(prompt_full_path, "r", encoding="utf-8") as f:
            system_message_content = f.read()
        if not system_message_content.strip():
            raise ValueError("System prompt file is empty.")
        log_callback(f"System prompt loaded from: {prompt_full_path}")
    except FileNotFoundError:
        log_callback(f"ERROR: System prompt file not found: {prompt_full_path}")
        return
    except Exception as e:
        log_callback(f"ERROR loading system prompt file: {e}")
        return

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        log_callback("ERROR: OPENAI_API_KEY environment variable not found.")
        return
    try:
        openai_client = OpenAI(api_key=openai_api_key)
        log_callback("OpenAI client initialized successfully.")
    except Exception as e:
        log_callback(f"ERROR initializing OpenAI client: {e}")
        return

    def classify_with_openai_local(text_to_classify: str) -> str:
        if not text_to_classify:
            if prompt_type == "exhibitor_fit":
                return json.dumps({"fit_for_expo": "Error", "explanation": "No text provided for classification"})
            return "Error: No text provided for classification"

        user_message_content = f"Categorize this website using the plain text scrapped below.\n{text_to_classify}"
        messages = [
            {"role": "system", "content": system_message_content},
            {"role": "user", "content": user_message_content}
        ]
        try:
            completion = openai_client.chat.completions.create(
                model=openai_model_name,
                temperature=0,
                messages=messages
            )
            response_text = completion.choices[0].message.content.strip()
            return response_text
        except Exception as e:
            log_callback(f"Error during OpenAI API call: {e}")
            if prompt_type == "exhibitor_fit":
                return json.dumps({"fit_for_expo": "Error", "explanation": f"OpenAI API call failed: {e}"})
            return f"Error: OpenAI API call failed: {e}"

    log_callback("Initializing Google Sheets client...")
    creds_file_path = os.getenv("CREDS_FILE")
    if not creds_file_path:
        log_callback("ERROR: Credentials file path (CREDS_FILE) not set in .env.")
        return
    try:
        gc_client = gspread.service_account(filename=creds_file_path)
        sh_opened = gc_client.open(gsheet_name).worksheet(worksheet_name)
        log_callback("Connected to Google Sheets.")
    except gspread.exceptions.SpreadsheetNotFound:
        log_callback(f"ERROR: Spreadsheet '{gsheet_name}' not found.")
        return
    except gspread.exceptions.WorksheetNotFound:
        log_callback(f"ERROR: Worksheet '{worksheet_name}' not found in spreadsheet '{gsheet_name}'.")
        return
    except Exception as e:
        log_callback(f"Error loading Google Sheets: {e}")
        return

    log_callback("Initializing Selenium WebDriver...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    selenium_driver = None
    try:
        service = ChromeService(ChromeDriverManager().install())
        selenium_driver = webdriver.Chrome(service=service, options=chrome_options)
        log_callback("WebDriver initialized using webdriver-manager.")
    except Exception as e:
        log_callback(f"ERROR initializing Selenium WebDriver with webdriver-manager")
        log_callback("Ensure you have an internet connection for the first run to download ChromeDriver.")
        if selenium_driver:
            selenium_driver.quit()
        return

    def get_text_with_selenium_local(url: str) -> str | None:
        nonlocal selenium_driver
        if not selenium_driver:
            log_callback("ERROR: Selenium driver not initialized when get_text_with_selenium_local was called.")
            return None
        try:
            selenium_driver.set_page_load_timeout(selenium_page_load_timeout)
            selenium_driver.get(url)
            time.sleep(selenium_sleep_after_load)
            html = selenium_driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            for script_or_style in soup(["script", "style"]):
                script_or_style.decompose()
            return soup.get_text(separator=" ", strip=True)
        except (WebDriverException, TimeoutException) as e:
            log_callback(f"Selenium - WebDriver or Timeout error for {url}")
            return None
        except Exception as e:
            log_callback(f"Selenium - Other error for {url}")
            return None

    log_callback(f"Starting processing rows {start_row} - {end_row}...")
    try:
        if end_row < start_row:
            log_callback(f"ERROR: End row ({end_row}) cannot be less than start row ({start_row}).")
            if selenium_driver: selenium_driver.quit()
            return

        company_names_data_range = f"{company_input_column}{start_row}:{company_input_column}{end_row}"
        log_callback(f"Fetching data from range: {company_names_data_range}")
        company_names_data = sh_opened.get(company_names_data_range)

    except gspread.exceptions.APIError as e:
        log_callback(f"Google Sheets API error while fetching data from range {company_names_data_range}: {e}")
        if selenium_driver: selenium_driver.quit()
        return
    except Exception as e:
        log_callback(f"Unexpected error while fetching data from Google Sheets: {e}")
        if selenium_driver: selenium_driver.quit()
        return

    for i, row_data in enumerate(company_names_data):
        current_row_index = start_row + i
        if current_row_index > end_row:
            log_callback(f"Reached defined end_row ({end_row}). Stopping further processing.")
            break

        company_name_or_domain_input = row_data[0] if row_data and len(row_data) > 0 else None
        output_val1, output_val2, output_val3 = "", "", ""

        if not company_name_or_domain_input:
            log_callback(f"Row {current_row_index}: No company name/domain in input column, skipping.")
            if num_expected_outputs >= 1:
                output_val1 = "Error: No input data"
            if first_output_column:
                try: sh_opened.update_acell(f"{first_output_column}{current_row_index}", output_val1)
                except Exception as e_gs: log_callback(f"GS Error updating blank input row {current_row_index} (Col1): {e_gs}")
            if second_output_column:
                 try: sh_opened.update_acell(f"{second_output_column}{current_row_index}", output_val2)
                 except Exception as e_gs: log_callback(f"GS Error updating blank input row {current_row_index} (Col2): {e_gs}")
            if third_output_column:
                 try: sh_opened.update_acell(f"{third_output_column}{current_row_index}", output_val3)
                 except Exception as e_gs: log_callback(f"GS Error updating blank input row {current_row_index} (Col3): {e_gs}")
            continue

        log_callback(f"\n--- Processing company {current_row_index}: {company_name_or_domain_input} ---")

        url_to_scrape = ""
        if not company_name_or_domain_input.startswith(('http://', 'https://')):
            url_to_scrape = "https://" + company_name_or_domain_input.strip()
        else:
            url_to_scrape = company_name_or_domain_input.strip()
        
        log_callback(f"URL to scrape: {url_to_scrape}")
        
        text_content = None
        scraped_with = ""
        REQUESTS_HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        }
        try:
            response = requests.get(url_to_scrape, headers=REQUESTS_HEADERS, timeout=requests_timeout)
            response.raise_for_status()
            if "text/html" in response.headers.get("Content-Type", "").lower():
                soup = BeautifulSoup(response.content, "html.parser")
                for script_or_style in soup(["script", "style"]):
                    script_or_style.decompose()
                text_content = soup.get_text(separator=" ", strip=True)
                scraped_with = "Requests"
            else:
                log_callback(f"Non-HTML content type for {url_to_scrape}: {response.headers.get('Content-Type')}. Trying with Selenium.")
                text_content = get_text_with_selenium_local(url_to_scrape)
                if text_content: scraped_with = "Selenium..."
        except requests.exceptions.RequestException:
            log_callback(f"Requests error for {url_to_scrape}. Trying with Selenium...")
            text_content = get_text_with_selenium_local(url_to_scrape)
            if text_content: scraped_with = "Selenium..."
        except Exception as e_req:
            log_callback(f"Generic request error for {url_to_scrape}: {e_req}. Trying with Selenium...")
            text_content = get_text_with_selenium_local(url_to_scrape)
            if text_content: scraped_with = "Selenium..."

        if text_content:
            log_callback(f"Content retrieved (length: {len(text_content)} chars) using: {scraped_with}")
            clean_text = " ".join(filter(None, (line.strip() for line in text_content.splitlines())))

            log_callback("Starting classification with OpenAI...")
            classification_result_str = classify_with_openai_local(clean_text)

            ## TO UPDATE WITH NEW STRUCTURES

            if prompt_type == "exhibitor_fit":
                parsed_fit = "Error"
                parsed_explanation = "LLM processing error or invalid format"
                
                extracted_json_str = None
                if classification_result_str:
                    match_markdown = re.search(r"```json\s*({.*?})\s*```", classification_result_str, re.DOTALL | re.IGNORECASE)
                    if match_markdown: extracted_json_str = match_markdown.group(1)
                    else:
                        first_brace = classification_result_str.find('{')
                        last_brace = classification_result_str.rfind('}')
                        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                            extracted_json_str = classification_result_str[first_brace : last_brace + 1]
                        else:
                            extracted_json_str = classification_result_str 
                            log_callback(f"Warning: Could not clearly identify JSON structure in LLM output for exhibitor_fit. Raw: {classification_result_str}")
                
                if extracted_json_str:
                    try:
                        llm_data = json.loads(extracted_json_str)
                        parsed_fit = llm_data.get("fit_for_expo", "Error")
                        parsed_explanation = llm_data.get("explanation", "LLM JSON response missing 'explanation' field.")
                        if isinstance(parsed_fit, str) and parsed_fit.lower() in ["yes", "no"]:
                            parsed_fit = parsed_fit.capitalize()
                        else:
                            actual_explanation_from_llm = llm_data.get('explanation', '')
                            log_callback(f"Warning: Invalid value for 'fit_for_expo' from LLM: '{parsed_fit}'. LLM Explanation: '{actual_explanation_from_llm}'")
                            parsed_explanation = f"Invalid 'fit_for_expo' value: {parsed_fit}. LLM Explanation: {actual_explanation_from_llm}"
                            parsed_fit = "Error" 
                    except json.JSONDecodeError:
                        log_callback(f"CRITICAL ERROR: LLM output for exhibitor_fit was not valid JSON. Attempted: '{extracted_json_str}'. Raw: '{classification_result_str}'")
                    except Exception as e_json:
                        log_callback(f"CRITICAL ERROR: Unexpected error parsing LLM JSON for exhibitor_fit: {e_json}. Raw: '{classification_result_str}'")
                else:
                    log_callback(f"Warning: No JSON content from LLM for exhibitor_fit. Raw output (if any): '{classification_result_str}'")
                    if classification_result_str and "Error:" in classification_result_str:
                        parsed_explanation = classification_result_str
                
                if num_expected_outputs >= 1:
                    output_val1 = parsed_fit
                if num_expected_outputs >= 2:
                    output_val2 = parsed_explanation

            elif prompt_type == "name_changer":
                if num_expected_outputs >= 1:
                    output_val1 = classification_result_str 
                log_callback(f"Name changer prompt: LLM output assigned based on num_expected_outputs.")
            
            elif prompt_type is None:
                 log_callback(f"ERROR: Row {current_row_index} - Output assignment skipped due to undefined prompt type for file '{prompt_filename}'.")
                 if num_expected_outputs >= 1:
                    output_val1 = f"Error: Undefined prompt type ('{prompt_filename}')"

        else:
            log_callback(f"Failed to retrieve content for {url_to_scrape}")
            error_message_no_content = "Error: No content retrieved"
            
            if prompt_type == "exhibitor_fit":
                if num_expected_outputs >= 1:
                    output_val1 = "Error" 
                if num_expected_outputs >= 2:
                    output_val2 = error_message_no_content 
            elif prompt_type == "name_changer":
                if num_expected_outputs >= 1:
                    output_val1 = error_message_no_content
            elif prompt_type is None:
                if num_expected_outputs >= 1:
                    output_val1 = f"Error: No content & Undefined prompt ('{prompt_filename}')"
                if num_expected_outputs >= 2: 
                    output_val2 = error_message_no_content
            else:
                if num_expected_outputs >=1:
                    output_val1 = "Error: No content retrieved (Unknown state)"

        log_message_parts = []
        if first_output_column and num_expected_outputs >= 1: log_message_parts.append(f"Col1({first_output_column})='{str(output_val1)[:70]}...'")
        if second_output_column and num_expected_outputs >= 2: log_message_parts.append(f"Col2({second_output_column})='{str(output_val2)[:70]}...'")
        if third_output_column and num_expected_outputs >= 3: log_message_parts.append(f"Col3({third_output_column})='{str(output_val3)[:70]}...'")
        
        if not log_message_parts:
            log_callback(f"Row {current_row_index}: No output columns specified for update based on num_expected_outputs.")
        else:
            log_callback(f"Updating sheet for row {current_row_index}: " + ", ".join(log_message_parts))

        try:
            if first_output_column and num_expected_outputs >= 1:
                sh_opened.update_acell(f"{first_output_column}{current_row_index}", str(output_val1))
            if second_output_column and num_expected_outputs >= 2:
                sh_opened.update_acell(f"{second_output_column}{current_row_index}", str(output_val2))
            if third_output_column and num_expected_outputs >= 3:
                sh_opened.update_acell(f"{third_output_column}{current_row_index}", str(output_val3))
        except Exception as e_gs_update:
            log_callback(f"Error updating Google Sheets for row {current_row_index}: {e_gs_update}")

        time.sleep(1)

    if selenium_driver:
        selenium_driver.quit()
    log_callback("Processing finished. WebDriver closed.")

# if __name__ == "__main__":
#     def console_logger(message):
#         print(message)

#     load_dotenv()

#     if not os.path.exists("./prompts"):
#         os.makedirs("./prompts")
#     if not os.path.exists("./prompts/exhibitor_fit.txt"):
#         with open("./prompts/exhibitor_fit.txt", "w", encoding="utf-8") as f:
#             f.write("System prompt for exhibitor_fit: Determine if the company from the website text is a good fit for an expo. Respond in JSON with 'fit_for_expo' (Yes/No) and 'explanation'.")
#     if not os.path.exists("./prompts/name_changer.txt"):
#         with open("./prompts/name_changer.txt", "w", encoding="utf-8") as f:
#             f.write("System prompt for name_changer: Suggest a new company name based on the website text.")

#     print("\n--- TESTING EXHIBITOR FIT (2 outputs expected: fit, explanation) ---")
#     run_core_logic(
#         prompt_full_path="./prompts/exhibitor_fit.txt",
#         num_expected_outputs=2, 
#         gsheet_name="Test PD",
#         worksheet_name="Data",
#         start_row=2,
#         end_row=3, 
#         company_input_column="B",
#         first_output_column="D",
#         second_output_column="E",
#         third_output_column="F",
#         log_callback=console_logger
#     )

    # print("\n--- TESTING NAME CHANGER (1 output expected: new name) ---")
    # run_core_logic(
    #     prompt_full_path="./prompts/name_changer.txt",
    #     num_expected_outputs=1,
    #     gsheet_name="Test PD", # Zastąp swoją nazwą arkusza testowego
    #     worksheet_name="Data",  # Zastąp swoją nazwą zakładki testowej
    #     start_row=4, 
    #     end_row=10,
    #     company_input_column="B", 
    #     first_output_column="I",  # Tutaj trafi nowa nazwa
    #     second_output_column="", # Ta kolumna nie zostanie użyta (output_val2 będzie "")
    #     third_output_column="",  # Ta kolumna nie zostanie użyta (output_val3 będzie "")
    #     log_callback=console_logger
    # )

    # print("\n--- TESTING EXHIBITOR FIT (1 output expected: only fit) ---")
    # run_core_logic(
    #     prompt_full_path="./prompts/exhibitor_fit.txt",
    #     num_expected_outputs=2, # Oczekujemy tylko 1 wartość: fit
    #     gsheet_name="Test PD",
    #     worksheet_name="Data",
    #     start_row=2,
    #     end_row=6,
    #     company_input_column="B",
    #     first_output_column="E",  # Tutaj trafi 'fit'
    #     second_output_column="F", # Ta kolumna nie zostanie użyta, bo num_expected_outputs=1
    #     third_output_column="",  # Ta kolumna nie zostanie użyta
    #     log_callback=console_logger
    # )