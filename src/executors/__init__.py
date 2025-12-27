"""
Executors package - Step execution implementations.

Each executor handles one type of step (read_file, analyze, etc.)
All executors inherit from BaseExecutor and return StepResult.
"""

from src.executors.base import BaseExecutor, StepResult
from src.executors.read_file import ReadFileExecutor
from src.executors.analyze import AnalyzeExecutor
from src.executors.edit_file import EditFileExecutor
from src.executors.run_command import RunCommandExecutor
from src.executors.summarize import SummarizeExecutor

__all__ = [
    "BaseExecutor",
    "StepResult",
    "ReadFileExecutor",
    "AnalyzeExecutor",
    "EditFileExecutor",
    "RunCommandExecutor",
    "SummarizeExecutor",
]
