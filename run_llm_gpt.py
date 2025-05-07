import os
import time
from urllib.parse import urlparse
import gspread
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from openai import OpenAI
import json
import re

load_dotenv()

OPENAI_MODEL = "gpt-4o-mini"
PROMPTS_FOLDER = "./prompts/"
prompt_filename = "exhibitor_fit"
full_path_prompt = PROMPTS_FOLDER + prompt_filename + ".txt"

CREDS_FILE_PATH = os.getenv("CREDS_FILE")
GSHEET_NAME = "Test PD"
WORKSHEET_NAME = "Data"

START_ROW = 2
END_ROW = 100

REQUESTS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
}
REQUESTS_TIMEOUT = 4
SELENIUM_PAGE_LOAD_TIMEOUT = 10
SELENIUM_SLEEP_AFTER_LOAD = 2

COMPANY_INPUT_COLUMN = "B"
INPUT_COLUMN1 = "D"
INPUT_COLUMN2 = "E"
INPUT_COLUMN3 = "F"

# --- Initialization ---

system_message_content = ""
try:
    with open(full_path_prompt, "r", encoding="utf-8") as f:
        system_message_content = f.read()
    if not system_message_content.strip():
        raise ValueError("System prompt file is empty.")
    print(f"System prompt loaded from: {full_path_prompt}")
except FileNotFoundError:
    print(f"ERROR: System prompt file not found: {full_path_prompt}")
    exit()
except Exception as e:
    print(f"ERROR loading system prompt file: {e}")
    exit()

openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    print("ERROR: OPENAI_API_KEY environment variable not found.")
    exit()
try:
    client = OpenAI(api_key=openai_api_key)
    print("OpenAI client initialized successfully.")
except Exception as e:
    print(f"ERROR initializing OpenAI client: {e}")
    exit()

def classify_with_openai(text_to_classify: str) -> str:
    """
    Classifies text using the configured OpenAI model.
    Returns the raw string response from the API (expected to be JSON).
    """
    if not text_to_classify:
        # Return an error JSON string
        return json.dumps({"fit_for_expo": "Error", "explanation": "No text provided for classification"})

    user_message_content = f"""Categorize this website using the plain text scrapped below.
{text_to_classify}"""

    messages = [
        {"role": "system", "content": system_message_content},
        {"role": "user", "content": user_message_content}
    ]
    
    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            messages=messages
        )
        response_text = completion.choices[0].message.content.strip()
        return response_text
    except Exception as e:
        print(f"Error during OpenAI API call: {e}")
        return json.dumps({"fit_for_expo": "Error", "explanation": f"OpenAI API call failed: {e}"})

def get_text_with_selenium(url: str, driver_instance) -> str | None:
    """
    Fetches website text content using Selenium.
    """
    try:
        driver_instance.set_page_load_timeout(SELENIUM_PAGE_LOAD_TIMEOUT)
        driver_instance.get(url)
        time.sleep(SELENIUM_SLEEP_AFTER_LOAD) 
        html = driver_instance.page_source
        soup = BeautifulSoup(html, "html.parser")
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
        return soup.get_text(separator=" ", strip=True)
    except (WebDriverException, TimeoutException) as e:
        print(f"Selenium - WebDriver or Timeout error for {url}: {e}")
        return None
    except Exception as e:
        print(f"Selenium - Other error for {url}: {e}")
        return None

