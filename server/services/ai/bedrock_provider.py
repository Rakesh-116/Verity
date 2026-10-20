"""Amazon Bedrock implementation of Verity's basic text-generation contract."""

from __future__ import annotations

import boto3
from botocore.config import Config

from services.ai.base import AIProvider


class BedrockProvider(AIProvider):
    """Use Converse for simple server-side text generation paths."""

    def __init__(self, region: str, model_id: str, profile: str | None = None) -> None:
        session = boto3.Session(profile_name=profile, region_name=region)
        self._client = session.client(
            "bedrock-runtime",
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
        )
        self._model_id = model_id

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.converse(
            modelId=self._model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.2},
        )
        return "".join(
            block.get("text", "") for block in response["output"]["message"]["content"]
        ).strip()
