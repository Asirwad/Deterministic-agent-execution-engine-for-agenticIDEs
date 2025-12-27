"""
Pydantic schemas for API requests and responses.

These schemas define the data contract for the REST API.
They handle validation, serialization, and documentation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ===================
# Request Schemas
# ===================

class CreateRunRequest(BaseModel):
    """Request to create a new agent run."""
    goal: str = Field(
        ...,
        description="The goal for the agent to accomplish",
        min_length=1,
        max_length=10000,
        examples=["Refactor the UserService class for better testability"],
    )
    workspace_path: Optional[str] = Field(
        default=None,
        description="Custom workspace path (uses default if not provided)",
    )


class CreateStepRequest(BaseModel):
    """Request to add a step to a run."""
    step_type: str = Field(
        ...,
        description="Type of step: read_file, analyze, edit_file, run_command, summarize",
        examples=["read_file"],
    )
    input: dict = Field(
        ...,
        description="Step-specific input parameters",
        examples=[{"path": "src/main.py"}],
    )


# ===================
# Response Schemas
# ===================

class StepResponse(BaseModel):
    """Response schema for a single step."""
    id: UUID
    step_number: int
    step_type: str
    status: str
    input: dict
    output: Optional[dict] = None
    error: Optional[str] = None
    cost_metadata: Optional[dict] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class RunResponse(BaseModel):
    """Response schema for an agent run."""
    id: UUID
    goal: str
    status: str
    workspace_path: str
    plan: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    steps: list[StepResponse] = []
    
    class Config:
        from_attributes = True


class RunSummaryResponse(BaseModel):
    """Lightweight response for listing runs."""
    id: UUID
    goal: str
    status: str
    step_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class ExecuteStepResponse(BaseModel):
    """Response from executing a step."""
    success: bool
    run_id: UUID
    step_number: Optional[int] = None
    step_type: Optional[str] = None
    status: str = Field(
        ...,
        description="Current status: completed, failed, awaiting_approval, all_complete"
    )
    output: Optional[Any] = None
    error: Optional[str] = None
    cost: Optional[dict] = None


class CostResponse(BaseModel):
    """Response schema for cost breakdown."""
    run_id: UUID
    total_cost: float = Field(..., description="Total cost in USD")
    total_tokens: dict = Field(
        ...,
        description="Total tokens used",
        examples=[{"prompt": 1500, "completion": 800}],
    )
    steps: list[dict] = Field(
        default=[],
        description="Cost breakdown per step",
    )


class ApprovalResponse(BaseModel):
    """Response after approving a step."""
    success: bool
    run_id: UUID
    step_id: UUID
    message: str


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: Optional[str] = None
