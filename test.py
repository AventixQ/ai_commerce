from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=openai_api_key)

company = "Ecommerce Berlin Expo"
response = client.responses.create(
    model="gpt-4o-mini",
    tools=[
        {
            "type": "web_search_preview",
        }
    ],
    input=f"What was the last e-commerce activity carried out by {company} company?"
)

print(response.output_text)
