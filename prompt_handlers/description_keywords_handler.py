# prompt_handlers/exhibitor_fit_handler.py
import json
import re
from typing import Dict, Any, Tuple, Callable, Optional
from .base_handler import BasePromptHandler


class DescriptionKeywordHandler(BasePromptHandler):
    """
    Handler for "Description and Keys" prompt.
    Creates short description of company and search for keywords characterizing company.
    """
    PROMPT_KEY: str = "description_keywords"

    @staticmethod
    def get_handler_category() -> str:
        return "scrape_and_llm"

    @staticmethod
    def get_prompt_key() -> str:
        """Returns the unique key for this prompt handler."""
        return DescriptionKeywordHandler.PROMPT_KEY

    @staticmethod
    def get_config() -> Dict[str, Any]:
        """
        Returns the configuration for this prompt type, including display name,
        file base for the prompt text, number of expected outputs, and their labels.
        """
        return {
            "display_name": "Description and Keywords creator",
            "file_base": DescriptionKeywordHandler.PROMPT_KEY,
            "num_outputs": 2,
            "output_labels": ["Column: Description", "Column: Keywords"]
        }

    @staticmethod
    def process_llm_response(
        llm_response_str: str,
        num_expected_outputs: int,
        log_callback: Callable[[str], None]
    ) -> Tuple[str, ...]:
        """
        Processes the raw string response from the LLM.
        For description and keys, it expects a JSON object with 'description' and 'keywords'.
        """
        parsed_description: str = "Error"
        parsed_keywords: str = "LLM processing error or invalid format"

        if not llm_response_str or not llm_response_str.strip():
            log_callback(f"Handler '{DescriptionKeywordHandler.PROMPT_KEY}': LLM response string is empty or whitespace.")
        else:
            extracted_json_str: Optional[str] = None
            match_markdown = re.search(r"```json\s*({.*?})\s*```", llm_response_str, re.DOTALL | re.IGNORECASE)
            if match_markdown:
                extracted_json_str = match_markdown.group(1)
                log_callback(f"Handler '{DescriptionKeywordHandler.PROMPT_KEY}': Extracted JSON from markdown block.")
            else:
                first_brace = llm_response_str.find('{')
                last_brace = llm_response_str.rfind('}')
                if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                    extracted_json_str = llm_response_str[first_brace : last_brace + 1]
                    log_callback(f"Handler '{DescriptionKeywordHandler.PROMPT_KEY}': Extracted JSON by finding braces.")
                else:
                    log_callback(f"Warning: Handler '{DescriptionKeywordHandler.PROMPT_KEY}' could not clearly identify JSON structure in LLM response. Raw response: '{llm_response_str[:200]}...'")

            if extracted_json_str:
                try:
                    llm_data: Dict[str, Any] = json.loads(extracted_json_str)
                    
                    parsed_description = str(llm_data.get("description", "Error")).strip()
                    parsed_keywords = str(llm_data.get("keywords", "LLM JSON response missing 'explanation' field.")).strip()
                    
                    if isinstance(llm_data.get("keywords"), list):
                        parsed_keywords = ", ".join(str(item) for item in llm_data.get("keywords", []))
                    else:
                        parsed_keywords = parsed_keywords.replace('[', '')
                        parsed_keywords = parsed_keywords.replace(']', '')
                        parsed_keywords = parsed_keywords.replace("'", "")

                    log_callback(f"Handler '{DescriptionKeywordHandler.PROMPT_KEY}': Parsed LLM data - Description: {parsed_description[:50]}, Keywords: {parsed_keywords[:10]}...")

                except json.JSONDecodeError:
                    log_callback(f"CRITICAL ERROR: Handler '{DescriptionKeywordHandler.PROMPT_KEY}' - LLM output was not valid JSON. Attempted to parse: '{extracted_json_str[:200]}...'. Raw LLM response: '{llm_response_str[:200]}...'")
                    parsed_keywords = f"Invalid JSON from LLM: {llm_response_str[:100]}..."
                except Exception as e_json:
                    log_callback(f"CRITICAL ERROR: Handler '{DescriptionKeywordHandler.PROMPT_KEY}' - Unexpected error parsing LLM JSON: {type(e_json).__name__} - {e_json}. Raw LLM response: '{llm_response_str[:200]}...'")
                    parsed_keywords = f"Error parsing LLM JSON: {str(e_json)[:100]}..."
            else:
                log_callback(f"Warning: Handler '{DescriptionKeywordHandler.PROMPT_KEY}' - No JSON content could be extracted from LLM. Raw output (if any): '{llm_response_str[:200]}...'")
                if llm_response_str and "error" in llm_response_str.lower():
                    parsed_keywords = f"LLM indicated an error: {llm_response_str[:150]}"
        outputs_list = [parsed_description, parsed_keywords]
        
        final_outputs = (outputs_list + [""] * num_expected_outputs)[:num_expected_outputs]
        return tuple(final_outputs)

    @staticmethod
    def handle_no_content(
        num_expected_outputs: int,
        log_callback: Callable[[str], None]
    ) -> Tuple[str, ...]:
        """
        Returns a tuple of strings to be used when website content could not be retrieved.
        """
        log_callback(f"Handler '{DescriptionKeywordHandler.PROMPT_KEY}': No content retrieved for website. Generating 'no content' outputs.")
        output_val1 = "Error"
        output_val2 = "Error: No website content retrieved"
        
        outputs_list = [output_val1, output_val2]
        final_outputs = (outputs_list + [""] * num_expected_outputs)[:num_expected_outputs]
        return tuple(final_outputs)

    @staticmethod
    def handle_no_input_data(
        num_expected_outputs: int,
        log_callback: Callable[[str], None]
    ) -> Tuple[str, ...]:
        """
        Returns a tuple of strings when the input data (e.g., company domain) is missing from the sheet.
        """
        log_callback(f"Handler '{DescriptionKeywordHandler.PROMPT_KEY}': No input data from sheet. Generating 'no input' outputs.")
        output_val1 = "Error"
        output_val2 = "Error: No input data from sheet"

        outputs_list = [output_val1, output_val2]
        final_outputs = (outputs_list + [""] * num_expected_outputs)[:num_expected_outputs]
        return tuple(final_outputs)

