"""Groq implementation of the provider-neutral AI contract."""

from groq import Groq

from services.ai.base import AIProvider


class GroqProvider(AIProvider):
    def __init__(self, api_key: str | None, model: str) -> None:
        if not api_key:
            raise ValueError("GROQ_API_KEY is required when AI_PROVIDER=groq.")
        self._client = Groq(api_key=api_key)
        self._model = model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""
