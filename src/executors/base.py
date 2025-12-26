"""
Base executor classes for the Deterministic Agent Execution Engine.

This module defines:
1. StepResult - The standardized output from any executor
2. BaseExecutor - Abstract class all step executors must inherit from

Design Principles:
- Every executor returns a StepResult (consistent interface)
- Executors are stateless (all state is in the Step object)
- Executors declare if they need human approval
- Cost metadata is captured for LLM-based executors
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.db.models import StepType


@dataclass
class StepResult:
    """
    The result of executing a step.
    
    Every executor returns this, providing a consistent interface
    for the execution engine to process results.
    
    Attributes:
        success: Whether the step completed successfully
        output: The output data (flexible - depends on step type)
        error: Error message if success=False
        cost_metadata: LLM cost info (for analyze/summarize steps)
        latency_ms: How long the step took to execute
        prompt_sent: Exact prompt sent to LLM (for debugging)
        response_received: Exact response from LLM (for debugging)
    
    Examples:
        # Successful read_file
        StepResult(success=True, output={"content": "file contents..."})
        
        # Failed read_file
        StepResult(success=False, error="File not found: config.py")
        
        # Successful analyze (LLM step)
        StepResult(
            success=True,
            output={"analysis": "The code has 3 issues..."},
            cost_metadata={
                "model": "gemini-flash",
                "prompt_tokens": 150,
                "completion_tokens": 200,
                "estimated_cost": 0.00015,
            },
            prompt_sent="Analyze this code...",
            response_received="The code has 3 issues..."
        )
    """
    success: bool
    output: Any = None
    error: Optional[str] = None
    cost_metadata: Optional[dict] = None
    latency_ms: int = 0
    prompt_sent: Optional[str] = None
    response_received: Optional[str] = None
    
    # Timestamp when step completed (set automatically)
    completed_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate the result state."""
        if not self.success and not self.error:
            raise ValueError("Failed steps must have an error message")


class BaseExecutor(ABC):
    """
    Abstract base class for all step executors.
    
    To create a new executor:
    1. Inherit from BaseExecutor
    2. Implement step_type property
    3. Implement execute() method
    4. Optionally override requires_approval property
    
    Example:
        class ReadFileExecutor(BaseExecutor):
            @property
            def step_type(self) -> StepType:
                return StepType.READ_FILE
            
            async def execute(self, input: dict, context: dict) -> StepResult:
                path = input["path"]
                content = await self.read_file(path)
                return StepResult(success=True, output={"content": content})
    """
    
    @property
    @abstractmethod
    def step_type(self) -> StepType:
        """
        The type of step this executor handles.
        
        Must return one of the StepType enum values.
        Used by the execution engine to route steps to the correct executor.
        """
        pass
    
    @property
    def requires_approval(self) -> bool:
        """
        Whether this executor's steps require human approval before execution.
        
        Default is False. Override to return True for dangerous operations
        like edit_file and run_command.
        
        When True:
        - Step status goes to AWAITING_APPROVAL instead of RUNNING
        - User must call /approve endpoint before execution continues
        """
        return False
    
    @abstractmethod
    async def execute(self, input: dict, context: dict) -> StepResult:
        """
        Execute the step with the given input.
        
        Args:
            input: Step-specific input parameters (from Step.input)
            context: Accumulated context from previous steps
                     Format: {
                         "goal": "original goal",
                         "step-1": {"type": "read_file", "output": {...}},
                         "step-2": {"type": "analyze", "output": {...}},
                         ...
                     }
        
        Returns:
            StepResult with success/failure status and output/error
        
        Raises:
            Should NOT raise exceptions - catch and return StepResult with error
        """
        pass
    
    async def validate_input(self, input: dict) -> Optional[str]:
        """
        Validate the input before execution.
        
        Override this to add input validation for your executor.
        
        Args:
            input: The step input to validate
        
        Returns:
            None if valid, error message string if invalid
        """
        return None
