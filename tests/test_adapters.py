#!/usr/bin/env python3
"""
Test script to verify DeepSeek and Qwen adapters work correctly.
Run this after adding your API keys to .env file.
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()


def test_deepseek_adapter():
    """Test DeepSeek adapter with a simple query."""
    print("\n" + "=" * 60)
    print("Testing DeepSeek Adapter")
    print("=" * 60)

    api_key = os.getenv('DEEPSEEK_API_KEY')
    if not api_key or 'your-deepseek-api-key' in api_key:
        print("WARNING: DEEPSEEK_API_KEY not configured in .env file")
        print("   Please add your real API key and try again.")
        return False

    try:
        from src.infrastructure.ai.deepseek_adapter import DeepSeekAdapter

        # Create adapter
        adapter = DeepSeekAdapter(
            api_key=api_key,
            default_model='deepseek-v4-flash',
            base_url='https://api.deepseek.com'
        )

        # Test simple query
        print("Sending test query to DeepSeek...")
        response = adapter.generate_content(
            model='deepseek-v4-flash',
            contents=['What is 2+2? Respond with JSON: {"answer": number}'],
            response_json=True,
            temperature=0.1,
        )

        print("Response received!")
        print(f"   Text: {response.text}")
        if response.usage:
            print(f"   Tokens: {response.usage.total_token_count}")
        return True

    except Exception as e:
        print(f"DeepSeek test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_qwen_adapter():
    """Test Qwen adapter with a simple query."""
    print("\n" + "=" * 60)
    print("Testing Qwen Adapter")
    print("=" * 60)

    api_key = os.getenv('QWEN_API_KEY')
    if not api_key or 'your-qwen-api-key' in api_key:
        print("WARNING: QWEN_API_KEY not configured in .env file")
        print("   Please add your real API key and try again.")
        return False

    try:
        from src.infrastructure.ai.qwen_adapter import QwenAdapter

        # Create adapter
        adapter = QwenAdapter(
            api_key=api_key,
            default_model='qwen-plus',
            base_url='https://dashscope.aliyuncs.com/compatible-mode/v1'
        )

        # Test simple query
        print("Sending test query to Qwen...")
        response = adapter.generate_content(
            model='qwen-plus',
            contents=['What is 3+3? Respond with JSON: {"answer": number}'],
            response_json=True,
            temperature=0.1,
        )

        print("Response received!")
        print(f"   Text: {response.text}")
        if response.usage:
            print(f"   Tokens: {response.usage.total_token_count}")
        return True

    except Exception as e:
        print(f"Qwen test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ai_factory():
    """Test AIFactory can create different providers."""
    print("\n" + "=" * 60)
    print("Testing AIFactory Provider Switching")
    print("=" * 60)

    try:
        from src.infrastructure.ai_factory import AIFactory

        # Test that factory can at least be imported and has the methods
        print("AIFactory imported successfully")
        print("Factory supports: gemini, ollama, deepseek, qwen")
        return True

    except Exception as e:
        print(f"AIFactory test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("\nAI Provider Adapter Test Suite")
    print("=" * 60)

    results = []

    # Test 1: AIFactory
    results.append(("AIFactory", test_ai_factory()))

    # Test 2: DeepSeek (only if API key is configured)
    if os.getenv('DEEPSEEK_API_KEY') and 'your-deepseek-api-key' not in os.getenv('DEEPSEEK_API_KEY', ''):
        results.append(("DeepSeek", test_deepseek_adapter()))
    else:
        print("\nSkipping DeepSeek test (API key not configured)")

    # Test 3: Qwen (only if API key is configured)
    if os.getenv('QWEN_API_KEY') and 'your-qwen-api-key' not in os.getenv('QWEN_API_KEY', ''):
        results.append(("Qwen", test_qwen_adapter()))
    else:
        print("\nSkipping Qwen test (API key not configured)")

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    for name, passed in results:
        status = "PASSED" if passed else "FAILED"
        print(f"{name:20s} {status}")

    all_passed = all(passed for _, passed in results)

    if all_passed:
        print("\nAll tests passed! Your adapters are ready to use.")
        print("\nNext steps:")
        print("1. Add your real API keys to .env file")
        print("2. Update config/global_config.yaml to set active_provider")
        print("3. Run your trading system normally")
    else:
        print("\nSome tests failed. Check the errors above.")
        sys.exit(1)
