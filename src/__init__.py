"""Singularity — AI-driven crypto quantitative trading engine."""

from src.utils.pipeline_utils import get_project_version, get_git_commit

__version__ = get_project_version()
__git_commit__ = get_git_commit()
