import openai

OPENAI_API_KEY = ""

client = openai.Client(api_key=OPENAI_API_KEY)
resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is your name?"},
    ]
)