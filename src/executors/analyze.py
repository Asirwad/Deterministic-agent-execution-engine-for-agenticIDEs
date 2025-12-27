"""
AnalyzeExecutor - LLM-powered analysis via Smart Model Router.

This is the core LLM executor. It:
1. Builds a prompt from instruction + context from previous steps
2. Calls the Smart Model Router /v1/complete API
3. Returns the response with full cost metadata

Input:
    {
        "instruction": "Analyze this code for security vulnerabilities",
        "context_keys": ["step-1", "step-2"]  # Optional - which steps to include
    }

Output:
    {
        "analysis": "The LLM response text...",
        "model": "gemini-flash",
        "tokens": {"prompt": 150, "completion": 200}
    }
"""

import time
from typing import Optional

from src.db.models import StepType
from src.executors.base import BaseExecutor, StepResult
from src.services.smart_router import SmartRouterClient, SmartRouterError


class AnalyzeExecutor(BaseExecutor):
    """
    Executor for LLM-powered analysis.
    
    This executor:
    - Uses SmartRouterClient to call the LLM
    - Builds context from previous step outputs
    - Captures full cost metadata for tracking
    - Stores prompt and response for debugging
    
    The Smart Model Router handles:
    - Model selection based on prompt complexity
    - Cost optimization
    - Caching
    """
    
    # Default system prompt for analysis tasks
    DEFAULT_SYSTEM_PROMPT = """You are an expert software engineer and code analyst.
Analyze the provided code or information carefully and provide clear, actionable insights.
Be specific and reference line numbers or code sections when applicable."""
    
    def __init__(self, router_client: SmartRouterClient):
        """
        Initialize the executor with a Smart Router client.
        
        Args:
            router_client: SmartRouterClient for LLM API calls
        """
        self.router = router_client
    
    @property
    def step_type(self) -> StepType:
        """This executor handles ANALYZE steps."""
        return StepType.ANALYZE
    
    @property
    def requires_approval(self) -> bool:
        """Analysis is read-only - no approval needed."""
        return False
    
    async def validate_input(self, input: dict) -> Optional[str]:
        """
        Validate that input contains required 'instruction' field.
        """
        if "instruction" not in input:
            return "Missing required field: 'instruction'"
        
        if not isinstance(input["instruction"], str):
            return "'instruction' must be a string"
        
        if not input["instruction"].strip():
            return "'instruction' cannot be empty"
        
        return None
    
    def _build_prompt(self, input: dict, context: dict) -> str:
        """
        Build the LLM prompt from instruction and context.
        
        Args:
            input: Step input with instruction and optional context_keys
            context: Accumulated context from previous steps
        
        Returns:
            Complete prompt string for the LLM
        """
        instruction = input["instruction"]
        context_keys = input.get("context_keys", [])
        
        # Start with the instruction
        prompt_parts = [f"## Instruction\n{instruction}\n"]
        
        # Add context from specified steps (or all if none specified)
        if context_keys:
            # Use only specified keys
            keys_to_use = [k for k in context_keys if k in context]
        else:
            # Use all step context (step-1, step-2, etc.)
            keys_to_use = [k for k in context.keys() if k.startswith("step-")]
        
        # Add goal if present
        if "goal" in context:
            prompt_parts.insert(0, f"## Goal\n{context['goal']}\n")
        
        # Add context from previous steps
        for key in sorted(keys_to_use):
            step_data = context[key]
            step_type = step_data.get("type", "unknown")
            step_output = step_data.get("output", {})
            
            prompt_parts.append(f"## Context from {key} ({step_type})")
            
            # Format output based on step type
            if step_type == "read_file":
                file_path = step_output.get("path", "unknown")
                content = step_output.get("content", "")
                prompt_parts.append(f"File: {file_path}\n```\n{content}\n```\n")
            else:
                # Generic formatting for other step types
                prompt_parts.append(f"{step_output}\n")
        
        return "\n".join(prompt_parts)
    
    async def execute(self, input: dict, context: dict) -> StepResult:
        """
        Execute an LLM analysis.
        
        Args:
            input: {"instruction": "...", "context_keys": [...]}
            context: Previous step outputs
        
        Returns:
            StepResult with LLM response and cost metadata
        """
        start_time = time.perf_counter()
        
        # Validate input
        validation_error = await self.validate_input(input)
        if validation_error:
            return StepResult(
                success=False,
                error=validation_error,
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
        
        # Build the prompt
        prompt = self._build_prompt(input, context)
        system_prompt = input.get("system_prompt", self.DEFAULT_SYSTEM_PROMPT)
        
        try:
            # Call Smart Model Router
            response = await self.router.complete(
                prompt=prompt,
                system_prompt=system_prompt,
            )
            
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            return StepResult(
                success=True,
                output={
                    "analysis": response.content,
                    "model": response.model,
                    "tokens": {
                        "prompt": response.prompt_tokens,
                        "completion": response.completion_tokens,
                    },
                    "cached": response.cached,
                },
                cost_metadata={
                    "model": response.model,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "estimated_cost": response.estimated_cost,
                    "cached": response.cached,
                },
                latency_ms=latency_ms,
                prompt_sent=prompt,
                response_received=response.content,
            )
        
        except SmartRouterError as e:
            return StepResult(
                success=False,
                error=f"Smart Router error: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
                prompt_sent=prompt,
            )
        
        except Exception as e:
            return StepResult(
                success=False,
                error=f"Unexpected error during analysis: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
