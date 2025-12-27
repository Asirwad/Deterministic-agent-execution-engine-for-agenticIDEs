"""
Execution Engine - The core orchestrator for agent runs.

This is the HEART of the system. It:
1. Loads runs and steps from the database
2. Routes steps to the correct executor
3. Accumulates context from completed steps
4. Handles approval workflow for sensitive operations
5. Persists state after each step
6. Tracks total cost across all steps

Design Principles:
- Steps execute sequentially (deterministic order)
- All state is persisted after each step (resumable)
- Failed steps stop execution (explicit failure)
- Sensitive operations require human approval
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AgentRun, RunStatus, Step, StepStatus, StepType
from src.executors.base import BaseExecutor, StepResult
from src.executors.read_file import ReadFileExecutor
from src.executors.analyze import AnalyzeExecutor
from src.executors.edit_file import EditFileExecutor
from src.executors.run_command import RunCommandExecutor
from src.executors.summarize import SummarizeExecutor
from src.services.workspace import WorkspaceManager
from src.services.smart_router import SmartRouterClient


class ExecutionEngineError(Exception):
    """Base exception for execution engine errors."""
    pass


class RunNotFoundError(ExecutionEngineError):
    """Raised when a run is not found."""
    pass


class StepNotFoundError(ExecutionEngineError):
    """Raised when a step is not found."""
    pass


class InvalidStateError(ExecutionEngineError):
    """Raised when an operation is invalid for the current state."""
    pass


class ExecutionEngine:
    """
    The core orchestrator for agent execution.
    
    Usage:
        engine = ExecutionEngine(session, workspace, router_client)
        
        # Execute the next pending step
        result = await engine.execute_next_step(run_id)
        
        # Approve a step awaiting approval
        await engine.approve_step(run_id, step_id)
        
        # Get total cost for a run
        cost = await engine.get_run_cost(run_id)
    """
    
    def __init__(
        self,
        session: AsyncSession,
        workspace: WorkspaceManager,
        router_client: SmartRouterClient,
    ):
        """
        Initialize the execution engine.
        
        Args:
            session: Database session for persistence
            workspace: WorkspaceManager for file operations
            router_client: SmartRouterClient for LLM operations
        """
        self.session = session
        self.workspace = workspace
        self.router = router_client
        
        # Initialize executors
        self.executors: dict[StepType, BaseExecutor] = {
            StepType.READ_FILE: ReadFileExecutor(workspace),
            StepType.ANALYZE: AnalyzeExecutor(router_client),
            StepType.EDIT_FILE: EditFileExecutor(workspace),
            StepType.RUN_COMMAND: RunCommandExecutor(workspace),
            StepType.SUMMARIZE: SummarizeExecutor(router_client),
        }
    
    async def get_run(self, run_id: uuid.UUID) -> AgentRun:
        """
        Get an agent run by ID.
        
        Args:
            run_id: UUID of the run
        
        Returns:
            AgentRun object with steps loaded
        
        Raises:
            RunNotFoundError: If run doesn't exist
        """
        result = await self.session.execute(
            select(AgentRun).where(AgentRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        
        if not run:
            raise RunNotFoundError(f"Run not found: {run_id}")
        
        return run
    
    def _get_next_pending_step(self, run: AgentRun) -> Optional[Step]:
        """
        Get the next step that needs execution.
        
        Returns:
            Next PENDING or APPROVED step, or None if all complete
        """
        for step in sorted(run.steps, key=lambda s: s.step_number):
            if step.status == StepStatus.PENDING:
                return step
            if step.status == StepStatus.APPROVED:
                return step
        
        return None
    
    def _get_awaiting_approval_step(self, run: AgentRun) -> Optional[Step]:
        """Get a step that's awaiting approval."""
        for step in run.steps:
            if step.status == StepStatus.AWAITING_APPROVAL:
                return step
        return None
    
    def _build_context(self, run: AgentRun, current_step: Step) -> dict:
        """
        Build context from all completed steps before the current one.
        
        Context structure:
        {
            "goal": "The original goal",
            "step-1": {"type": "read_file", "input": {...}, "output": {...}},
            "step-2": {"type": "analyze", "input": {...}, "output": {...}},
            ...
        }
        """
        context = {"goal": run.goal}
        
        for step in sorted(run.steps, key=lambda s: s.step_number):
            if step.step_number >= current_step.step_number:
                break  # Don't include current or future steps
            
            if step.status == StepStatus.COMPLETED:
                context[f"step-{step.step_number}"] = {
                    "type": step.step_type.value,
                    "input": step.input,
                    "output": step.output or {},
                }
        
        return context
    
    async def execute_next_step(self, run_id: uuid.UUID) -> Optional[StepResult]:
        """
        Execute the next pending step in a run.
        
        This is the main entry point for step execution.
        
        Args:
            run_id: UUID of the run
        
        Returns:
            StepResult from execution, or None if no pending steps
        
        Raises:
            RunNotFoundError: If run doesn't exist
            InvalidStateError: If run is not in executable state
        """
        run = await self.get_run(run_id)
        
        # Check if run is in valid state
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
            raise InvalidStateError(
                f"Run is already {run.status.value}, cannot execute more steps"
            )
        
        # Check if waiting for approval
        awaiting = self._get_awaiting_approval_step(run)
        if awaiting:
            raise InvalidStateError(
                f"Step {awaiting.step_number} is awaiting approval. "
                f"Call approve_step() or skip_step() first."
            )
        
        # Get next step to execute
        step = self._get_next_pending_step(run)
        if not step:
            # All steps complete
            run.status = RunStatus.COMPLETED
            await self.session.commit()
            return None
        
        # Get the executor for this step type
        executor = self.executors.get(step.step_type)
        if not executor:
            step.status = StepStatus.FAILED
            step.error = f"No executor for step type: {step.step_type.value}"
            run.status = RunStatus.FAILED
            await self.session.commit()
            return StepResult(success=False, error=step.error)
        
        # Check if approval is required
        if executor.requires_approval and step.status == StepStatus.PENDING:
            # Mark as awaiting approval instead of executing
            step.status = StepStatus.AWAITING_APPROVAL
            run.status = RunStatus.AWAITING_APPROVAL
            await self.session.commit()
            
            # Return a result indicating approval is needed
            return StepResult(
                success=True,
                output={
                    "status": "awaiting_approval",
                    "step_number": step.step_number,
                    "step_type": step.step_type.value,
                    "input": step.input,
                },
            )
        
        # Execute the step
        run.status = RunStatus.RUNNING
        step.status = StepStatus.RUNNING
        step.started_at = datetime.now(timezone.utc)
        await self.session.commit()
        
        # Build context and execute
        context = self._build_context(run, step)
        result = await executor.execute(step.input, context)
        
        # Update step with result
        step.output = result.output
        step.error = result.error
        step.cost_metadata = result.cost_metadata
        step.prompt_sent = result.prompt_sent
        step.response_received = result.response_received
        step.completed_at = datetime.now(timezone.utc)
        
        if result.success:
            step.status = StepStatus.COMPLETED
            
            # Check if all steps are done
            remaining = [s for s in run.steps if s.status in (
                StepStatus.PENDING, StepStatus.AWAITING_APPROVAL, StepStatus.APPROVED
            )]
            if not remaining:
                run.status = RunStatus.COMPLETED
            else:
                run.status = RunStatus.RUNNING
        else:
            step.status = StepStatus.FAILED
            run.status = RunStatus.FAILED
            run.error = f"Step {step.step_number} failed: {result.error}"
        
        await self.session.commit()
        return result
    
    async def approve_step(self, run_id: uuid.UUID, step_id: uuid.UUID) -> StepResult:
        """
        Approve a step that's awaiting approval and execute it.
        
        Args:
            run_id: UUID of the run
            step_id: UUID of the step to approve
        
        Returns:
            StepResult from execution
        
        Raises:
            InvalidStateError: If step is not awaiting approval
        """
        run = await self.get_run(run_id)
        
        # Find the step
        step = None
        for s in run.steps:
            if s.id == step_id:
                step = s
                break
        
        if not step:
            raise StepNotFoundError(f"Step not found: {step_id}")
        
        if step.status != StepStatus.AWAITING_APPROVAL:
            raise InvalidStateError(
                f"Step is {step.status.value}, not awaiting approval"
            )
        
        # Mark as approved
        step.status = StepStatus.APPROVED
        run.status = RunStatus.RUNNING
        await self.session.commit()
        
        # Now execute it
        return await self.execute_next_step(run_id)
    
    async def skip_step(self, run_id: uuid.UUID, step_id: uuid.UUID) -> None:
        """
        Skip a step that's awaiting approval.
        
        Args:
            run_id: UUID of the run
            step_id: UUID of the step to skip
        """
        run = await self.get_run(run_id)
        
        step = None
        for s in run.steps:
            if s.id == step_id:
                step = s
                break
        
        if not step:
            raise StepNotFoundError(f"Step not found: {step_id}")
        
        if step.status != StepStatus.AWAITING_APPROVAL:
            raise InvalidStateError(
                f"Step is {step.status.value}, not awaiting approval"
            )
        
        step.status = StepStatus.SKIPPED
        step.completed_at = datetime.now(timezone.utc)
        run.status = RunStatus.RUNNING
        
        await self.session.commit()
    
    async def apply_edit(
        self,
        run_id: uuid.UUID,
        step_id: uuid.UUID,
    ) -> StepResult:
        """
        Apply an approved file edit.
        
        Called after approve_step() for EDIT_FILE steps to actually write the file.
        
        Args:
            run_id: UUID of the run
            step_id: UUID of the EDIT_FILE step
        
        Returns:
            StepResult indicating success/failure of write
        """
        run = await self.get_run(run_id)
        
        step = None
        for s in run.steps:
            if s.id == step_id:
                step = s
                break
        
        if not step:
            raise StepNotFoundError(f"Step not found: {step_id}")
        
        if step.step_type != StepType.EDIT_FILE:
            raise InvalidStateError("Can only apply edits for EDIT_FILE steps")
        
        if step.status != StepStatus.COMPLETED:
            raise InvalidStateError("Step must be completed before applying edit")
        
        # Get the edit executor and apply
        executor: EditFileExecutor = self.executors[StepType.EDIT_FILE]
        
        path = step.output.get("path")
        content = step.output.get("proposed_content")
        
        if not path or content is None:
            return StepResult(
                success=False,
                error="Missing path or content in step output",
            )
        
        return await executor.apply_edit(path, content)
    
    async def get_run_cost(self, run_id: uuid.UUID) -> dict:
        """
        Get the total cost for a run.
        
        Returns:
            {
                "total_cost": 0.00125,
                "total_tokens": {"prompt": 1500, "completion": 800},
                "steps": [
                    {"step_number": 2, "model": "gemini-flash", "cost": 0.0005},
                    ...
                ]
            }
        """
        run = await self.get_run(run_id)
        
        total_cost = 0.0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        step_costs = []
        
        for step in run.steps:
            if step.cost_metadata:
                cost = step.cost_metadata.get("estimated_cost", 0.0)
                prompt_tokens = step.cost_metadata.get("prompt_tokens", 0)
                completion_tokens = step.cost_metadata.get("completion_tokens", 0)
                
                total_cost += cost
                total_prompt_tokens += prompt_tokens
                total_completion_tokens += completion_tokens
                
                step_costs.append({
                    "step_number": step.step_number,
                    "step_type": step.step_type.value,
                    "model": step.cost_metadata.get("model", "unknown"),
                    "cost": cost,
                    "tokens": {
                        "prompt": prompt_tokens,
                        "completion": completion_tokens,
                    },
                })
        
        return {
            "total_cost": total_cost,
            "total_tokens": {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
            },
            "steps": step_costs,
        }
