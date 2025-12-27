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
from src.services.smart_router import SmartRouterClient, SmartRouterError, StructuredLLMResponse
from src.services.workspace import WorkspaceManager


class PlannerError(Exception):
    """Raised when planning fails."""
    pass


class PlannerService:
    """
    Service for converting goals into executable plans.
    
    Uses the Smart Router's /v1/structure endpoint for guaranteed JSON output
    conforming to our step schema. This eliminates prompt engineering complexity.
    """
    
    # JSON Schema for step plans - ensures LLM returns exactly this structure
    PLAN_SCHEMA = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "step_type": {
                    "type": "string",
                    "enum": ["read_file", "analyze", "edit_file", "run_command", "summarize"],
                    "description": "Type of step to execute"
                },
                "input": {
                    "type": "object",
                    "description": "Step-specific parameters"
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of what this step does"
                }
            },
            "required": ["step_type", "input", "description"]
        }
    }
    
    SYSTEM_PROMPT = """You are a software engineering assistant that creates execution plans.

Given a goal, generate a plan as a JSON array of steps. Keep plans focused and minimal (3-7 steps).

Step types and their input requirements:
- read_file: {"path": "relative/path/to/file"} - Read file contents
- analyze: {"instruction": "what to analyze"} - Think through a problem
- edit_file: {"path": "file", "new_content": "complete content"} - Write/modify file
- run_command: {"command": "shell command", "working_dir": "."} - Execute command
- summarize: {"instruction": "what to summarize"} - Provide summary

Guidelines:
1. Start by reading relevant files to understand context
2. Use analyze steps to reason about changes needed
3. For simple additions, use edit_file with the new content
4. End with a summarize step"""
    
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
        parts = [f"Goal: {goal}"]
        
        if workspace_files:
            parts.append(f"\nRelevant files: {', '.join(workspace_files[:10])}")
        
        if additional_context:
            parts.append(f"\nContext: {additional_context}")
        
        parts.append("\nCreate a step-by-step plan to accomplish this goal.")
        
        return "".join(parts)
    
    def _parse_plan(self, response: str) -> list[dict]:
        """
        Parse the LLM response into step definitions.
        
        Since we use the output prefix technique (prompt ends with '['),
        the LLM response continues from there. We need to prepend '[' if missing.
        
        Args:
            response: Raw LLM response text
        
        Returns:
            List of step dictionaries
        
        Raises:
            PlannerError: If response cannot be parsed
        """
        text = response.strip()
        
        # Remove markdown code blocks if present
        if "```" in text:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if match:
                text = match.group(1).strip()
        
        # Handle output prefix technique - LLM continues after our '['
        # So response might start with '{' instead of '['
        if text.startswith("{") or text.startswith("\n"):
            text = "[" + text
        
        # Ensure text starts with '[' and ends with ']'
        if not text.startswith("["):
            # Try to find JSON array in the response
            array_match = re.search(r'\[[\s\S]*\]', text)
            if array_match:
                text = array_match.group(0)
            else:
                raise PlannerError(f"Could not find JSON array in response: {text[:200]}")
        
        # Ensure proper closing
        if not text.rstrip().endswith("]"):
            text = text.rstrip() + "]"
        
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
    ) -> tuple[list[dict], StructuredLLMResponse]:
        """
        Create a plan to achieve the given goal.
        
        Uses the Smart Router's /v1/structure endpoint for guaranteed JSON output
        conforming to our PLAN_SCHEMA. No JSON parsing needed.
        
        Args:
            goal: The goal to accomplish
            workspace_files: Optional list of relevant files
            additional_context: Optional additional context
        
        Returns:
            Tuple of (validated steps list, response for cost tracking)
        
        Raises:
            PlannerError: If planning or validation fails
            SmartRouterError: If LLM call fails
        """
        prompt = self._build_prompt(goal, workspace_files, additional_context)
        
        try:
            # Use structured() for guaranteed JSON conforming to schema
            response = await self.router.structured(
                prompt=prompt,
                json_schema=self.PLAN_SCHEMA,
                system_prompt=self.SYSTEM_PROMPT,
            )
        except SmartRouterError as e:
            raise PlannerError(f"LLM call failed: {e}")
        
        # response.data is already parsed JSON guaranteed to be an array
        # Just validate the step contents
        raw_steps = response.data
        
        if not isinstance(raw_steps, list):
            raise PlannerError(f"Plan must be a list, got: {type(raw_steps).__name__}")
        
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
