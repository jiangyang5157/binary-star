from google import genai
import os
import sys

def run_diagnostic():
    """
    NEW SDK VERSION: Lists available models using the modern 'google-genai' library.
    """
    # 1. Loading API Key
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        # Fallback to .env in root
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if line.startswith("GOOGLE_API_KEY=") or line.startswith("GEMINI_API_KEY="):
                        api_key = line.split("=")[1].strip().strip('"').strip("'")
                        break

    if not api_key:
        print("\n[!] ERROR: API Key (GEMINI_API_KEY) not found.")
        return

    print(f"\n{'='*65}")
    print(f" GEMINI API DIAGNOSTIC (MODERN SDK) - PROJECT: SINGULARITY")
    print(f"{'='*65}\n")

    # 2. Initialize Client
    client = genai.Client(api_key=api_key)
    
    print(f"{'Model Name':<45} | {'Capabilities':<15}")
    print(f"{'-'*45}-|-{'-'*15}")
    
    try:
        # Client-based model listing
        for m in client.models.list():
            # Filter for content generation models
            # In the new SDK, we check supported_actions/methods via the model object
            name = m.name
            
            # Simple check for general applicability
            is_gen = "generateContent" in (getattr(m, 'supported_actions', []) or [])
            
            if is_gen:
                print(f"{name:<45} | ✅ GENERATE")
            else:
                print(f"{name:<45} | 🔒 RESTRICTED")
                
    except Exception as e:
        print(f"\n[!] API CONNECTION FAILED: {str(e)}")

    print(f"\n{'='*65}")
    print("TIP: If you don't care about spending: 'gemini-flash-latest, gemini-pro-latest'")
    print(f"{'='*65}\n")

if __name__ == "__main__":
    run_diagnostic()
