"""Environment-backed settings for the DeepAgents query application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    model: str = "openai:qwen-plus"
    api_key: str | None = None
    base_url: str | None = None


def get_settings() -> Settings:
    return Settings(
        model=os.getenv("DEEPAGENTS_MODEL", "openai:qwen-plus"),
        api_key=os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv(
            "OPENAI_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    )
