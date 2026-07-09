"""Gemini distillation for live lg runs."""

from __future__ import annotations

import os
import time
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

load_dotenv()

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        key = os.environ.get("GOOGLE_API_KEY", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("GOOGLE_API_KEY not set in environment")
        _client = genai.Client(api_key=key)
        logger.debug("Initialized google-genai client")
    return _client


def _is_rate_limit(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "resource exhausted" in msg or "rate" in msg


def _extract_tokens(response: types.GenerateContentResponse) -> dict[str, int | None]:
    usage = response.usage_metadata
    if usage is None:
        return {"prompt_tokens": None, "candidates_tokens": None, "total_tokens": None}
    return {
        "prompt_tokens": usage.prompt_token_count,
        "candidates_tokens": usage.candidates_token_count,
        "total_tokens": usage.total_token_count,
    }


def distill_with_retries(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_retries: int = 3,
) -> tuple[str, dict[str, int | None], float]:
    last_error: Exception | None = None

    @retry(
        retry=retry_if_exception(_is_rate_limit),
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        reraise=True,
    )
    def _call() -> tuple[str, dict[str, int | None], float]:
        nonlocal last_error
        client = _get_client()
        t0 = time.perf_counter()
        try:
            response = client.models.generate_content(
                model=model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=temperature,
                ),
            )
        except Exception as exc:
            last_error = exc
            raise
        elapsed_ms = (time.perf_counter() - t0) * 1000
        text = response.text or ""
        if not text.strip():
            raise ValueError("Empty distill response")
        return text, _extract_tokens(response), elapsed_ms

    try:
        return _call()
    except Exception as exc:
        raise RuntimeError(f"Distill failed after {max_retries} retries") from (last_error or exc)
