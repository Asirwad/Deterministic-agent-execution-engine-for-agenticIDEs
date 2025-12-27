"""
FastAPI routes for Agent Runs.

These routes expose the ExecutionEngine functionality via REST API.
All routes are prefixed with /v1/agent-runs.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    ApprovalResponse,
    CostResponse,
    CreateRunRequest,
    CreateStepRequest,
    ErrorResponse,
    ExecuteStepResponse,
    RunResponse,
    RunSummaryResponse,
    StepResponse,
)
from src.config import get_settings
from src.db.models import AgentRun, RunStatus, Step, StepStatus, StepType
from src.db.session import get_session
from src.engine import (
    ExecutionEngine,
    InvalidStateError,
    RunNotFoundError,
    StepNotFoundError,
)
from src.services.smart_router import SmartRouterClient
from src.services.workspace import WorkspaceManager


router = APIRouter(prefix="/v1/agent-runs", tags=["Agent Runs"])


def get_workspace() -> WorkspaceManager:
    """Get the workspace manager instance."""
    settings = get_settings()
    return WorkspaceManager(settings.workspace_path)


def get_router_client() -> SmartRouterClient:
    """Get the Smart Router client instance."""
    return SmartRouterClient()


def get_engine(
    session: AsyncSession = Depends(get_session),
    workspace: WorkspaceManager = Depends(get_workspace),
    router_client: SmartRouterClient = Depends(get_router_client),
) -> ExecutionEngine:
    """Get the execution engine with all dependencies."""
    return ExecutionEngine(session, workspace, router_client)


# ===================
# Create Run
# ===================

@router.post(
    "",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
)
async def create_run(
    request: CreateRunRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Create a new agent run.
    
    This creates a run with the given goal. You'll need to add steps
    before executing.
    """
    settings = get_settings()
    workspace_path = request.workspace_path or str(settings.workspace_path)
    
    run = AgentRun(
        goal=request.goal,
        workspace_path=workspace_path,
        status=RunStatus.CREATED,
    )
    
    session.add(run)
    await session.commit()
    await session.refresh(run)
    
    return RunResponse(
        id=run.id,
        goal=run.goal,
        status=run.status.value,
        workspace_path=run.workspace_path,
        plan=run.plan,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[],
    )


# ===================
# Get Run
# ===================

@router.get(
    "/{run_id}",
    response_model=RunResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_run(
    run_id: UUID,
    engine: ExecutionEngine = Depends(get_engine),
):
    """
    Get an agent run by ID.
    
    Returns the run with all its steps.
    """
    try:
        run = await engine.get_run(run_id)
    except RunNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )
    
    return RunResponse(
        id=run.id,
        goal=run.goal,
        status=run.status.value,
        workspace_path=run.workspace_path,
        plan=run.plan,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[
            StepResponse(
                id=step.id,
                step_number=step.step_number,
                step_type=step.step_type.value,
                status=step.status.value,
                input=step.input,
                output=step.output,
                error=step.error,
                cost_metadata=step.cost_metadata,
                created_at=step.created_at,
                started_at=step.started_at,
                completed_at=step.completed_at,
            )
            for step in sorted(run.steps, key=lambda s: s.step_number)
        ],
    )


# ===================
# Add Step
# ===================

@router.post(
    "/{run_id}/steps",
    response_model=StepResponse,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
)
async def add_step(
    run_id: UUID,
    request: CreateStepRequest,
    engine: ExecutionEngine = Depends(get_engine),
    session: AsyncSession = Depends(get_session),
):
    """
    Add a step to a run.
    
    Steps are executed in the order they are added.
    """
    try:
        run = await engine.get_run(run_id)
    except RunNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )
    
    # Validate step type
    try:
        step_type = StepType(request.step_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid step type: {request.step_type}. "
                   f"Valid types: {[t.value for t in StepType]}",
        )
    
    # Calculate next step number
    next_number = len(run.steps) + 1
    
    step = Step(
        run_id=run.id,
        step_number=next_number,
        step_type=step_type,
        status=StepStatus.PENDING,
        input=request.input,
    )
    
    session.add(step)
    
    # Update run status if first step
    if run.status == RunStatus.CREATED:
        run.status = RunStatus.PLANNED
    
    await session.commit()
    await session.refresh(step)
    
    return StepResponse(
        id=step.id,
        step_number=step.step_number,
        step_type=step.step_type.value,
        status=step.status.value,
        input=step.input,
        output=step.output,
        error=step.error,
        cost_metadata=step.cost_metadata,
        created_at=step.created_at,
        started_at=step.started_at,
        completed_at=step.completed_at,
    )


# ===================
# Execute Next Step
# ===================

