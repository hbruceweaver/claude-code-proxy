import os
import json
import logging
from typing import Dict, Any, List, Optional
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)

class ExaSearchAdapter:
    """Adapter to convert WebSearch tool calls to Exa API calls and format responses."""
    
    def __init__(self):
        self.api_key = os.environ.get("EXA_API_KEY", "")
        self.base_url = "https://api.exa.ai"
        
    async def search(self, websearch_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert WebSearch input to Exa API format, execute search, and format response.
        
        Args:
            websearch_input: Dict with keys:
                - query (str): The search query
                - allowed_domains (List[str], optional): Domains to include
                - blocked_domains (List[str], optional): Domains to exclude
        
        Returns:
            Dict formatted like Exa API response
        """
        if not self.api_key:
            logger.error("EXA_API_KEY not set in environment variables")
            return self._create_error_response("EXA_API_KEY not configured")
        
        try:
            # Map WebSearch parameters to Exa API parameters
            exa_params = self._map_websearch_to_exa(websearch_input)
            
            # Make request to Exa API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/search",
                    headers={
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json"
                    },
                    json=exa_params,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    logger.error(f"Exa API error: {response.status_code} - {response.text}")
                    return self._create_error_response(f"Exa API error: {response.status_code}")
                
                # Return the raw Exa response
                # The format already matches what Claude expects
                return response.json()
                
        except Exception as e:
            logger.error(f"Error calling Exa API: {str(e)}")
            return self._create_error_response(str(e))
    
    def _map_websearch_to_exa(self, websearch_input: Dict[str, Any]) -> Dict[str, Any]:
        """Map WebSearch parameters to Exa API format."""
        exa_params = {
            "query": websearch_input.get("query", ""),
            "type": "auto",  # Let Exa decide between keyword and neural search
            "numResults": 10,
            "contents": {
                "text": {
                    "maxCharacters": 2000
                },
                "highlights": {
                    "numSentences": 2
                },
                "summary": {
                    "query": websearch_input.get("query", "")
                }
            }
        }
        
        # Handle domain filtering
        allowed_domains = websearch_input.get("allowed_domains", [])
        if allowed_domains:
            exa_params["includeDomains"] = allowed_domains
            
        blocked_domains = websearch_input.get("blocked_domains", [])
        if blocked_domains:
            exa_params["excludeDomains"] = blocked_domains
        
        # Add date range for recent results
        # You can make this configurable if needed
        exa_params["startCrawlDate"] = "2024-01-01"
        
        return exa_params
    
    def _create_error_response(self, error_message: str) -> Dict[str, Any]:
        """Create an error response in Exa format."""
        return {
            "requestId": "error",
            "resolvedSearchType": "error",
            "results": [],
            "searchType": "error",
            "context": f"Error: {error_message}",
            "costDollars": {
                "total": 0,
                "breakDown": [],
                "perRequestPrices": {},
                "perPagePrices": {}
            }
        }

# Singleton instance
exa_adapter = ExaSearchAdapter()

async def process_websearch_via_exa(tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a WebSearch tool call through the Exa API.
    
    This is the main entry point for intercepting WebSearch calls.
    """
    return await exa_adapter.search(tool_input)