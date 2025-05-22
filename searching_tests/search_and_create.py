import csv
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")

if not openai_api_key:
    raise ValueError("OPENAI_API_KEY not found in environment variables. Please set it in your .env file.")

client = OpenAI(api_key=openai_api_key)

def llm1_search_person_activity(company_name: str) -> str | None:
    print(f"\n--- LLM 1: Searching for activity of {company_name} ---")
    prompt = f"Tell me something about {company_name} and what this company shared in media recently connected to e-commerce or similar fields? Focus directly on company thoughts, insides and conclusions."
    try:
        response = client.responses.create(
            model="gpt-4o-mini",
            tools=[{"type": "web_search_preview", "search_context_size": "low"}],
            input=prompt
        )
        output_text = getattr(response, 'output_text', None)
        output_text = output_text.replace("\n", " ")
        if not output_text and hasattr(response, 'choices'):
            output_text = response.choices[0].message.content
        return output_text if output_text else None
    except Exception as e:
        print(f"Error in LLM 1 for {company_name}: {e}")
        return None

def llm2_write_article_intro(company_name: str, context_from_llm1: str) -> str | None:
    print(f"\n--- LLM 2: Writing intro for {company_name} ---")
    prompt_file_path = "../prompts/email_first_line_creator.txt"
    try:
        with open(prompt_file_path, "r", encoding="utf-8") as f:
            prompt_llm2 = f.read()
        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": prompt_llm2},
                {"role": "user", "content": f"Write me intrudoction to email for {company_name}. Here is what I know about this company: {context_from_llm1}"}
            ],
            max_tokens=100,
            temperature=0.5
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error in LLM 2 for {company_name}: {e}")
        return None

def run_search_write_llms(person_to_research: str) -> tuple:
    recent_activity_summary = llm1_search_person_activity(person_to_research)
    if recent_activity_summary:
        article_intro = llm2_write_article_intro(person_to_research, recent_activity_summary)
        if article_intro:
            return person_to_research, recent_activity_summary, article_intro
        else:
            return person_to_research, recent_activity_summary, "Failed to generate email"
    else:
        return person_to_research, "Not found", "Not found"

import os

def process_csv(input_csv_path: str, output_csv_path: str):
    with open(input_csv_path, "r", encoding="utf-8") as infile, \
         open(output_csv_path, "w", encoding="utf-8", newline="") as outfile:

        reader = csv.reader(infile)
        writer = csv.writer(outfile, delimiter=';')
        writer.writerow(["Input", "Recent Activity Summary", "Article Intro"])
        outfile.flush()  # Flushing header write
        os.fsync(outfile.fileno())

        for row in reader:
            if not row:
                continue
            person_to_research = row[0].strip()
            input_text, activity, intro = run_search_write_llms(person_to_research)
            writer.writerow([input_text, activity, intro])
            outfile.flush()
            os.fsync(outfile.fileno())  # Ensure data is written to disk
            print(f"\n--- DONE for {input_text} ---")

if __name__ == "__main__":
    input_csv = "input.csv"
    output_csv = "output.csv"
    process_csv(input_csv, output_csv)
