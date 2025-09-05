from fastapi import APIRouter, HTTPException, Request, Header, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from datetime import datetime
import uuid
import json
from typing import Optional

from src.core.config import config
from src.core.logging import logger
from src.core.client import OpenAIClient
from src.models.claude import ClaudeMessagesRequest, ClaudeTokenCountRequest
from src.conversion.request_converter import convert_claude_to_openai
from src.conversion.response_converter import (
    convert_openai_to_claude_response,
    convert_openai_streaming_to_claude_with_cancellation,
)
from src.core.model_manager import model_manager
from src.utils.exa_search import process_websearch_via_exa

router = APIRouter()

openai_client = OpenAIClient(
    config.openai_api_key,
    config.openai_base_url,
    config.request_timeout,
    api_version=config.azure_api_version,
)

async def validate_api_key(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    """Validate the client's API key from either x-api-key header or Authorization header."""
    client_api_key = None
    
    # Extract API key from headers
    if x_api_key:
        client_api_key = x_api_key
    elif authorization and authorization.startswith("Bearer "):
        client_api_key = authorization.replace("Bearer ", "")
    
    # Skip validation if ANTHROPIC_API_KEY is not set in the environment
    if not config.anthropic_api_key:
        return
        
    # Validate the client API key
    if not client_api_key or not config.validate_client_api_key(client_api_key):
        logger.warning(f"Invalid API key provided by client")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key. Please provide a valid Anthropic API key."
        )

async def intercept_websearch_in_request(request: ClaudeMessagesRequest, logger) -> ClaudeMessagesRequest:
    """
    Check if the request contains WebSearch tool results that haven't been executed yet.
    If the previous message was a tool_use for WebSearch, execute it via Exa and inject results.
    """
    logger.info(f"Checking for WebSearch interception, message count: {len(request.messages)}")
    
    # Check if there are messages with tool_use for WebSearch waiting for results
    if len(request.messages) >= 2:
        # Check the last assistant message for WebSearch tool_use
        second_last = request.messages[-2]
        last = request.messages[-1]
        
        logger.info(f"Second last role: {second_last.role}, Last role: {last.role}")
        logger.info(f"Second last content type: {type(second_last.content)}, Last content type: {type(last.content)}")
        
        if (second_last.role == "assistant" and 
            last.role == "user" and 
            isinstance(second_last.content, list) and
            isinstance(last.content, list)):
            
            # Check if assistant message has WebSearch tool_use
            for assistant_block in second_last.content:
                logger.info(f"Assistant block type: {getattr(assistant_block, 'type', 'no type')}, name: {getattr(assistant_block, 'name', 'no name')}")
                if (hasattr(assistant_block, 'type') and 
                    assistant_block.type == "tool_use" and 
                    assistant_block.name == "WebSearch"):
                    
                    # Check if user message has corresponding tool_result placeholder
                    for user_block in last.content:
                        if (hasattr(user_block, 'type') and 
                            user_block.type == "tool_result" and
                            user_block.tool_use_id == assistant_block.id):
                            
                            # Check if the content contains an error or is a placeholder
                            current_content = getattr(user_block, 'content', '')
                            if isinstance(current_content, str):
                                # If it contains an API error or is a failed search, replace it
                                if 'API Error' in current_content or 'Did 0 searches' in current_content or 'Web search results' in current_content:
                                    logger.info(f"Intercepting WebSearch execution with input: {assistant_block.input}")
                                    
                                    try:
                                        # Execute the search via Exa
                                        search_results = await process_websearch_via_exa(assistant_block.input)
                                        
                                        # Format results as JSON string for the tool result
                                        user_block.content = json.dumps(search_results, ensure_ascii=False)
                                        logger.info(f"Injected Exa search results into tool_result")
                                        
                                    except Exception as e:
                                        logger.error(f"Error executing WebSearch via Exa: {e}")
                                        # Inject error message if search fails
                                        user_block.content = json.dumps({
                                            "error": f"Search failed: {str(e)}",
                                            "results": []
                                        })
    
    return request

