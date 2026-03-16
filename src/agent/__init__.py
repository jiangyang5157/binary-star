"""
Agent Module:
Contains the 'Brains' of the system. 
- TraderAgent (Agent A): Real-time analysis and decision making (Multimodal).
- ReviewerAgent (Agent B): Retrospective performance optimization (Config/Prompt Tuning).
"""
from .trader_agent import TraderAgent
from .reviewer_agent import ReviewerAgent

__all__ = ["TraderAgent", "ReviewerAgent"]
