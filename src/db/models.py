"""
SQLAlchemy ORM Models for Deterministic Agent Execution Engine.

This is the CORE of our domain model. These models represent:
- AgentRun: A complete execution lifecycle for a goal
- Step: Individual actions within a run

Key Design Decisions:
1. Explicit Enums for status - prevents typos, enables IDE autocomplete
2. JSONB for flexible data - each step type has different input/output
3. Immutable goal, mutable state - goal never changes after creation
4. step_number for ordering - deterministic execution order
"""

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ===================
# Base Class
# ===================

class Base(DeclarativeBase):
    """
    Base class for all ORM models.
    
    Using DeclarativeBase (SQLAlchemy 2.0 style) for:
    - Better type hints
    - IDE autocomplete support
    - Modern Python patterns
    """
    pass


# ===================
# Status Enums
# ===================

class RunStatus(str, enum.Enum):
    """
    Status of an AgentRun.
    
    State machine transitions:
    CREATED → PLANNING → PLANNED → RUNNING → COMPLETED
                                         ↘ FAILED
                                    ↗ PAUSED
                           AWAITING_APPROVAL ↔ RUNNING
    """
    CREATED = "created"                    # Goal received, plan not generated
    PLANNING = "planning"                  # Generating plan via LLM
    PLANNED = "planned"                    # Plan ready, execution not started
    RUNNING = "running"                    # Actively executing steps
    PAUSED = "paused"                      # Manually paused by user
    AWAITING_APPROVAL = "awaiting_approval"  # Step needs human approval
    COMPLETED = "completed"                # All steps finished successfully
    FAILED = "failed"                      # Step failed, execution stopped


class StepStatus(str, enum.Enum):
    """
    Status of an individual Step.
    
    Transitions:
    PENDING → RUNNING → COMPLETED
                    ↘ FAILED
    PENDING → AWAITING_APPROVAL → APPROVED → RUNNING
                               ↘ SKIPPED
    """
    PENDING = "pending"                    # Not yet executed
    AWAITING_APPROVAL = "awaiting_approval"  # Needs human approval
    APPROVED = "approved"                  # Approved, ready to execute
    RUNNING = "running"                    # Currently executing
    COMPLETED = "completed"                # Finished successfully
    FAILED = "failed"                      # Execution failed
    SKIPPED = "skipped"                    # Skipped by user


class StepType(str, enum.Enum):
    """
    Types of steps the engine can execute.
    
    Each type has its own executor with specific input/output shapes.
    """
    READ_FILE = "read_file"         # Read file contents
    ANALYZE = "analyze"             # LLM reasoning via Smart Model Router
    EDIT_FILE = "edit_file"         # Propose file changes (requires approval)
    RUN_COMMAND = "run_command"     # Execute shell command (requires approval)
    SUMMARIZE = "summarize"         # Generate summary via LLM


# ===================
# ORM Models
# ===================

class AgentRun(Base):
    """
    Represents a complete agent execution lifecycle.
    
    An AgentRun:
    - Has one immutable goal
    - Has one generated plan (list of steps)
    - Progresses through status states
    - Tracks total cost across all steps
    
    Example:
        run = AgentRun(goal="Refactor UserService for testability")
        # Plan gets generated, steps get created
        # Steps execute one by one
        # Run completes or fails
    """
    __tablename__ = "agent_runs"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # The goal is IMMUTABLE after creation
    goal: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    # Current status (uses Enum for type safety)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status_enum"),
        nullable=False,
        default=RunStatus.CREATED,
        index=True,  # Common query pattern: find runs by status
    )
    
    # Workspace path for this run (security boundary)
    workspace_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    
    # The generated plan (stored as JSON)
    # This is the full plan structure from the LLM
    plan: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,  # Null until planning completes
    )
    
    # Error message if run failed
    error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    # Relationship to steps (one-to-many)
    # lazy="selectin" is async-compatible eager loading
    steps: Mapped[list["Step"]] = relationship(
        back_populates="run",
        lazy="selectin",
        order_by="Step.step_number",  # Always ordered by execution order
        cascade="all, delete-orphan",  # Delete steps when run is deleted
    )
    
    def __repr__(self) -> str:
        return f"<AgentRun(id={self.id}, status={self.status.value}, goal='{self.goal[:50]}...')>"


class Step(Base):
    """
    Represents a single executable step in an AgentRun.
    
    Each step:
    - Has a type (read_file, analyze, etc.)
    - Has input parameters (JSONB for flexibility)
    - Produces output (JSONB for flexibility)
    - Tracks its own cost metadata
    - Executes in deterministic order (step_number)
    
    Example:
        step = Step(
            run_id=run.id,
            step_number=1,
            step_type=StepType.READ_FILE,
            input={"path": "src/service.py"}
        )
        # After execution:
        step.output = {"content": "class UserService: ..."}
        step.status = StepStatus.COMPLETED
    """
    __tablename__ = "agent_steps"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Foreign key to parent run
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Execution order (1, 2, 3, ...)
    # CRITICAL for deterministic execution
    step_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    
    # Step type (determines which executor to use)
    step_type: Mapped[StepType] = mapped_column(
        Enum(StepType, name="step_type_enum"),
        nullable=False,
    )
    
    # Current status
    status: Mapped[StepStatus] = mapped_column(
        Enum(StepStatus, name="step_status_enum"),
        nullable=False,
        default=StepStatus.PENDING,
        index=True,
    )
    
    # Input parameters (flexible structure per step type)
    input: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )
    
    # Output from execution (flexible structure)
    output: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,  # Null until step completes
    )
    
    # Error message if step failed
    error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Cost tracking metadata
    # Stores: model, prompt_tokens, completion_tokens, estimated_cost, latency_ms
    cost_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )
    
    # For LLM steps: store the actual prompt and response for debugging
    prompt_sent: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    response_received: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Retry tracking
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,  # Set when step starts executing
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,  # Set when step completes/fails
    )
    
    # Relationship back to run
    run: Mapped["AgentRun"] = relationship(
        back_populates="steps",
    )
    
    def __repr__(self) -> str:
        return f"<Step(id={self.id}, number={self.step_number}, type={self.step_type.value}, status={self.status.value})>"
    
    @property
    def requires_approval(self) -> bool:
        """Check if this step type requires human approval."""
        return self.step_type in (StepType.EDIT_FILE, StepType.RUN_COMMAND)