@router.post("/v1/messages")
async def create_message(request: ClaudeMessagesRequest, http_request: Request, _: None = Depends(validate_api_key)):
    try:
        logger.info(
            f"Processing Claude request: model={request.model}, stream={request.stream}"
        )
        
        # Debug: Log the full incoming Claude request
        logger.info(f"=== INCOMING CLAUDE REQUEST ===\n{request.model_dump_json(indent=2)}")
        
        # Intercept WebSearch tool results and execute via Exa if needed
        request = await intercept_websearch_in_request(request, logger)

        # Generate unique request ID for cancellation tracking
        request_id = str(uuid.uuid4())

        # Convert Claude request to OpenAI format
        openai_request = convert_claude_to_openai(request, model_manager)
        
        # Debug: Log the converted OpenAI request
        logger.info(f"=== CONVERTED OPENAI REQUEST ===\n{json.dumps(openai_request, indent=2)}")

        # Check if client disconnected before processing
        if await http_request.is_disconnected():
            raise HTTPException(status_code=499, detail="Client disconnected")

        if request.stream:
            # Streaming response - wrap in error handling
            try:
                openai_stream = openai_client.create_chat_completion_stream(
                    openai_request, request_id
                )
                return StreamingResponse(
                    convert_openai_streaming_to_claude_with_cancellation(
                        openai_stream,
                        request,
                        logger,
                        http_request,
                        openai_client,
                        request_id,
                    ),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Headers": "*",
                    },
                )
            except HTTPException as e:
                # Convert to proper error response for streaming
                logger.error(f"Streaming error: {e.detail}")
                import traceback

                logger.error(traceback.format_exc())
                error_message = openai_client.classify_openai_error(e.detail)
                error_response = {
                    "type": "error",
                    "error": {"type": "api_error", "message": error_message},
                }
                return JSONResponse(status_code=e.status_code, content=error_response)
        else:
            # Non-streaming response
            openai_response = await openai_client.create_chat_completion(
                openai_request, request_id
            )
            
            # Debug: Log the converted OpenAI response before Claude conversion
            logger.info(f"=== OPENAI RESPONSE BEFORE CONVERSION ===\n{json.dumps(openai_response, indent=2)}")
            
            claude_response = convert_openai_to_claude_response(
                openai_response, request
            )
            
            # Debug: Log the final Claude response
            logger.info(f"=== FINAL CLAUDE RESPONSE ===\n{json.dumps(claude_response, indent=2)}")
            
            return claude_response
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        logger.error(f"Unexpected error processing request: {e}")
        logger.error(traceback.format_exc())
        error_message = openai_client.classify_openai_error(str(e))
        raise HTTPException(status_code=500, detail=error_message)


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: ClaudeTokenCountRequest, _: None = Depends(validate_api_key)):
    try:
        # For token counting, we'll use a simple estimation
        # In a real implementation, you might want to use tiktoken or similar

        total_chars = 0

        # Count system message characters
        if request.system:
            if isinstance(request.system, str):
                total_chars += len(request.system)
            elif isinstance(request.system, list):
                for block in request.system:
                    if hasattr(block, "text"):
                        total_chars += len(block.text)

        # Count message characters
        for msg in request.messages:
            if msg.content is None:
                continue
            elif isinstance(msg.content, str):
                total_chars += len(msg.content)
            elif isinstance(msg.content, list):
                for block in msg.content:
                    if hasattr(block, "text") and block.text is not None:
                        total_chars += len(block.text)

        # Rough estimation: 4 characters per token
        estimated_tokens = max(1, total_chars // 4)

        return {"input_tokens": estimated_tokens}

    except Exception as e:
        logger.error(f"Error counting tokens: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "openai_api_configured": bool(config.openai_api_key),
        "api_key_valid": config.validate_api_key(),
        "client_api_key_validation": bool(config.anthropic_api_key),
    }


@router.get("/test-connection")
async def test_connection():
    """Test API connectivity to OpenAI"""
    try:
        # Simple test request to verify API connectivity
        test_response = await openai_client.create_chat_completion(
            {
                "model": config.small_model,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 5,
            }
        )

        return {
            "status": "success",
            "message": "Successfully connected to OpenAI API",
            "model_used": config.small_model,
            "timestamp": datetime.now().isoformat(),
            "response_id": test_response.get("id", "unknown"),
        }

    except Exception as e:
        logger.error(f"API connectivity test failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "failed",
                "error_type": "API Error",
                "message": str(e),
                "timestamp": datetime.now().isoformat(),
                "suggestions": [
                    "Check your GROQ_API_KEY_KIMI (or OPENAI_API_KEY) is valid",
                    "Verify your API key has the necessary permissions",
                    "Check if you have reached rate limits",
                ],
            },
        )


@router.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Claude-to-OpenAI API Proxy v1.0.0",
        "status": "running",
        "config": {
            "openai_base_url": config.openai_base_url,
            "max_tokens_limit": config.max_tokens_limit,
            "api_key_configured": bool(config.openai_api_key),
            "client_api_key_validation": bool(config.anthropic_api_key),
            "big_model": config.big_model,
            "small_model": config.small_model,
        },
        "endpoints": {
            "messages": "/v1/messages",
            "count_tokens": "/v1/messages/count_tokens",
            "health": "/health",
            "test_connection": "/test-connection",
        },
    }
