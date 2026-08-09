import time
import requests

# Pointing to your local LLM Gateway
GATEWAY_URL = "http://localhost:8000/v1/chat/completions"

HEADERS = {
    "Authorization": "Bearer my_secure_local_password",
    "Content-Type": "application/json"
}

# We use temperature 0.0 to ensure the LLM gives a deterministic answer, 
# which is perfect for triggering the cache!
PAYLOAD = {
    "model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    "messages": [
        {"role": "system", "content": "You are a helpful AI assistant."},
        {"role": "user", "content": "Write a 3-line haiku about writing software tests."}
    ],
    "temperature": 0.0,
    "max_tokens": 50
}

def test_caching():
    print("🚀 Sending Request 1 (Routing to Groq - Expect ~1000ms+)")
    start_time = time.time()
    response1 = requests.post(GATEWAY_URL, headers=HEADERS, json=PAYLOAD)
    duration1 = (time.time() - start_time) * 1000
    
    if response1.status_code == 200:
        print(f"✅ Success! Time: {duration1:.0f} ms")
        print(f"🤖 AI Answer:\n{response1.json()['choices'][0]['message']['content'].strip()}\n")
    else:
        print(f"❌ Failed: {response1.text}")
        return

    print("⚡ Sending Request 2 (Exact same prompt - Expect ~50ms Cache Hit)")
    start_time = time.time()
    response2 = requests.post(GATEWAY_URL, headers=HEADERS, json=PAYLOAD)
    duration2 = (time.time() - start_time) * 1000
    
    if response2.status_code == 200:
        print(f"✅ Success! Time: {duration2:.0f} ms")
        print(f"🤖 AI Answer:\n{response2.json()['choices'][0]['message']['content'].strip()}\n")
    
    print(f"🎉 The gateway made the second request {duration1 / duration2:.1f}x faster!")

if __name__ == "__main__":
    test_caching()