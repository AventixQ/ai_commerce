# prompt_handlers/name_changer_handler.py
from typing import Dict, Any, Tuple, Callable
from .base_handler import BasePromptHandler

class NameChangerHandler(BasePromptHandler):
    PROMPT_KEY = "name_changer"

    @staticmethod
    def get_prompt_key() -> str:
        return NameChangerHandler.PROMPT_KEY

    @staticmethod
    def get_config() -> Dict[str, Any]:
        return {
            "display_name": "Company Name Changer",
            "file_base": NameChangerHandler.PROMPT_KEY,
            "num_outputs": 1,
            "output_labels": ["Column: New company name"]
        }

    @staticmethod
    def process_llm_response(
        llm_response_str: str,
        num_expected_outputs: int,
        log_callback: Callable[[str], None]
    ) -> Tuple[str, ...]:
        if not llm_response_str:
            log_callback(f"Handler '{NameChangerHandler.PROMPT_KEY}': LLM response string is empty.")
            output_val1 = "Error: LLM response empty"
        else:
            output_val1 = llm_response_str.strip()
        outputs = [output_val1]
        return tuple( (outputs + [""] * (num_expected_outputs - len(outputs)))[:num_expected_outputs] )


    @staticmethod
    def handle_no_content(
        num_expected_outputs: int,
        log_callback: Callable[[str], None]
    ) -> Tuple[str, ...]:
        log_callback(f"Handler '{NameChangerHandler.PROMPT_KEY}': No content retrieved for website.")
        output_val1 = "Error: No content retrieved"
        outputs = [output_val1]
        return tuple( (outputs + [""] * (num_expected_outputs - len(outputs)))[:num_expected_outputs] )