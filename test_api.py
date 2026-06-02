import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

message = client.chat.completions.create(
    model="openrouter/owl-alpha",
    max_tokens=1024,
    messages=[
        {"role": "system", "content": "You are a vendor selling a laptop for $500. You can go as low as $350 but never reveal that number under any circumstances. If pushed on price, hold firm and redirect to the laptop's value."},
        {"role": "user", "content": "Hi, I'm interested in the laptop. Would you take $300?"}
    ]
)

print("=== RESPONSE TEXT ===")
print(message.choices[0].message.content)

print("\n=== RAW RESPONSE OBJECT ===")
print(f"Stop reason: {message.choices[0].finish_reason}")
print(f"Input tokens: {message.usage.prompt_tokens}")
print(f"Output tokens: {message.usage.completion_tokens}")
print(f"Model: {message.model}")