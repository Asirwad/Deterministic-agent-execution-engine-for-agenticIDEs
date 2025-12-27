"""
SummarizeExecutor - Generates summaries via LLM.

Similar to AnalyzeExecutor but specialized for summarization tasks.
Useful for creating final summaries of what was accomplished.

Input:
    {
        "instruction": "Summarize the changes made",
        "context_keys": ["step-1", "step-2", "step-3"]  # Steps to summarize
    }

Output:
    {
        "summary": "The LLM-generated summary...",
        "model": "gemini-flash",
        "tokens": {"prompt": 300, "completion": 100}
    }
"""

import time
from typing import Optional

from src.db.models import StepType
from src.executors.base import BaseExecutor, StepResult
from src.services.smart_router import SmartRouterClient, SmartRouterError


class SummarizeExecutor(BaseExecutor):
    """
    Executor for generating summaries via LLM.
    
    This is similar to AnalyzeExecutor but with a summarization focus:
    - System prompt optimized for concise summaries
    - Designed for end-of-workflow summary generation
    """
    
    DEFAULT_SYSTEM_PROMPT = """You are a technical documentation expert.
Generate clear, concise summaries of the work that was completed.
Focus on what was done, what files were changed, and any important outcomes.
Use bullet points for clarity. Be specific but brief."""
    
    def __init__(self, router_client: SmartRouterClient):
        """
        Initialize the executor with a Smart Router client.
        
        Args:
            router_client: SmartRouterClient for LLM API calls
        """
        self.router = router_client
    
    @property
    def step_type(self) -> StepType:
        """This executor handles SUMMARIZE steps."""
        return StepType.SUMMARIZE
    
    @property
    def requires_approval(self) -> bool:
        """Summarization is read-only - no approval needed."""
        return False
    
    async def validate_input(self, input: dict) -> Optional[str]:
        """Validate that input contains an instruction."""
        if "instruction" not in input:
            return "Missing required field: 'instruction'"
        
        return None
    
    def _build_prompt(self, input: dict, context: dict) -> str:
        """Build the summarization prompt."""
        instruction = input["instruction"]
        context_keys = input.get("context_keys", [])
        
        prompt_parts = [f"## Task\n{instruction}\n"]
        
        # Add goal if present
        if "goal" in context:
            prompt_parts.insert(0, f"## Original Goal\n{context['goal']}\n")
        
        # Determine which steps to include
        if context_keys:
            keys_to_use = [k for k in context_keys if k in context]
        else:
            keys_to_use = [k for k in context.keys() if k.startswith("step-")]
        
        # Build context from steps
        prompt_parts.append("## Work Completed\n")
        
        for key in sorted(keys_to_use):
            step_data = context[key]
            step_type = step_data.get("type", "unknown")
            step_output = step_data.get("output", {})
            
            prompt_parts.append(f"### {key} ({step_type})")
            
            # Summarize output based on step type
            if step_type == "read_file":
                path = step_output.get("path", "unknown")
                lines = step_output.get("lines", 0)
                prompt_parts.append(f"Read file: {path} ({lines} lines)\n")
            
            elif step_type == "edit_file":
                path = step_output.get("path", "unknown")
                added = step_output.get("lines_added", 0)
                removed = step_output.get("lines_removed", 0)
                prompt_parts.append(f"Edited: {path} (+{added}/-{removed} lines)\n")
            
            elif step_type == "analyze":
                analysis = step_output.get("analysis", "")[:500]
                prompt_parts.append(f"Analysis: {analysis}...\n")
            
            elif step_type == "run_command":
                command = step_output.get("command", "unknown")
                exit_code = step_output.get("exit_code", -1)
                prompt_parts.append(f"Command: {command} (exit: {exit_code})\n")
            
            else:
                prompt_parts.append(f"{step_output}\n")
        
        return "\n".join(prompt_parts)
    
    async def execute(self, input: dict, context: dict) -> StepResult:
        """
        Generate a summary using the LLM.
        
        Args:
            input: {"instruction": "...", "context_keys": [...]}
            context: Previous step outputs
        
        Returns:
            StepResult with summary and cost metadata
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
        
        # Build prompt
        prompt = self._build_prompt(input, context)
        system_prompt = input.get("system_prompt", self.DEFAULT_SYSTEM_PROMPT)
        
        try:
            response = await self.router.complete(
                prompt=prompt,
                system_prompt=system_prompt,
            )
            
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            return StepResult(
                success=True,
                output={
                    "summary": response.content,
                    "model": response.model,
                    "tokens": {
                        "prompt": response.prompt_tokens,
                        "completion": response.completion_tokens,
                    },
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
                error=f"Unexpected error during summarization: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
