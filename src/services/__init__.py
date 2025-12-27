"""
Services package - Business logic and utilities.

Contains services like WorkspaceManager, SmartRouterClient, etc.
"""

from src.services.workspace import WorkspaceManager, WorkspaceSecurityError

__all__ = [
    "WorkspaceManager",
    "WorkspaceSecurityError",
]
