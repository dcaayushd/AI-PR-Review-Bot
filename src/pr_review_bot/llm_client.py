from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

try:
    from openai import APIConnectionError, APIStatusError, APITimeoutError, LengthFinishReasonError, OpenAI, RateLimitError
except ModuleNotFoundError:  # pragma: no cover - makes lightweight unit tests import-safe without the SDK installed.
    APIConnectionError = APIStatusError = APITimeoutError = LengthFinishReasonError = RateLimitError = Exception  # type: ignore[assignment]
    OpenAI = None  # type: ignore[assignment]

from .config import ReviewSettings
from .domain import DiffChunk, PullRequestContext, RepositorySnippet
from .llm_schemas import ChunkReviewResponseModel
from .prompts import SYSTEM_PROMPT, build_user_prompt

LOGGER = logging.getLogger(__name__)
UNSUPPORTED_PARAM_RE = re.compile(r"Unsupported parameter: '([^']+)'")


class LLMReviewError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OutputProfile:
    name: str
    max_findings: int
    max_inline_comments: int
    compact_mode: bool = False


class LLMClient:
    def __init__(self, settings: ReviewSettings) -> None:
        self._settings = settings
        self._provider = settings.provider
        api_key = self._resolve_api_key()
        if not api_key:
            if self._provider == "gemini":
                raise LLMReviewError("GOOGLE_API_KEY is required to run Gemini review.")
            raise LLMReviewError("OPENAI_API_KEY is required to run AI review.")
        if OpenAI is None:
            raise LLMReviewError("The openai package is not installed in this Python environment.")
        if self._provider == "gemini":
            self._client = OpenAI(
                api_key=api_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                timeout=90.0,
                max_retries=0,
            )
        else:
            self._client = OpenAI(api_key=api_key, timeout=90.0, max_retries=0)
        self._unsupported_params_by_model: dict[str, set[str]] = {}

    def _resolve_api_key(self) -> str:
        if self._provider == "gemini":
            return os.getenv("GOOGLE_API_KEY", "").strip()
        return os.getenv("OPENAI_API_KEY", "").strip()

    def review_chunk(
        self,
        pr_context: PullRequestContext,
        chunk: DiffChunk,
        repository_snippets: list[RepositorySnippet],
    ) -> tuple[ChunkReviewResponseModel, str]:
        models = [self._settings.model]
        if self._settings.fallback_model and self._settings.fallback_model != self._settings.model:
            models.append(self._settings.fallback_model)

        last_error: Exception | None = None
        for model in models:
            for profile in self._output_profiles():
                prompt = build_user_prompt(
                    pr_context,
                    chunk,
                    repository_snippets,
                    max_findings=profile.max_findings,
                    max_inline_comments=profile.max_inline_comments,
                    compact_mode=profile.compact_mode,
                )
                for attempt in range(1, self._settings.retry_attempts + 1):
                    try:
                        LOGGER.info(
                            "Reviewing chunk %s with provider %s model %s profile %s (attempt %s).",
                            chunk.chunk_id,
                            self._provider,
                            model,
                            profile.name,
                            attempt,
                        )
                        parsed = self._structured_request(model=model, prompt=prompt)
                        return parsed, model
                    except LengthFinishReasonError as exc:
                        last_error = exc
                        LOGGER.warning(
                            "Model %s hit a length limit for chunk %s using profile %s.",
                            model,
                            chunk.chunk_id,
                            profile.name,
                        )
                        break
                    except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
                        last_error = exc
                        self._sleep_backoff(attempt, "transient OpenAI error")
                    except (APIStatusError, ValueError, json.JSONDecodeError) as exc:
                        last_error = exc
                        if self._is_length_error(exc):
                            LOGGER.warning(
                                "Model %s hit a parse or length limit for chunk %s using profile %s.",
                                model,
                                chunk.chunk_id,
                                profile.name,
                            )
                            break
                        status_code = getattr(exc, "status_code", None)
                        if isinstance(exc, APIStatusError) and status_code and 500 <= status_code < 600:
                            self._sleep_backoff(attempt, f"OpenAI server error {status_code}")
                            continue
                        break
                if last_error is not None and self._is_length_error(last_error):
                    continue
                if last_error is not None:
                    break
        raise LLMReviewError(f"Unable to review diff chunk {chunk.chunk_id}: {last_error}") from last_error

    def _output_profiles(self) -> list[OutputProfile]:
        normal_findings = min(self._settings.max_issues, 8)
        normal_inline = min(self._settings.max_inline_comments, 4)
        compact_findings = min(self._settings.max_issues, 4)
        compact_inline = min(self._settings.max_inline_comments, 2)
        profiles = [OutputProfile(name="default", max_findings=normal_findings, max_inline_comments=normal_inline)]
        if compact_findings < normal_findings or compact_inline < normal_inline:
            profiles.append(
                OutputProfile(
                    name="compact",
                    max_findings=compact_findings,
                    max_inline_comments=compact_inline,
                    compact_mode=True,
                    )
                )
        return profiles

    def _structured_request(self, *, model: str, prompt: str) -> ChunkReviewResponseModel:
        if self._provider == "gemini":
            return self._structured_request_gemini(model=model, prompt=prompt)
        return self._structured_request_openai(model=model, prompt=prompt)

    def _structured_request_openai(self, *, model: str, prompt: str) -> ChunkReviewResponseModel:
        unsupported = self._unsupported_params_by_model.setdefault(model, set())
        parse_method = getattr(self._client.responses, "parse", None)
        while True:
            try:
                if callable(parse_method):
                    response = parse_method(**self._build_parse_kwargs(model=model, prompt=prompt, unsupported=unsupported))
                    parsed = getattr(response, "output_parsed", None)
                    if parsed is None:
                        output_text = getattr(response, "output_text", "")
                        if not output_text:
                            raise ValueError("OpenAI response did not include structured output.")
                        return ChunkReviewResponseModel.model_validate_json(output_text)
                    return parsed

                response = self._client.responses.create(
                    **self._build_create_kwargs(model=model, prompt=prompt, unsupported=unsupported)
                )
                output_text = getattr(response, "output_text", "")
                if not output_text:
                    raise ValueError("OpenAI response did not include output_text.")
                return ChunkReviewResponseModel.model_validate_json(output_text)
            except APIStatusError as exc:
                unsupported_param = self._extract_unsupported_param(exc)
                if unsupported_param and unsupported_param not in unsupported:
                    unsupported.add(unsupported_param)
                    LOGGER.warning(
                        "Model %s does not support %s; retrying without that parameter.",
                        model,
                        unsupported_param,
                    )
                    continue
                raise

    def _structured_request_gemini(self, *, model: str, prompt: str) -> ChunkReviewResponseModel:
        unsupported = self._unsupported_params_by_model.setdefault(model, set())
        parse_method = getattr(getattr(self._client, "beta", None), "chat", None)
        completions = getattr(parse_method, "completions", None)
        parse_call = getattr(completions, "parse", None)
        if not callable(parse_call):
            raise LLMReviewError("Installed openai SDK does not support beta.chat.completions.parse for Gemini.")

        while True:
            try:
                response = parse_call(**self._build_gemini_parse_kwargs(model=model, prompt=prompt, unsupported=unsupported))
                choice = response.choices[0].message
                parsed = getattr(choice, "parsed", None)
                if parsed is None:
                    content = getattr(choice, "content", None)
                    if not content:
                        raise ValueError("Gemini response did not include structured output.")
                    if isinstance(content, str):
                        return ChunkReviewResponseModel.model_validate_json(content)
                    raise ValueError("Gemini response returned an unexpected structured output shape.")
                return parsed
            except APIStatusError as exc:
                unsupported_param = self._extract_unsupported_param(exc)
                if unsupported_param and unsupported_param not in unsupported:
                    unsupported.add(unsupported_param)
                    LOGGER.warning(
                        "Provider %s model %s does not support %s; retrying without that parameter.",
                        self._provider,
                        model,
                        unsupported_param,
                    )
                    continue
                raise

    def _build_parse_kwargs(self, *, model: str, prompt: str, unsupported: set[str]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": SYSTEM_PROMPT,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "max_output_tokens": self._settings.max_output_tokens,
            "text_format": ChunkReviewResponseModel,
        }
        if "reasoning" not in unsupported:
            kwargs["reasoning"] = {"effort": self._settings.reasoning_effort}
        if "temperature" not in unsupported:
            kwargs["temperature"] = self._settings.temperature
        return kwargs

    def _build_create_kwargs(self, *, model: str, prompt: str, unsupported: set[str]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": SYSTEM_PROMPT,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "max_output_tokens": self._settings.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "chunk_review",
                    "strict": True,
                    "schema": ChunkReviewResponseModel.model_json_schema(),
                }
            },
        }
        if "reasoning" not in unsupported:
            kwargs["reasoning"] = {"effort": self._settings.reasoning_effort}
        if "temperature" not in unsupported:
            kwargs["temperature"] = self._settings.temperature
        return kwargs

    def _build_gemini_parse_kwargs(self, *, model: str, prompt: str, unsupported: set[str]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": ChunkReviewResponseModel,
        }
        if "reasoning_effort" not in unsupported:
            kwargs["reasoning_effort"] = self._settings.reasoning_effort
        if "max_tokens" not in unsupported:
            kwargs["max_tokens"] = self._settings.max_output_tokens
        if "temperature" not in unsupported:
            kwargs["temperature"] = self._settings.temperature
        return kwargs

    @staticmethod
    def _extract_unsupported_param(exc: APIStatusError) -> str | None:
        message = str(exc)
        match = UNSUPPORTED_PARAM_RE.search(message)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _is_length_error(exc: Exception) -> bool:
        if isinstance(exc, LengthFinishReasonError):
            return True
        return "length limit" in str(exc).lower()

    @staticmethod
    def _sleep_backoff(attempt: int, reason: str) -> None:
        delay = min(2 ** (attempt - 1), 8)
        LOGGER.warning("%s. Retrying in %ss.", reason, delay)
        time.sleep(delay)
