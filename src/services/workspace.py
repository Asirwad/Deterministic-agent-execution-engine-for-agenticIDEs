"""
WorkspaceManager - Security boundary for file operations.

This service ensures that ALL file operations are restricted to
a specific workspace directory. This prevents agents from:
- Reading sensitive files (/etc/passwd, ~/.ssh/id_rsa)
- Writing outside the project directory
- Path traversal attacks (../../etc/passwd)

Usage:
    workspace = WorkspaceManager("/path/to/workspace")
    
    # Safe - within workspace
    safe_path = workspace.resolve_path("src/main.py")
    
    # Throws SecurityError - escapes workspace
    workspace.resolve_path("../../../etc/passwd")
"""

from pathlib import Path
from typing import Union


class WorkspaceSecurityError(Exception):
    """Raised when a path operation would escape the workspace."""
    pass


class WorkspaceManager:
    """
    Manages file operations within a secure workspace boundary.
    
    All paths are validated to ensure they remain within the workspace.
    This is CRITICAL for security when agents can read/write files.
    
    Attributes:
        root: The absolute path to the workspace root directory
    """
    
    def __init__(self, workspace_root: Union[str, Path]):
        """
        Initialize the workspace manager.
        
        Args:
            workspace_root: Path to the workspace root directory.
                           Will be created if it doesn't exist.
        """
        self.root = Path(workspace_root).resolve()
        
        # Create workspace if it doesn't exist
        self.root.mkdir(parents=True, exist_ok=True)
    
    def resolve_path(self, relative_path: str) -> Path:
        """
        Resolve a relative path to an absolute path within the workspace.
        
        Args:
            relative_path: Path relative to workspace root
        
        Returns:
            Absolute Path object
        
        Raises:
            WorkspaceSecurityError: If path would escape workspace
        
        Examples:
            workspace.resolve_path("src/main.py")  # OK
            workspace.resolve_path("../secret.txt")  # SecurityError!
        """
        # Handle both forward and back slashes
        normalized = relative_path.replace("\\", "/")
        
        # Resolve the full path
        full_path = (self.root / normalized).resolve()
        
        # Security check: ensure path is within workspace
        try:
            full_path.relative_to(self.root)
        except ValueError:
            raise WorkspaceSecurityError(
                f"Path '{relative_path}' escapes workspace boundary. "
                f"All paths must be within: {self.root}"
            )
        
        return full_path
    
    def validate_path(self, relative_path: str) -> bool:
        """
        Check if a path is valid (within workspace) without raising.
        
        Args:
            relative_path: Path to validate
        
        Returns:
            True if path is valid, False otherwise
        """
        try:
            self.resolve_path(relative_path)
            return True
        except WorkspaceSecurityError:
            return False
    
    def exists(self, relative_path: str) -> bool:
        """Check if a file exists within the workspace."""
        try:
            return self.resolve_path(relative_path).exists()
        except WorkspaceSecurityError:
            return False
    
    def is_file(self, relative_path: str) -> bool:
        """Check if path is a file within the workspace."""
        try:
            return self.resolve_path(relative_path).is_file()
        except WorkspaceSecurityError:
            return False
    
    def is_dir(self, relative_path: str) -> bool:
        """Check if path is a directory within the workspace."""
        try:
            return self.resolve_path(relative_path).is_dir()
        except WorkspaceSecurityError:
            return False
    
    async def read_file(self, relative_path: str) -> str:
        """
        Read a file from the workspace.
        
        Args:
            relative_path: Path relative to workspace root
        
        Returns:
            File contents as string
        
        Raises:
            WorkspaceSecurityError: If path escapes workspace
            FileNotFoundError: If file doesn't exist
            IsADirectoryError: If path is a directory
        """
        full_path = self.resolve_path(relative_path)
        
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        
        if full_path.is_dir():
            raise IsADirectoryError(f"Path is a directory: {relative_path}")
        
        # Read the file (sync I/O, but file operations are fast enough)
        return full_path.read_text(encoding="utf-8")
    
    async def write_file(self, relative_path: str, content: str) -> None:
        """
        Write content to a file in the workspace.
        
        Creates parent directories if needed.
        
        Args:
            relative_path: Path relative to workspace root
            content: Content to write
        
        Raises:
            WorkspaceSecurityError: If path escapes workspace
        """
        full_path = self.resolve_path(relative_path)
        
        # Create parent directories
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write the file
        full_path.write_text(content, encoding="utf-8")
    
    async def list_dir(self, relative_path: str = ".") -> list[str]:
        """
        List files and directories in a workspace path.
        
        Args:
            relative_path: Directory path relative to workspace root
        
        Returns:
            List of filenames/directory names
        
        Raises:
            WorkspaceSecurityError: If path escapes workspace
            NotADirectoryError: If path is not a directory
        """
        full_path = self.resolve_path(relative_path)
        
        if not full_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {relative_path}")
        
        return [item.name for item in full_path.iterdir()]
    
    def __repr__(self) -> str:
        return f"<WorkspaceManager root='{self.root}'>"
