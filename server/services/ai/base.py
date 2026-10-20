"""Provider-neutral contract for text generation."""

from abc import ABC, abstractmethod


class AIProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Return a text response without exposing provider SDK details."""
