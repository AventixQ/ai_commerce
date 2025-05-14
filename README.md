# Company Website Analyzer

## Project Overview

The Company Website Analyzer is a Streamlit-based application designed to analyze company websites. It fetches website content, processes it using an OpenAI language model based on selected analysis types (prompts), and outputs the results, typically to a Google Sheet. Its modular design allows for various types of website content analysis.

The application allows users to:
* Select different analysis types (e.g., "Exhibitor Fit Analysis", "Company Name Changer").
* Configure Google Sheets integration for input (company domains) and output.
* Specify a range of rows in the Google Sheet to process.
* View real-time logs of the analysis process.

## Project Structure

The project is organized into the following main files and directories:

* **`app_interface.py`**: The main Streamlit application file. It handles the user interface, input collection, validation, and initiates the core processing logic. It also dynamically loads and manages different analysis types through "Prompt Handlers".
* **`core_processor.py`**: Contains the core logic for processing each company/domain. This includes fetching website content (using `requests` and `selenium`), interacting with the OpenAI API, and updating the Google Sheet with results. It uses the appropriate Prompt Handler to interpret LLM responses.
* **`prompt_handlers/`**: This directory is a Python package containing individual "Prompt Handler" modules.
    * **`base_handler.py`**: Defines an abstract base class (`BasePromptHandler`) that all specific handlers should inherit from, ensuring a consistent interface.
    * **`*_handler.py`** (e.g., `exhibitor_fit_handler.py`, `name_changer_handler.py`): Each file defines a specific handler class responsible for a particular type of analysis.
* **`prompts/`**: This directory stores the text files (`.txt`) containing the system prompts fed to the OpenAI model for each analysis type. The filename (e.g., `exhibitor_fit.txt`) corresponds to the `file_base` configured in its respective handler.
* **`.env`**: A file (not committed to version control) to store environment variables, primarily `OPENAI_API_KEY` and `CREDS_FILE` (path to Google Cloud service account credentials JSON).
* **`requirements.txt`** (or similar): Lists project dependencies (though installation instructions will use `uv`).

## Prompt Handlers

Prompt Handlers are a key architectural feature of this project, enabling modularity and easy extensibility. Each handler is a Python class responsible for a specific type of analysis.

**Role of a Handler:**
1.  **Configuration:** Defines its display name (for the UI), the base filename of its system prompt (in the `prompts/` directory), the number of expected outputs, and labels for these outputs.
2.  **LLM Response Processing:** Implements logic to parse and interpret the raw text response from the OpenAI model according to the specific analysis type.
3.  **Edge Case Handling:** Provides default outputs for scenarios like failing to retrieve website content or missing input data.
4.  **Identification:** Provides a unique key to identify itself.

**Creating a New Handler:**
1.  Add a new `.txt` system prompt file to the `prompts/` directory.
2.  Create a new Python file (e.g., `new_analysis_handler.py`) in the `prompt_handlers/` directory.
3.  Define a new class in this file, inheriting from `BasePromptHandler` (or implementing its methods via duck-typing).
4.  Implement the required static methods: `get_prompt_key()`, `get_config()`, `process_llm_response()`, `handle_no_content()`, and optionally `handle_no_input_data()`.

The application will automatically discover and load new, correctly implemented handlers.

## Setup and Installation

Follow these steps to set up and run the project locally.

#### 1. Clone the Repository

git clone <your-repository-url>
cd <repository-directory-name>

#### 2. Install Dependencies with `uv`.

This project uses uv for fast dependency management. If you don't have `uv` installed, you can install it first (see uv's official documentation). Run uv in project. This should start `.venv` and download all need libraries.

```
uv init
uv sync
```

(Ensure this list matches all necessary packages used in your project.)

#### 3. Set Up Environment Variables

Create a `.env` file in the root directory of the project. This file will store your API keys and credentials path. Do not commit this file to version control.

Add the following lines to your `.env` file, replacing the placeholder values with your actual credentials:

```
OPENAI_API_KEY="your_openai_api_key_here"
CREDS_FILE="./path/to/your/google-credentials.json" 
# Example: CREDS_FILE="./google-service-account.json"
# Make sure the path is correct relative to the project root, or use an absolute path.
```

* OPENAI_API_KEY: Your secret API key from OpenAI.
* CREDS_FILE: The path to your Google Cloud service account JSON key file. This service account needs permission to access the Google Sheets you intend to use.
    * Remember to share your Google Sheets with the service account email address found in this JSON file (e.g., your-service-account-name@your-project-id.iam.gserviceaccount.com).

#### 4. ChromeDriver (for Selenium).

The webdriver-manager library (installed as a dependency) should automatically download and manage ChromeDriver for Selenium. An internet connection is required for the first time it runs or when an update is needed.

## Running the Application

Once the setup is complete, you can run the Streamlit application using:

`streamlit run app_interface.py`

This will start a local web server, and the application should open in your default web browser. You can then configure the analysis parameters in the sidebar and run