# --- Main Script Logic ---
def main():
    print("Starting Google Sheets client...")
    if not CREDS_FILE_PATH:
        print("Error: wrong creds file path.")
        return
    try:
        gc_client = gspread.service_account(filename=CREDS_FILE_PATH)
        sh_opened = gc_client.open(GSHEET_NAME).worksheet(WORKSHEET_NAME)
        print("Connected with Google Sheets.")
    except Exception as e:
        print(f"Error during loading GS: {e}")
        return

    print("Initializing Selenium WebDriver...")
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    selenium_driver = webdriver.Chrome(options=chrome_options)
    print("WebDriver init.")

    print(f"Start processing rows {START_ROW} - {END_ROW}...")
    try:
        company_names_data = sh_opened.get(f"{COMPANY_INPUT_COLUMN}{START_ROW}:{COMPANY_INPUT_COLUMN}{END_ROW}")
    except Exception as e:
        print(f"Error during downloading GS: {e}")
        selenium_driver.quit()
        return

    for i, row_data in enumerate(company_names_data):
        current_row_index = START_ROW + i
        
        company_name_or_domain = row_data[0] if row_data and len(row_data) > 0 else None

        if not company_name_or_domain:
            print(f"Row {current_row_index}: No name/domain, skipping.")
            continue

        print(f"\n--- Processing company {current_row_index}: {company_name_or_domain} ---")
        
        if not company_name_or_domain.startswith(('http://', 'https://')):
            url = "https://" + company_name_or_domain.strip()
        else:
            url = company_name_or_domain.strip()
        
        print(f"URL: {url}")
        text_content = None
        scraped_with = ""

        try:
            response = requests.get(url, headers=REQUESTS_HEADERS, timeout=REQUESTS_TIMEOUT)
            response.raise_for_status() 
            if "text/html" in response.headers.get("Content-Type", "").lower():
                soup = BeautifulSoup(response.content, "html.parser")
                for script_or_style in soup(["script", "style"]): 
                    script_or_style.decompose()
                text_content = soup.get_text(separator=" ", strip=True)
                scraped_with = "Requests"
            else:
                print(f"Non-HTML content type for {url}: {response.headers.get('Content-Type')}. Trying with Selenium.")
                text_content = get_text_with_selenium(url, selenium_driver)
                if text_content: scraped_with = "Selenium (after non-HTML)"

        except requests.exceptions.RequestException as e:
            print(f"Requests error for {url}. Trying with Selenium...")
            text_content = get_text_with_selenium(url, selenium_driver)
            if text_content: scraped_with = "Selenium (after requests error)"
        
        if text_content:
            print(f"Content retrieved (length: {len(text_content)} chars) using: {scraped_with}")
            clean_text = " ".join(filter(None, (line.strip() for line in text_content.splitlines())))
            
            print("Starting classification with OpenAI...")
            classification_result_str = classify_with_openai(clean_text) # Call the new OpenAI function
            print(f"Raw LLM output: {classification_result_str}")

            # --- START OF ROBUST JSON EXTRACTION AND PARSING LOGIC ---
            parsed_fit = "Error"
            parsed_explanation = "Invalid format from LLM (initial)"
            
            extracted_json_str = None
            if classification_result_str: 
                match_markdown = re.search(r"```json\s*({.*?})\s*```", classification_result_str, re.DOTALL | re.IGNORECASE)
                if match_markdown:
                    extracted_json_str = match_markdown.group(1)
                    print(f"Extracted JSON from markdown: {extracted_json_str}")
                else:
                    first_brace = classification_result_str.find('{')
                    last_brace = classification_result_str.rfind('}')
                    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                        extracted_json_str = classification_result_str[first_brace : last_brace + 1]
                        print(f"Extracted JSON by finding braces: {extracted_json_str}")
                    else:
                        extracted_json_str = classification_result_str 
                        print(f"Warning: Could not clearly identify JSON structure. Attempting to parse raw output as is.")
            
            if extracted_json_str:
                try:
                    llm_data = json.loads(extracted_json_str)
                    
                    parsed_fit = llm_data.get("fit_for_expo", "Error") 
                    parsed_explanation = llm_data.get("explanation", "LLM JSON response missing 'explanation' field.")

                    if isinstance(parsed_fit, str) and parsed_fit.lower() in ["yes", "no"]:
                        parsed_fit = parsed_fit.capitalize()
                    else:
                        print(f"Warning: Invalid value for 'fit_for_expo' from LLM: '{parsed_fit}'. Original explanation: '{parsed_explanation}'")
                        parsed_explanation = f"Invalid 'fit_for_expo' value: {parsed_fit}. LLM explanation: {llm_data.get('explanation', '')}"
                        parsed_fit = "Error"
                        
                except json.JSONDecodeError:
                    print(f"CRITICAL ERROR: Extracted string or LLM output was not valid JSON. Extracted attempt: '{extracted_json_str}'. Raw output: '{classification_result_str}'")
                    parsed_explanation = f"LLM output not valid JSON. Raw: {classification_result_str}"
                except Exception as e: 
                    print(f"CRITICAL ERROR: Unexpected error parsing extracted LLM JSON output: {e}. Extracted: '{extracted_json_str}'. Raw: '{classification_result_str}'")
                    parsed_explanation = f"Unexpected error parsing LLM JSON. Raw: {classification_result_str}"
            else: 
                print(f"Warning: No extractable JSON content found in LLM output. Raw output: '{classification_result_str}'")
                parsed_explanation = f"No extractable JSON content. Raw: {classification_result_str}"

            fit_to_write = parsed_fit
            explanation_to_write = parsed_explanation
            actual_domain_from_url = urlparse(url).netloc.replace("www.", "")
            
            print(f"Updating sheet for domain: {actual_domain_from_url}, Fit: {fit_to_write}, Explanation: {explanation_to_write}")
            try:
                sh_opened.update_acell(f"{INPUT_COLUMN1}{current_row_index}", actual_domain_from_url)
                sh_opened.update_acell(f"{INPUT_COLUMN2}{current_row_index}", fit_to_write)
                sh_opened.update_acell(f"{INPUT_COLUMN3}{current_row_index}", explanation_to_write)
            except Exception as e:
                print(f"Error updating Google Sheets for row {current_row_index}: {e}")

        else:
            print(f"Failed to retrieve content for {url}")
            try:
                sh_opened.update_acell(f"{INPUT_COLUMN2}{current_row_index}", "Error") 
                sh_opened.update_acell(f"{INPUT_COLUMN3}{current_row_index}", "No content retrieved")
            except Exception as e:
                print(f"Error updating Google Sheets (No content) for row {current_row_index}: {e}")
        
        time.sleep(1)

    selenium_driver.quit()
    print("Processing finished. WebDriver closed.")

if __name__ == "__main__":
    main()