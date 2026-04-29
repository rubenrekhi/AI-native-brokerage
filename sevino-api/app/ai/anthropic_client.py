from anthropic import AsyncAnthropic
from fastapi import Request

from app.config import settings


def create_anthropic_client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


def get_anthropic(request: Request) -> AsyncAnthropic:
    return request.app.state.anthropic
