"""Single entry point for all optional local AI providers."""

from services.ai.base import AIProvider
from services.ai.bedrock_provider import BedrockProvider
from services.ai.groq_provider import GroqProvider
from services.ai.openai_provider import OpenAIProvider
from services.ai.settings import AISettings


class AIOrchestrator:
    """Selects one configured provider behind a stable interface."""

    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider

    @classmethod
    def from_environment(cls) -> "AIOrchestrator":
        settings = AISettings.from_environment()
        if settings.provider == "openai":
            return cls(OpenAIProvider(settings.openai_api_key, settings.openai_model))
        if settings.provider == "groq":
            return cls(GroqProvider(settings.groq_api_key, settings.groq_model))
        if settings.provider == "bedrock":
            return cls(
                BedrockProvider(
                    region=settings.aws_region,
                    model_id=settings.bedrock_model_id,
                    profile=settings.aws_profile,
                )
            )
        raise ValueError("AI_PROVIDER must be 'openai', 'groq', or 'bedrock'.")

    def respond(self, system_prompt: str, user_prompt: str) -> str:
        return self._provider.generate(system_prompt, user_prompt)
