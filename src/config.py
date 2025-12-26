"""
Configuration management for Deterministic Agent Execution Engine.

Uses Pydantic Settings for:
- Type-safe configuration
- Automatic environment variable loading
- Validation at startup
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings can be overridden via environment variables or .env file.
    The .env file is automatically loaded from the project root.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # DATABASE_URL == database_url
    )
    
    # ===================
    # Database Configuration
    # ===================
    database_url: str = "postgresql+asyncpg://router_user:router_password@localhost:5433/router_db"
    
    # ===================
    # Smart Model Router (Microservice)
    # ===================
    # We call this service for ALL LLM operations
    # This keeps the execution engine model-agnostic
    smart_router_url: str = "http://localhost:8000"
    smart_router_api_key: Optional[str] = None
    
    # ===================
    # Workspace Configuration  
    # ===================
    # SECURITY: All file operations are restricted to this directory
    # This prevents agents from accessing files outside the workspace
    workspace_root: str = "./workspace"
    
    # ===================
    # Server Configuration
    # ===================
    server_host: str = "0.0.0.0"
    server_port: int = 8002  # Different port from Smart Router (8000)
    
    # ===================
    # Logging
    # ===================
    log_level: str = "INFO"
    
    @property
    def workspace_path(self) -> Path:
        """
        Get workspace root as an absolute Path object.
        
        This is used by WorkspaceManager for path validation.
        """
        return Path(self.workspace_root).resolve()


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    The @lru_cache decorator ensures we only load settings ONCE.
    This is the singleton pattern - call this function anywhere
    you need settings, and you'll get the same instance.
    
    Usage:
        settings = get_settings()
        print(settings.database_url)
    """
    return Settings()
