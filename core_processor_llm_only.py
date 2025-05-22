# core_processor.py
import os
import time
from typing import Dict, Type, Callable, Tuple, List, Any, Optional

import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI, OpenAIError

# Zakładając, że prompt_handlers.base_handler jest dostępne w PYTHONPATH
from prompt_handlers.base_handler import BasePromptHandler

# Konfiguracja
LLM_MODEL_NAME = "gpt-4o-mini"
LLM_REQUEST_TIMEOUT = 180  # sekundy na zapytania do LLM (może być dłużej z wyszukiwaniem)

def get_col_index(col_str: str) -> int:
    """Konwertuje literowy identyfikator kolumny (A, B, AA) na indeks numeryczny (1-based)."""
    if not col_str or not col_str.isalpha():
        raise ValueError(f"Nieprawidłowy identyfikator kolumny: '{col_str}'. Musi zawierać tylko litery.")
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
    company_input_column: str, # Litera kolumny z domenami/formułami
    first_output_column: str,  # Litera kolumny
    second_output_column: str, # Litera kolumny
    third_output_column: str,  # Litera kolumny
    log_callback: Callable[[str], None]
):
    """
    Główna logika przetwarzania danych firm z Google Sheets przy użyciu LLM 
    (z wyszukiwaniem webowym przez LLM, zgodnie z podaną składnią) i handlerów promptów.
    """
    log_callback("Inicjacja logiki głównej (z wyszukiwaniem webowym przez LLM via client.responses.create).")

    # --- 1. Inicjalizacja ---
    log_callback("Inicjalizacja klientów i ładowanie zasobów...")
    creds_file = os.getenv("CREDS_FILE")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not creds_file or not os.path.exists(creds_file):
        log_callback(f"❌ BŁĄD: Plik poświadczeń Google nie znaleziony lub nie ustawiony przez CREDS_FILE. Ścieżka: {creds_file}")
        raise ValueError(f"Plik poświadczeń Google nie znaleziony lub nie ustawiony przez CREDS_FILE. Ścieżka: {creds_file}")
    if not openai_api_key:
        log_callback("❌ BŁĄD: Klucz API OpenAI nie ustawiony przez OPENAI_API_KEY.")
        raise ValueError("Klucz API OpenAI nie ustawiony przez OPENAI_API_KEY.")

    try:
        gc = gspread.service_account(filename=creds_file)
        sh = gc.open(gsheet_name)
        worksheet = sh.worksheet(worksheet_name)
        log_callback(f"Pomyślnie połączono z Google Sheet: '{gsheet_name}' -> Arkusz: '{worksheet_name}'.")
    except Exception as e:
        log_callback(f"❌ BŁĄD: Nie można połączyć się z Google Sheets: {type(e).__name__} - {e}")
        raise

    try:
        openai_client = OpenAI(api_key=openai_api_key, timeout=LLM_REQUEST_TIMEOUT)
        log_callback(f"Klient OpenAI zainicjalizowany dla modelu {LLM_MODEL_NAME}.")
    except Exception as e:
        log_callback(f"❌ BŁĄD: Nie można zainicjalizować klienta OpenAI: {type(e).__name__} - {e}")
        raise

    if prompt_handler_key not in available_handlers:
        log_callback(f"❌ BŁĄD: Handler promptu dla klucza '{prompt_handler_key}' nie znaleziony.")
        raise ValueError(f"Handler '{prompt_handler_key}' niedostępny.")
    handler_class: Type[BasePromptHandler] = available_handlers[prompt_handler_key]
    log_callback(f"Używany handler promptu: {handler_class.__name__}")

    try:
        with open(prompt_full_path, 'r', encoding='utf-8') as f:
            prompt_template_content = f.read() # Ten string będzie użyty jako 'input' dla LLM
        log_callback(f"Pomyślnie załadowano szablon promptu z: {prompt_full_path}")
    except Exception as e:
        log_callback(f"❌ BŁĄD: Nie można odczytać pliku promptu '{prompt_full_path}': {type(e).__name__} - {e}")
        raise

    output_column_letters_map: List[str] = []
    if num_expected_outputs >= 1 and first_output_column: output_column_letters_map.append(first_output_column)
    if num_expected_outputs >= 2 and second_output_column: output_column_letters_map.append(second_output_column)
    if num_expected_outputs >= 3 and third_output_column: output_column_letters_map.append(third_output_column)
    
    actual_output_column_letters = output_column_letters_map[:num_expected_outputs]
    if len(actual_output_column_letters) < num_expected_outputs:
        log_callback(f"⚠️ OSTRZEŻENIE: Prompt oczekuje {num_expected_outputs} wyników, ale tylko {len(actual_output_column_letters)} kolumn wyjściowych jest skonfigurowanych/poprawnych.")

    output_col_indices = [get_col_index(col_letter) for col_letter in actual_output_column_letters]
    company_input_col_idx = get_col_index(company_input_column)

    log_callback(f"Kolumna wejściowa: {company_input_column} (indeks {company_input_col_idx}). Kolumny wyjściowe: {actual_output_column_letters} (indeksy {output_col_indices}).")
    log_callback("--- Rozpoczęcie przetwarzania wierszy ---")

    for current_row_index in range(start_row, end_row + 1):
        log_callback(f"\nPrzetwarzanie wiersza {current_row_index}...")
        outputs_for_sheet: Tuple[str, ...] = tuple([""] * num_expected_outputs)

        try:
            domain_or_formula = worksheet.cell(current_row_index, company_input_col_idx).value
            if not domain_or_formula or not str(domain_or_formula).strip():
                log_callback(f"Wiersz {current_row_index}, Kol {company_input_column}: Puste wejście. Pomijanie.")
                time.sleep(0.1)
                continue
            
            domain_or_formula = str(domain_or_formula).strip()
            log_callback(f"Wiersz {current_row_index}, Kol {company_input_column}: Odczytano '{domain_or_formula}'.")

            # --- Przygotowanie danych wejściowych dla LLM ---
            # Szablon promptu powinien być zaprojektowany tak, aby LLM użył wyszukiwania.
            # Przykład placeholdera: {domain}
            try:
                # prompt_template_content jest całym stringiem wejściowym dla LLM
                filled_input_for_llm = prompt_template_content.format(domain=domain_or_formula)
            except KeyError as e:
                log_callback(f"❌ BŁĄD: Szablon promptu '{prompt_full_path}' nie zawiera wymaganego placeholdera: {e}.")
                log_callback("Pominięcie wywołania LLM dla tego wiersza z powodu błędu szablonu.")
                outputs_for_sheet = tuple(["Błąd szablonu promptu"] * num_expected_outputs)
            else:
                # --- Wywołanie LLM z narzędziem web_search_preview używając client.responses.create ---
                log_callback(f"Wysyłanie promptu dla '{domain_or_formula}' do LLM (model: {LLM_MODEL_NAME} z client.responses.create)...")
                try:
                    # Użycie client.responses.create zgodnie z Twoim przykładem
                    if not hasattr(openai_client, 'responses') or not hasattr(openai_client.responses, 'create'):
                        log_callback(f"❌ KRYTYCZNY BŁĄD: Obiekt klienta OpenAI ({type(openai_client)}) nie posiada metody 'responses.create'. Sprawdź wersję biblioteki OpenAI lub środowisko.")
                        raise AttributeError("Metoda 'openai_client.responses.create' nie jest dostępna.")

                    llm_api_response = openai_client.responses.create(
                        model=LLM_MODEL_NAME,
                        tools=[
                            {
                                "type": "web_search_preview",
                            }
                        ],
                        input=filled_input_for_llm # Użycie sformatowanego stringu jako 'input'
                    )
                    
                    llm_response_str = ""
                    if hasattr(llm_api_response, 'output_text'):
                        llm_response_str = llm_api_response.output_text
                    else:
                        log_callback(f"⚠️ OSTRZEŻENIE: Odpowiedź LLM (typ: {type(llm_api_response)}) nie zawiera oczekiwanego atrybutu 'output_text'. Sprawdź strukturę odpowiedzi. Odpowiedź: {llm_api_response}")

                    if not llm_response_str:
                         log_callback(f"⚠️ LLM zwrócił pustą odpowiedź (output_text) dla '{domain_or_formula}'.")
                         llm_response_str = "" 

                    log_callback(f"Otrzymano odpowiedź LLM. Przetwarzanie przez handler '{handler_class.__name__}'...")
                    outputs_for_sheet = handler_class.process_llm_response(
                        llm_response_str, num_expected_outputs, log_callback
                    )

                except OpenAIError as e: # Ogólny błąd API OpenAI
                    error_detail = str(e)
                    if hasattr(e, 'response') and e.response is not None and hasattr(e.response, 'text'):
                        error_detail = f"{e} - API Response: {e.response.text}"
                    log_callback(f"❌ Błąd API OpenAI dla '{domain_or_formula}': {type(e).__name__} - {error_detail}")
                    outputs_for_sheet = tuple([f"Błąd LLM: {type(e).__name__}"] * num_expected_outputs)
                except AttributeError as e_attr: # Jeśli .responses.create lub .output_text nie istnieje
                     log_callback(f"❌ Błąd Atrybutu (prawdopodobnie problem z SDK OpenAI) dla '{domain_or_formula}': {e_attr}")
                     outputs_for_sheet = tuple([f"Błąd SDK OpenAI: {e_attr}"] * num_expected_outputs)
                except Exception as e: # Inne nieoczekiwane błędy
                    log_callback(f"❌ Nieoczekiwany błąd podczas wywołania LLM lub przetwarzania przez handler dla '{domain_or_formula}': {type(e).__name__} - {e}")
                    outputs_for_sheet = tuple([f"Błąd przetwarzania: {type(e).__name__}"] * num_expected_outputs)

            # --- Zapis do Arkusza ---
            if len(outputs_for_sheet) != num_expected_outputs:
                 log_callback(f"⚠️ OSTRZEŻENIE: Handler zwrócił {len(outputs_for_sheet)} wartości, oczekiwano {num_expected_outputs}. Uzupełnianie/obcinanie.")
                 outputs_for_sheet = (list(outputs_for_sheet) + [""] * num_expected_outputs)[:num_expected_outputs]

            cells_to_update = []
            for i, col_idx in enumerate(output_col_indices):
                if i < len(outputs_for_sheet):
                    cell_value = outputs_for_sheet[i]
                    cells_to_update.append(gspread.Cell(row=current_row_index, col=col_idx, value=str(cell_value if cell_value is not None else "")))
            
            if cells_to_update:
                worksheet.update_cells(cells_to_update, value_input_option='USER_ENTERED')
                log_callback(f"Wiersz {current_row_index}: Zaktualizowano arkusz wynikami.")

        except Exception as e: # Ogólny błąd przetwarzania wiersza
            log_callback(f"❌ Nieoczekiwany błąd podczas przetwarzania wiersza {current_row_index}: {type(e).__name__} - {e}")
            outputs_for_sheet = tuple([f"Nieoczekiwany błąd wiersza: {type(e).__name__}"] * num_expected_outputs)
            cells_to_update = [] # Spróbuj zapisać błąd do arkusza
            for i, col_idx in enumerate(output_col_indices):
                if i < len(outputs_for_sheet):
                    cells_to_update.append(gspread.Cell(row=current_row_index, col=col_idx, value=str(outputs_for_sheet[i])))
            if cells_to_update:
                try:
                    worksheet.update_cells(cells_to_update, value_input_option='USER_ENTERED')
                except Exception as e_write:
                    log_callback(f"Wiersz {current_row_index}: Nie udało się również zapisać komunikatu o błędzie do arkusza: {e_write}")
        finally:
            log_callback(f"Zakończono przetwarzanie wiersza {current_row_index}. Oczekiwanie 1 sek...")
            time.sleep(1) 

    log_callback("\n--- Wszystkie wiersze przetworzone. Logika główna zakończona. ---")