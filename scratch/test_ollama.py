import sys
import os

# Add src to path
sys.path.append(os.getcwd())

from src.infrastructure.ollama_adapter import OllamaAdapter
import logging

logging.basicConfig(level=logging.INFO)

def test_ollama_connection():
    print("--- Testing Ollama Connection ---")
    adapter = OllamaAdapter(base_url="http://localhost:11434", default_model="gemma4:e4b")
    
    try:
        # 1. Simple text test
        print("Testing simple text inference...")
        response = adapter.generate_content(
            model="gemma4:e4b",
            contents=["你好，请用一句话自我介绍。"],
            config={"temperature": 0.7}
        )
        text = response.candidates[0].content.parts[0].text
        print(f"Response: {text}")
        
        # 2. Tool call mock test
        print("\nTesting tool call format mapping...")
        # We don't actually need to execute the tool, just see if the adapter handles the 'tools' param without crashing
        # and if it can (theoretically) parse a tool call if the model returns one.
        response = adapter.generate_content(
            model="gemma4:e4b",
            contents=["What is the price of BTC?"],
            config={
                "temperature": 0.1,
                "tools": [{
                    'type': 'function',
                    'function': {
                        'name': 'get_crypto_price',
                        'description': 'Get price',
                        'parameters': {'type': 'object', 'properties': {'symbol': {'type': 'string'}}}
                    }
                }]
            }
        )
        print("Tool call test completed (no crash).")
        
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    test_ollama_connection()
