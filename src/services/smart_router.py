"""
SmartRouterClient - HTTP client for the Smart Model Router API.

This service encapsulates all communication with the Smart Model Router,
providing a clean interface for executors to use LLM capabilities.

The Smart Model Router handles:
- Model selection based on prompt complexity
- Cost tracking and optimization
- Caching (exact and semantic)
- Retry and fallback logic

This client just needs to call /v1/complete and handle the response.
"""

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from src.config import get_settings


@dataclass
class LLMResponse:
    """
    Response from an LLM completion request.
    
    This is our internal representation, parsed from the Smart Model Router's
    CompletionResponse schema.
    
    Attributes:
        content: The generated text response
        model: Which model was used (e.g., "gemini-flash", "ollama/qwen")
        prompt_tokens: Number of tokens in the prompt
        completion_tokens: Number of tokens in the response
        estimated_cost: Cost in USD for this request
        cached: Whether this was a cache hit
        latency_ms: Round-trip time for the request
    """
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: float
    cached: bool = False
    latency_ms: int = 0


class SmartRouterError(Exception):
    """Raised when Smart Model Router returns an error."""
    pass


class SmartRouterClient:
    """
    HTTP client for the Smart Model Router API.
    
    Usage:
        client = SmartRouterClient()
        response = await client.complete("Explain this code: ...")
        print(response.content)
        print(f"Cost: ${response.estimated_cost}")
    
    The client:
    - Uses httpx.AsyncClient for non-blocking HTTP
    - Adds X-API-Key header for authentication
    - Parses response into LLMResponse dataclass
    - Tracks latency for each request
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
    ):
        """
        Initialize the Smart Router client.
        
        Args:
            base_url: Smart Router URL (defaults to settings.smart_router_url)
            api_key: API key for auth (defaults to settings.smart_router_api_key)
            timeout: Request timeout in seconds (default 60s for slow models)
        """
        settings = get_settings()
        
        self.base_url = (base_url or settings.smart_router_url).rstrip("/")
        self.api_key = api_key or settings.smart_router_api_key
        self.timeout = timeout
        
        # Create reusable HTTP client
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["X-API-Key"] = self.api_key
            
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(self.timeout),
            )
        
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """
        Send a completion request to the Smart Model Router.
        
        Args:
            prompt: The user prompt to send
            system_prompt: Optional system prompt for context
        
        Returns:
            LLMResponse with content, model info, and cost
        
        Raises:
            SmartRouterError: If the request fails
        
        Example:
            response = await client.complete(
                prompt="Analyze this code for bugs: ...",
                system_prompt="You are an expert code reviewer."
            )
        """
        client = await self._get_client()
        
        # Build request payload
        # This matches the Smart Model Router's CompletionRequest schema
        payload = {
            "prompt": prompt,
        }
        if system_prompt:
            payload["system_prompt"] = system_prompt
        
        start_time = time.perf_counter()
        
        try:
            response = await client.post("/v1/complete", json=payload)
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            if response.status_code != 200:
                error_detail = response.text
                raise SmartRouterError(
                    f"Smart Router returned {response.status_code}: {error_detail}"
                )
            
            data = response.json()
            
            return LLMResponse(
                content=data.get("content", ""),
                model=data.get("model", "unknown"),
                prompt_tokens=data.get("prompt_tokens", 0),
                completion_tokens=data.get("completion_tokens", 0),
                estimated_cost=data.get("estimated_cost", 0.0),
                cached=data.get("cached", False),
                latency_ms=latency_ms,
            )
        
        except httpx.TimeoutException:
            raise SmartRouterError(
                f"Request timed out after {self.timeout}s"
            )
        
        except httpx.RequestError as e:
            raise SmartRouterError(
                f"Failed to connect to Smart Router at {self.base_url}: {str(e)}"
            )
    
    async def health_check(self) -> dict:
        """
        Check if the Smart Model Router is healthy.
        
        Returns:
            Health status dict from /health endpoint
        
        Raises:
            SmartRouterError: If health check fails
        """
        client = await self._get_client()
        
        try:
            response = await client.get("/health")
            
            if response.status_code != 200:
                raise SmartRouterError(
                    f"Health check failed with status {response.status_code}"
                )
            
            return response.json()
        
        except httpx.RequestError as e:
            raise SmartRouterError(
                f"Cannot reach Smart Router: {str(e)}"
            )
    
    def __repr__(self) -> str:
        return f"<SmartRouterClient base_url='{self.base_url}'>"
