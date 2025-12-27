"""
ReadFileExecutor - Reads files from the workspace.

This is the simplest executor:
- No LLM calls (no cost)
- No approval needed (read-only operation)
- Uses WorkspaceManager for security

Input:
    {"path": "src/main.py"}

Output:
    {"content": "file contents...", "path": "src/main.py", "size": 1234}
"""

import time
from typing import Optional

from src.db.models import StepType
from src.executors.base import BaseExecutor, StepResult
from src.services.workspace import WorkspaceManager, WorkspaceSecurityError


class ReadFileExecutor(BaseExecutor):
    """
    Executor for reading files from the workspace.
    
    This is a foundational executor - many workflows start by reading
    files to understand the codebase before making changes.
    
    Security:
        All paths are validated through WorkspaceManager.
        Paths that escape the workspace are rejected.
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
        """This executor handles READ_FILE steps."""
        return StepType.READ_FILE
    
    @property
    def requires_approval(self) -> bool:
        """Reading files is safe - no approval needed."""
        return False
    
    async def validate_input(self, input: dict) -> Optional[str]:
        """
        Validate that input contains required 'path' field.
        
        Args:
            input: Step input to validate
        
        Returns:
            None if valid, error message if invalid
        """
        if "path" not in input:
            return "Missing required field: 'path'"
        
        if not isinstance(input["path"], str):
            return "'path' must be a string"
        
        if not input["path"].strip():
            return "'path' cannot be empty"
        
        return None
    
    async def execute(self, input: dict, context: dict) -> StepResult:
        """
        Read a file from the workspace.
        
        Args:
            input: {"path": "relative/path/to/file.py"}
            context: Previous step outputs (not used for read_file)
        
        Returns:
            StepResult with file content or error
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
            # Read the file through workspace manager (security check happens here)
            content = await self.workspace.read_file(path)
            
            # Calculate latency
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            return StepResult(
                success=True,
                output={
                    "content": content,
                    "path": path,
                    "size": len(content),
                    "lines": content.count("\n") + 1,
                },
                latency_ms=latency_ms,
            )
        
        except WorkspaceSecurityError as e:
            return StepResult(
                success=False,
                error=f"Security error: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
        
        except FileNotFoundError:
            return StepResult(
                success=False,
                error=f"File not found: {path}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
        
        except IsADirectoryError:
            return StepResult(
                success=False,
                error=f"Path is a directory, not a file: {path}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
        
        except UnicodeDecodeError:
            return StepResult(
                success=False,
                error=f"File is not a text file (binary content): {path}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
        
        except Exception as e:
            # Catch any unexpected errors
            return StepResult(
                success=False,
                error=f"Unexpected error reading file: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
