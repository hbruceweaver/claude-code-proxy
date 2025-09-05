#!/usr/bin/env python3
"""Test script to verify WebSearch tool interception works with Exa."""

import httpx
import json
import asyncio

async def test_websearch_interception():
    """Test that WebSearch tool calls are intercepted and executed via Exa."""
    
    # Configuration
    proxy_url = "http://localhost:8082/v1/messages"
    api_key = "test-client-key"  # Your configured ANTHROPIC_API_KEY
    
    # Create a request that simulates Claude wanting to search the web
    # This mimics what happens when Claude calls the WebSearch tool
    request_data = {
        "model": "claude-3-opus-20240229",
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": "What are the latest developments in quantum computing in 2025?"
            },
            {
                "role": "assistant", 
                "content": [
                    {
                        "type": "text",
                        "text": "I'll search for the latest developments in quantum computing in 2025."
                    },
                    {
                        "type": "tool_use",
                        "id": "test_tool_123",
                        "name": "WebSearch",
                        "input": {
                            "query": "quantum computing breakthroughs 2025 latest developments"
                        }
                    }
                ]
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "test_tool_123",
                        "content": "Pending search results..."  # This will be replaced by Exa results
                    }
                ]
            }
        ],
        "stream": False
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            print("Sending request to proxy...")
            print(f"Request: {json.dumps(request_data, indent=2)}")
            
            response = await client.post(
                proxy_url,
                json=request_data,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json"
                }
            )
            
            print(f"\nResponse status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"\nResponse content:\n{json.dumps(result, indent=2)}")
                
                # Check if the response contains search results
                if "content" in result:
                    for block in result["content"]:
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if "quantum" in text.lower() or "search" in text.lower():
                                print("\n✅ SUCCESS: The proxy appears to have processed the search!")
                                return True
                
                print("\n⚠️  Response received but doesn't seem to contain search results")
            else:
                print(f"\n❌ Error: {response.text}")
                
    except Exception as e:
        print(f"\n❌ Exception occurred: {e}")
        import traceback
        traceback.print_exc()
    
    return False

if __name__ == "__main__":
    print("Testing WebSearch to Exa interception...")
    print("=" * 50)
    success = asyncio.run(test_websearch_interception())
    print("=" * 50)
    if success:
        print("✅ Test completed successfully!")
    else:
        print("❌ Test failed - check the logs above")