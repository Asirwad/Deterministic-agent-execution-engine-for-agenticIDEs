"""
PlannerService - Converts goals into executable step plans via LLM.

This service uses the Smart Model Router to analyze a goal and
generate a structured plan of steps to achieve it.

Example:
    planner = PlannerService(router_client, workspace)
    steps = await planner.create_plan(
        goal="Refactor UserService to use dependency injection",
        workspace_files=["src/services/user.py"]
    )
    
    # Returns: [
    #     {"step_type": "read_file", "input": {"path": "src/services/user.py"}},
    #     {"step_type": "analyze", "input": {"instruction": "Identify dependencies..."}},
    #     {"step_type": "edit_file", "input": {"path": "...", "new_content": "..."}},
    # ]
"""

import json
import re
from typing import Optional

from src.db.models import StepType
from src.services.smart_router import SmartRouterClient, SmartRouterError, LLMResponse
from src.services.workspace import WorkspaceManager


class PlannerError(Exception):
    """Raised when planning fails."""
    pass


class PlannerService:
    """
    Service for converting goals into executable plans.
    
    The planner:
    1. Analyzes the goal and workspace context
    2. Generates a structured plan of steps
    3. Validates that each step has correct type and input
    4. Returns step definitions ready to be added to a run
    """
    
    SYSTEM_PROMPT = """You are an expert software engineering AI that creates execution plans.

Given a goal, generate a plan as a JSON array of steps. Each step must have:
- "step_type": One of "read_file", "analyze", "edit_file", "run_command", "summarize"
- "input": Object with step-specific parameters
- "description": Brief description of what this step does

Step type requirements:
- read_file: {"path": "relative/path/to/file"}
- analyze: {"instruction": "What to analyze"}
- edit_file: {"path": "file", "new_content": "full new file content"}
- run_command: {"command": "shell command", "working_dir": "."}
- summarize: {"instruction": "What to summarize"}

Guidelines:
1. Start by reading relevant files to understand the codebase
2. Use analyze steps to reason about what changes are needed
3. edit_file and run_command require human approval - use sparingly
4. End with a summarize step explaining what was done
5. Keep plans focused and minimal (usually 3-7 steps)

IMPORTANT: Respond with ONLY a JSON array. No markdown, no explanation.

Example output:
[
  {"step_type": "read_file", "input": {"path": "src/main.py"}, "description": "Read the main file"},
  {"step_type": "analyze", "input": {"instruction": "Identify issues in the code"}, "description": "Analyze for problems"}
]"""
    
    def __init__(
        self,
        router_client: SmartRouterClient,
        workspace: Optional[WorkspaceManager] = None,
    ):
        """
        Initialize the planner.
        
        Args:
            router_client: SmartRouterClient for LLM calls
            workspace: Optional WorkspaceManager for file listing
        """
        self.router = router_client
        self.workspace = workspace
    
    def _build_prompt(
        self,
        goal: str,
        workspace_files: Optional[list[str]] = None,
        additional_context: Optional[str] = None,
    ) -> str:
        """Build the planning prompt."""
        prompt_parts = [f"## Goal\n{goal}"]
        
        if workspace_files:
            files_list = "\n".join(f"- {f}" for f in workspace_files[:20])
            prompt_parts.append(f"## Available Files\n{files_list}")
        
        if additional_context:
            prompt_parts.append(f"## Additional Context\n{additional_context}")
        
        prompt_parts.append("\n## Task\nGenerate a step-by-step plan to achieve this goal.")
        
        return "\n\n".join(prompt_parts)
    
    def _parse_plan(self, response: str) -> list[dict]:
        """
        Parse the LLM response into step definitions.
        
        Args:
            response: Raw LLM response text
        
        Returns:
            List of step dictionaries
        
        Raises:
            PlannerError: If response cannot be parsed
        """
        # Try to extract JSON from the response
        text = response.strip()
        
        # Remove markdown code blocks if present
        if text.startswith("```"):
            # Find the JSON content
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if match:
                text = match.group(1).strip()
        
        try:
            plan = json.loads(text)
        except json.JSONDecodeError as e:
            raise PlannerError(f"Failed to parse plan as JSON: {e}\nResponse: {text[:500]}")
        
        if not isinstance(plan, list):
            raise PlannerError(f"Plan must be a list, got: {type(plan).__name__}")
        
        return plan
    
    def _validate_step(self, step: dict, step_index: int) -> dict:
        """
        Validate and normalize a step definition.
        
        Args:
            step: Raw step from LLM
            step_index: Position in plan (for error messages)
        
        Returns:
            Validated step dictionary
        
        Raises:
            PlannerError: If step is invalid
        """
        if not isinstance(step, dict):
            raise PlannerError(f"Step {step_index} must be a dict, got: {type(step).__name__}")
        
        # Validate step_type
        step_type_str = step.get("step_type")
        if not step_type_str:
            raise PlannerError(f"Step {step_index} missing 'step_type'")
        
        try:
            step_type = StepType(step_type_str)
        except ValueError:
            valid_types = [t.value for t in StepType]
            raise PlannerError(
                f"Step {step_index} has invalid step_type '{step_type_str}'. "
                f"Valid types: {valid_types}"
            )
        
        # Validate input
        step_input = step.get("input")
        if not isinstance(step_input, dict):
            raise PlannerError(f"Step {step_index} 'input' must be a dict")
        
        # Type-specific validation
        if step_type == StepType.READ_FILE:
            if "path" not in step_input:
                raise PlannerError(f"Step {step_index} (read_file) missing 'path' in input")
        
        elif step_type == StepType.ANALYZE:
            if "instruction" not in step_input:
                raise PlannerError(f"Step {step_index} (analyze) missing 'instruction' in input")
        
        elif step_type == StepType.EDIT_FILE:
            if "path" not in step_input:
                raise PlannerError(f"Step {step_index} (edit_file) missing 'path' in input")
            if "new_content" not in step_input:
                raise PlannerError(f"Step {step_index} (edit_file) missing 'new_content' in input")
        
        elif step_type == StepType.RUN_COMMAND:
            if "command" not in step_input:
                raise PlannerError(f"Step {step_index} (run_command) missing 'command' in input")
        
        elif step_type == StepType.SUMMARIZE:
            if "instruction" not in step_input:
                raise PlannerError(f"Step {step_index} (summarize) missing 'instruction' in input")
        
        return {
            "step_type": step_type.value,
            "input": step_input,
            "description": step.get("description", ""),
        }
    
    async def create_plan(
        self,
        goal: str,
        workspace_files: Optional[list[str]] = None,
        additional_context: Optional[str] = None,
    ) -> tuple[list[dict], LLMResponse]:
        """
        Create a plan to achieve the given goal.
        
        Args:
            goal: The goal to accomplish
            workspace_files: Optional list of relevant files
            additional_context: Optional additional context
        
        Returns:
            Tuple of (validated steps list, LLM response for cost tracking)
        
        Raises:
            PlannerError: If planning fails
            SmartRouterError: If LLM call fails
        """
        prompt = self._build_prompt(goal, workspace_files, additional_context)
        
        try:
            response = await self.router.complete(
                prompt=prompt,
                system_prompt=self.SYSTEM_PROMPT,
            )
        except SmartRouterError as e:
            raise PlannerError(f"LLM call failed: {e}")
        
        # Parse the response
        raw_steps = self._parse_plan(response.content)
        
        # Validate each step
        validated_steps = []
        for i, step in enumerate(raw_steps):
            validated = self._validate_step(step, i + 1)
            validated_steps.append(validated)
        
        return validated_steps, response
    
    async def list_workspace_files(self, max_depth: int = 3) -> list[str]:
        """
        List files in the workspace for context.
        
        Args:
            max_depth: Maximum directory depth to traverse
        
        Returns:
            List of relative file paths
        """
        if not self.workspace:
            return []
        
        files = []
        
        async def _walk(path: str, depth: int):
            if depth > max_depth:
                return
            
            try:
                items = await self.workspace.list_dir(path)
                for item in items:
                    full_path = f"{path}/{item}" if path != "." else item
                    
                    # Skip common non-essential directories
                    if item in (".git", ".venv", "node_modules", "__pycache__", ".ruff_cache"):
                        continue
                    
                    if self.workspace.is_file(full_path):
                        files.append(full_path)
                    elif self.workspace.is_dir(full_path):
                        await _walk(full_path, depth + 1)
            except Exception:
                pass  # Skip inaccessible directories
        
        await _walk(".", 0)
        return files[:100]  # Limit to 100 files
