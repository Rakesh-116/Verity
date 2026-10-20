"""OpenAI implementation of the provider-neutral AI contract."""

from openai import OpenAI

from services.ai.base import AIProvider


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str | None, model: str) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER=openai.")
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.responses.create(
            model=self._model, instructions=system_prompt, input=user_prompt
        )
        return response.output_text