@router.post(
    "/{run_id}/execute",
    response_model=ExecuteStepResponse,
    responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
)
async def execute_next_step(
    run_id: UUID,
    engine: ExecutionEngine = Depends(get_engine),
):
    """
    Execute the next pending step in the run.
    
    Returns the result of execution. If a step requires approval,
    returns with status 'awaiting_approval'.
    """
    try:
        run = await engine.get_run(run_id)
        result = await engine.execute_next_step(run_id)
    except RunNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )
    except InvalidStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    # Reload run to get updated state
    run = await engine.get_run(run_id)
    
    if result is None:
        # All steps complete
        return ExecuteStepResponse(
            success=True,
            run_id=run_id,
            status="all_complete",
            output={"message": "All steps have been executed"},
        )
    
    # Find the current step
    current_step = None
    for step in run.steps:
        if step.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.AWAITING_APPROVAL):
            if step.completed_at or step.status == StepStatus.AWAITING_APPROVAL:
                current_step = step
    
    return ExecuteStepResponse(
        success=result.success,
        run_id=run_id,
        step_number=current_step.step_number if current_step else None,
        step_type=current_step.step_type.value if current_step else None,
        status=current_step.status.value if current_step else run.status.value,
        output=result.output,
        error=result.error,
        cost=result.cost_metadata,
    )


# ===================
# Approve Step
# ===================

@router.post(
    "/{run_id}/steps/{step_id}/approve",
    response_model=ExecuteStepResponse,
    responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
)
async def approve_step(
    run_id: UUID,
    step_id: UUID,
    engine: ExecutionEngine = Depends(get_engine),
):
    """
    Approve a step that's awaiting approval and execute it.
    
    This is required for sensitive operations like edit_file and run_command.
    """
    try:
        result = await engine.approve_step(run_id, step_id)
    except RunNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )
    except StepNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Step not found: {step_id}",
        )
    except InvalidStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    return ExecuteStepResponse(
        success=result.success,
        run_id=run_id,
        status="completed" if result.success else "failed",
        output=result.output,
        error=result.error,
        cost=result.cost_metadata,
    )


# ===================
# Skip Step
# ===================

@router.post(
    "/{run_id}/steps/{step_id}/skip",
    response_model=ApprovalResponse,
    responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
)
async def skip_step(
    run_id: UUID,
    step_id: UUID,
    engine: ExecutionEngine = Depends(get_engine),
):
    """
    Skip a step that's awaiting approval.
    
    The step will be marked as skipped and execution continues.
    """
    try:
        await engine.skip_step(run_id, step_id)
    except RunNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )
    except StepNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Step not found: {step_id}",
        )
    except InvalidStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    return ApprovalResponse(
        success=True,
        run_id=run_id,
        step_id=step_id,
        message="Step skipped",
    )


# ===================
# Get Cost
# ===================

@router.get(
    "/{run_id}/cost",
    response_model=CostResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_run_cost(
    run_id: UUID,
    engine: ExecutionEngine = Depends(get_engine),
):
    """
    Get the cost breakdown for a run.
    
    Returns total cost and per-step costs for all completed steps.
    """
    try:
        cost_info = await engine.get_run_cost(run_id)
    except RunNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )
    
    return CostResponse(
        run_id=run_id,
        total_cost=cost_info["total_cost"],
        total_tokens=cost_info["total_tokens"],
        steps=cost_info["steps"],
    )


# ===================
# Create a separate router for planning
# ===================
from src.api.schemas import PlanRequest, PlanResponse
from src.services.planner import PlannerService, PlannerError

plan_router = APIRouter(prefix="/v1", tags=["Planning"])


@plan_router.post(
    "/plan",
    response_model=PlanResponse,
    responses={400: {"model": ErrorResponse}},
)
async def create_plan(
    request: PlanRequest,
    session: AsyncSession = Depends(get_session),
    workspace: WorkspaceManager = Depends(get_workspace),
    router_client: SmartRouterClient = Depends(get_router_client),
):
    """
    Generate a plan of steps from a goal using LLM.
    
    This analyzes the goal and creates a structured list of steps
    that can be added to a run. Optionally auto-adds steps to an existing run.
    """
    planner = PlannerService(router_client, workspace)
    
    try:
        steps, llm_response = await planner.create_plan(
            goal=request.goal,
            workspace_files=request.workspace_files,
            additional_context=request.additional_context,
        )
    except PlannerError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    steps_added = 0
    run_id = request.run_id
    
    # Auto-add steps if requested
    if request.auto_add_steps and request.run_id:
        from src.engine import ExecutionEngine, RunNotFoundError
        
        engine = ExecutionEngine(session, workspace, router_client)
        
        try:
            run = await engine.get_run(request.run_id)
        except RunNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run not found: {request.run_id}",
            )
        
        # Add each step
        for step_def in steps:
            step = Step(
                run_id=run.id,
                step_number=len(run.steps) + 1,
                step_type=StepType(step_def["step_type"]),
                status=StepStatus.PENDING,
                input=step_def["input"],
            )
            session.add(step)
            run.steps.append(step)
            steps_added += 1
        
        if run.status == RunStatus.CREATED:
            run.status = RunStatus.PLANNED
        
        await session.commit()
    
    return PlanResponse(
        success=True,
        steps=steps,
        cost={
            "model": llm_response.model,
            "estimated_cost": llm_response.estimated_cost,
            "latency_ms": llm_response.latency_ms,
        },
        run_id=run_id,
        steps_added=steps_added,
    )
