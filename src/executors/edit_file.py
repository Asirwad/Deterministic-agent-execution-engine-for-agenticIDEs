"""
EditFileExecutor - Proposes file edits that require human approval.

This executor:
1. Generates a proposed file edit (new content or patch)
2. Returns AWAITING_APPROVAL status
3. Only applies the change after user approval

Input:
    {
        "path": "src/main.py",
        "new_content": "updated file content..."  # OR
        "patch": "unified diff patch..."          # For partial edits
    }

Output (before approval):
    {
        "path": "src/main.py",
        "original_content": "old content...",
        "proposed_content": "new content...",
        "diff": "unified diff showing changes..."
    }

IMPORTANT: This executor does NOT write files directly.
The ExecutionEngine handles approval flow and applies changes.
"""

import difflib
import time
from typing import Optional

from src.db.models import StepType
from src.executors.base import BaseExecutor, StepResult
from src.services.workspace import WorkspaceManager, WorkspaceSecurityError


class EditFileExecutor(BaseExecutor):
    """
    Executor for proposing file edits.
    
    Unlike read_file, this executor requires human approval before
    changes are applied. The execution flow is:
    
    1. Step starts → Status: PENDING
    2. Executor runs → Generates diff → Status: AWAITING_APPROVAL
    3. User reviews diff
    4. User approves → WorkspaceManager writes file → Status: COMPLETED
       OR User rejects → Status: SKIPPED
    
    This ensures humans always review file changes before they happen.
    """
    
    def __init__(self, workspace: WorkspaceManager):
        """
        Initialize the executor with a workspace.
        
        Args:
            workspace: WorkspaceManager for file operations
        """
        self.workspace = workspace
    
    @property
    def step_type(self) -> StepType:
        """This executor handles EDIT_FILE steps."""
        return StepType.EDIT_FILE
    
    @property
    def requires_approval(self) -> bool:
        """File edits ALWAYS require human approval."""
        return True
    
    async def validate_input(self, input: dict) -> Optional[str]:
        """
        Validate that input contains required fields.
        """
        if "path" not in input:
            return "Missing required field: 'path'"
        
        if "new_content" not in input and "patch" not in input:
            return "Must provide either 'new_content' or 'patch'"
        
        if not isinstance(input["path"], str):
            return "'path' must be a string"
        
        return None
    
    def _generate_diff(self, original: str, new: str, path: str) -> str:
        """
        Generate a unified diff between original and new content.
        """
        original_lines = original.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        
        return "".join(diff)
    
    async def execute(self, input: dict, context: dict) -> StepResult:
        """
        Propose a file edit (does NOT apply it).
        
        The actual file write happens after approval in the ExecutionEngine.
        
        Args:
            input: {"path": "...", "new_content": "..."}
            context: Previous step outputs
        
        Returns:
            StepResult with proposed changes and diff
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
        
        path = input["path"]
        
        try:
            # Check if file exists and read current content
            if self.workspace.exists(path):
                original_content = await self.workspace.read_file(path)
            else:
                original_content = ""  # New file
            
            # Get the new content
            if "new_content" in input:
                new_content = input["new_content"]
            else:
                # TODO: Apply patch to original content
                # For MVP, we only support full content replacement
                return StepResult(
                    success=False,
                    error="Patch-based editing not yet implemented. Use 'new_content' instead.",
                    latency_ms=int((time.perf_counter() - start_time) * 1000),
                )
            
            # Generate diff for review
            diff = self._generate_diff(original_content, new_content, path)
            
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            return StepResult(
                success=True,
                output={
                    "path": path,
                    "original_content": original_content,
                    "proposed_content": new_content,
                    "diff": diff,
                    "is_new_file": not self.workspace.exists(path),
                    "lines_added": diff.count("\n+") if diff else 0,
                    "lines_removed": diff.count("\n-") if diff else 0,
                },
                latency_ms=latency_ms,
            )
        
        except WorkspaceSecurityError as e:
            return StepResult(
                success=False,
                error=f"Security error: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
        
        except Exception as e:
            return StepResult(
                success=False,
                error=f"Error preparing file edit: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
    
    async def apply_edit(self, path: str, content: str) -> StepResult:
        """
        Apply an approved edit (called by ExecutionEngine after approval).
        
        This is a separate method because the actual write only happens
        after human approval.
        
        Args:
            path: File path to write
            content: Content to write
        
        Returns:
            StepResult indicating success/failure of write
        """
        start_time = time.perf_counter()
        
        try:
            await self.workspace.write_file(path, content)
            
            return StepResult(
                success=True,
                output={
                    "path": path,
                    "written": True,
                    "size": len(content),
                },
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
        
        except WorkspaceSecurityError as e:
            return StepResult(
                success=False,
                error=f"Security error: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
        
        except Exception as e:
            return StepResult(
                success=False,
                error=f"Error writing file: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
