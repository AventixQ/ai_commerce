# prompt_handlers/base_handler.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Callable

class BasePromptHandler(ABC):
    """
    Abstract base class for prompt-specific handlers.
    """

    @staticmethod
    @abstractmethod
    def get_config() -> Dict[str, Any]:
        """
        Returns the configuration for this type of prompt.
        Should contain keys like: 'display_name', 'file_base', 'num_outputs', 'output_labels'.
        """
        pass

    @staticmethod
    @abstractmethod
    def process_llm_response(
        llm_response_str: str,
        num_expected_outputs: int,
        log_callback: Callable[[str], None]
    ) -> Tuple[str, ...]:
        """
        Processes the raw text response from the LLM.
        Returns a tuple of strings with the results. The length of the tuple should match
        'num_expected_outputs' from the handler configuration, padded with empty strings
        or error messages as needed.
        """
        pass

    @staticmethod
    @abstractmethod
    def handle_no_content(
        num_expected_outputs: int,
        log_callback: Callable[[str], None]
    ) -> Tuple[str, ...]:
        """
        Returns a tuple of strings with results if the page content could not be fetched.
        The length of the tuple should correspond to 'num_expected_outputs'.
        """
        pass

    @staticmethod
    @abstractmethod
    def get_prompt_key() -> str:
        """
        Returns a unique key identifying this prompt type (e.g. 'exhibitor_fit').
        May be the same as 'file_base'.
        """
        pass