"""
Executors package - Step execution implementations.

Each executor handles one type of step (read_file, analyze, etc.)
All executors inherit from BaseExecutor and return StepResult.
"""

from src.executors.base import BaseExecutor, StepResult
from src.executors.read_file import ReadFileExecutor

__all__ = [
    "BaseExecutor",
    "StepResult",
    "ReadFileExecutor",
]
