"""
RunCommandExecutor - Executes shell commands (MOCKED for MVP).

This executor is MOCKED for safety. In production, it would
integrate with a sandboxed environment (Docker, etc.).

Input:
    {
        "command": "npm install",
        "working_dir": "."  # Optional, relative to workspace
    }

Output (mocked):
    {
        "command": "npm install",
        "stdout": "[MOCKED] Command would execute: npm install",
        "stderr": "",
        "exit_code": 0,
        "mocked": true
    }

SECURITY: In real implementation, this would:
1. Run in Docker container
2. Have network restrictions
3. Have resource limits (CPU, memory, time)
4. Require human approval before execution
"""

import time
from typing import Optional

from src.db.models import StepType
from src.executors.base import BaseExecutor, StepResult
from src.services.workspace import WorkspaceManager


class RunCommandExecutor(BaseExecutor):
    """
    Executor for running shell commands (MOCKED for MVP).
    
    WHY MOCKED?
    Running arbitrary shell commands is dangerous. A real implementation
    would need sandboxing (Docker container, restrictive permissions, etc.)
    For MVP, we mock the execution and show what WOULD happen.
    
    FUTURE IMPLEMENTATION:
    - Plugin architecture for sandbox backends
    - Docker container execution
    - Timeout and resource limits
    - Output streaming
    """
    
    def __init__(self, workspace: WorkspaceManager, allow_real_execution: bool = False):
        """
        Initialize the executor.
        
        Args:
            workspace: WorkspaceManager for working directory resolution
            allow_real_execution: If True, actually run commands (DANGER!)
                                 Default False = mocked
        """
        self.workspace = workspace
        self.allow_real_execution = allow_real_execution
    
    @property
    def step_type(self) -> StepType:
        """This executor handles RUN_COMMAND steps."""
        return StepType.RUN_COMMAND
    
    @property
    def requires_approval(self) -> bool:
        """Commands ALWAYS require human approval."""
        return True
    
    async def validate_input(self, input: dict) -> Optional[str]:
        """
        Validate that input contains required 'command' field.
        """
        if "command" not in input:
            return "Missing required field: 'command'"
        
        if not isinstance(input["command"], str):
            return "'command' must be a string"
        
        if not input["command"].strip():
            return "'command' cannot be empty"
        
        # Basic security checks for dangerous commands
        dangerous_patterns = [
            "rm -rf /",
            ":(){ :|:& };:",  # Fork bomb
            "> /dev/sda",
            "mkfs",
            "dd if=/dev/zero",
        ]
        
        command = input["command"].lower()
        for pattern in dangerous_patterns:
            if pattern in command:
                return f"Dangerous command pattern detected: {pattern}"
        
        return None
    
    async def execute(self, input: dict, context: dict) -> StepResult:
        """
        Execute a command (mocked for MVP).
        
        Args:
            input: {"command": "npm install", "working_dir": "."}
            context: Previous step outputs
        
        Returns:
            StepResult with command output (mocked)
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
        
        command = input["command"]
        working_dir = input.get("working_dir", ".")
        
        # Validate working directory is within workspace
        try:
            resolved_dir = self.workspace.resolve_path(working_dir)
        except Exception as e:
            return StepResult(
                success=False,
                error=f"Invalid working directory: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
        
        if self.allow_real_execution:
            # REAL EXECUTION (only if explicitly enabled)
            return await self._execute_real(command, resolved_dir, start_time)
        else:
            # MOCKED EXECUTION (default, safe)
            return await self._execute_mocked(command, working_dir, start_time)
    
    async def _execute_mocked(
        self,
        command: str,
        working_dir: str,
        start_time: float,
    ) -> StepResult:
        """
        Return a mocked command execution result.
        """
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        
        return StepResult(
            success=True,
            output={
                "command": command,
                "working_dir": working_dir,
                "stdout": f"[MOCKED] Command would execute in {working_dir}:\n$ {command}\n\n"
                          f"(Real execution disabled for MVP safety)",
                "stderr": "",
                "exit_code": 0,
                "mocked": True,
            },
            latency_ms=latency_ms,
        )
    
    async def _execute_real(
        self,
        command: str,
        working_dir,
        start_time: float,
    ) -> StepResult:
        """
        Actually execute the command (use with extreme caution!).
        
        This is only called if allow_real_execution=True.
        In production, this would run in a sandboxed container.
        """
        import asyncio
        import subprocess
        
        try:
            # Run command with timeout
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(working_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            
            # Wait with timeout (30 seconds max)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                process.kill()
                return StepResult(
                    success=False,
                    error="Command timed out after 30 seconds",
                    latency_ms=int((time.perf_counter() - start_time) * 1000),
                )
            
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            return StepResult(
                success=process.returncode == 0,
                output={
                    "command": command,
                    "working_dir": str(working_dir),
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                    "exit_code": process.returncode,
                    "mocked": False,
                },
                error=f"Command failed with exit code {process.returncode}" if process.returncode != 0 else None,
                latency_ms=latency_ms,
            )
        
        except Exception as e:
            return StepResult(
                success=False,
                error=f"Error executing command: {str(e)}",
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
