"""Configuration for the optional local AI provider layer."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIRECTORY = Path(__file__).resolve().parents[3]
# Local developer convenience only. Existing shell variables take precedence,
# which keeps deployment configuration explicit.
load_dotenv(PROJECT_DIRECTORY / ".env", override=False)


@dataclass(frozen=True)
class AISettings:
    provider: str
    openai_api_key: str | None
    openai_model: str
    groq_api_key: str | None
    groq_model: str
    aws_region: str
    aws_profile: str | None
    bedrock_model_id: str

    @classmethod
    def from_environment(cls) -> "AISettings":
        return cls(
            provider=os.getenv("AI_PROVIDER", "groq").strip().lower(),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5"),
            groq_api_key=os.getenv("GROQ_API_KEY"),
            groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
            aws_region=os.getenv("AWS_REGION", "ap-southeast-2"),
            aws_profile=os.getenv("AWS_PROFILE") or None,
            bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", "global.amazon.nova-2-lite-v1:0"),
        )
