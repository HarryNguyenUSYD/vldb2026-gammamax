"""LLM semantic abstraction, following ZeroEC's OpenAI-compatible client pattern."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SEMANTIC_TYPES = (
    "address", "age", "city", "company", "continent", "country", "currency",
    "date", "description", "duration", "email", "gender", "language", "name",
    "nationality", "occupation", "organization", "phone", "state", "year",
)


@dataclass(frozen=True)
class SemanticSpan:
    semantic_type: str
    original: str
    replacement: str
    marker: str


@dataclass(frozen=True)
class AbstractedValue:
    original: str
    annotated: str
    abstracted: str
    spans: tuple[SemanticSpan, ...]


class SemanticAbstractionError(RuntimeError):
    pass


class SemanticAbstractor:
    def __init__(self, model: str | None = None, cache_path: Path | None = None,
                 enabled: bool = True) -> None:
        self.enabled = enabled
        self.model = model or os.getenv("DATAVINCI_MODEL", "gpt-3.5-turbo-0125")
        self.api_base = os.getenv("OPENAI_API_BASE")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.max_attempts = max(1, int(os.getenv("DATAVINCI_OPENAI_MAX_ATTEMPTS", "3")))
        self.max_requests = max(1, int(os.getenv("DATAVINCI_OPENAI_MAX_REQUESTS", "2000")))
        self.interval = max(0.0, float(os.getenv("DATAVINCI_OPENAI_MIN_REQUEST_INTERVAL_SECONDS", "2")))
        self.retry_base = max(0.1, float(os.getenv("DATAVINCI_OPENAI_RETRY_BASE_SECONDS", "2")))
        self.cache_path = cache_path
        self._cache = self._load_cache()
        self._lock = threading.Lock()
        self._next_request = 0.0
        self._requests = 0
        self.call_count = 0

    def abstract_column(self, values: list[str], token_budget: int = 3500) -> list[AbstractedValue]:
        if not self.enabled:
            return [AbstractedValue(value, value, value, ()) for value in values]
        if not self.api_key:
            raise SemanticAbstractionError("OPENAI_API_KEY environment variable is not configured")
        result: list[AbstractedValue] = []
        batch: list[str] = []
        used = 0
        for value in values:
            tokens = self._token_count(value) + 8
            if batch and used + tokens > token_budget:
                result.extend(self._abstract_batch(batch)); batch = []; used = 0
            batch.append(value); used += tokens
        if batch:
            result.extend(self._abstract_batch(batch))
        return result

    def _token_count(self, value: str) -> int:
        try:
            import tiktoken
            return len(tiktoken.encoding_for_model(self.model).encode(value))
        except Exception:
            return max(1, (len(value) + 3) // 4)

    def _abstract_batch(self, values: list[str]) -> list[AbstractedValue]:
        cache_key = hashlib.sha256(json.dumps([self.model, values], ensure_ascii=False).encode()).hexdigest()
        if cache_key in self._cache:
            return self._parse(values, self._cache[cache_key])
        prompt_path = Path(__file__).resolve().parent / "prompt_templates" / "semantic_abstraction.txt"
        system_prompt = prompt_path.read_text(encoding="utf-8")
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI
        except ImportError as error:
            raise SemanticAbstractionError("install langchain-openai and langchain-core") from error
        client = ChatOpenAI(model_name=self.model, openai_api_base=self.api_base,
                            openai_api_key=self.api_key, temperature=0, max_retries=0)
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=json.dumps({
            "semantic_types": SEMANTIC_TYPES, "values": values,
        }, ensure_ascii=False))]
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            self._wait_for_slot()
            try:
                response = client.invoke(messages)
                payload = self._decode(response.content)
                parsed = self._parse(values, payload)
                self._cache[cache_key] = payload
                self._save_cache()
                self.call_count += 1
                return parsed
            except Exception as error:
                last_error = error
                if attempt + 1 < self.max_attempts:
                    time.sleep(min(self.retry_base * (2 ** attempt), 60) + random.random())
        raise SemanticAbstractionError(f"semantic abstraction failed after {self.max_attempts} attempts") from last_error

    def _wait_for_slot(self) -> None:
        with self._lock:
            if self._requests >= self.max_requests:
                raise SemanticAbstractionError(f"OpenAI request cap reached ({self.max_requests})")
            now = time.monotonic()
            scheduled = max(now, self._next_request)
            self._next_request = scheduled + self.interval
            self._requests += 1
        if scheduled > now:
            time.sleep(scheduled - now)

    @staticmethod
    def _decode(content: str) -> Any:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        return json.loads(cleaned)

    @staticmethod
    def _parse(values: list[str], payload: Any) -> list[AbstractedValue]:
        items = payload.get("values") if isinstance(payload, dict) else None
        if not isinstance(items, list) or len(items) != len(values):
            raise ValueError("LLM response must contain one values item per input")
        output = []
        for original, item in zip(values, items):
            if not isinstance(item, dict) or not isinstance(item.get("spans", []), list):
                raise ValueError("each LLM values item requires spans array")
            spans: list[SemanticSpan] = []
            annotated_parts: list[str] = []
            abstracted_parts: list[str] = []
            cursor = 0
            for raw_span in sorted(item.get("spans", []), key=lambda span: span.get("start", -1)):
                if not isinstance(raw_span, dict):
                    raise ValueError("semantic span must be an object")
                start, end = raw_span.get("start"), raw_span.get("end")
                semantic_type = raw_span.get("type")
                replacement = raw_span.get("replacement")
                supplied_original = raw_span.get("original")
                if not isinstance(start, int) or not isinstance(end, int) or not cursor <= start < end <= len(original):
                    raise ValueError("semantic span offsets are invalid or overlapping")
                if not isinstance(semantic_type, str) or not isinstance(replacement, str):
                    raise ValueError("semantic span requires type and replacement strings")
                if semantic_type not in SEMANTIC_TYPES:
                    raise ValueError(f"unsupported semantic type: {semantic_type}")
                source_substring = original[start:end]
                if supplied_original != source_substring:
                    raise ValueError("semantic span original does not match input offsets")
                marker = chr(0xE000 + SEMANTIC_TYPES.index(semantic_type))
                annotated_parts.extend((original[cursor:start], f"{{{semantic_type}({replacement})}}"))
                abstracted_parts.extend((original[cursor:start], marker))
                spans.append(SemanticSpan(semantic_type, source_substring, replacement, marker))
                cursor = end
            annotated_parts.append(original[cursor:]); abstracted_parts.append(original[cursor:])
            annotated = "".join(annotated_parts)
            abstracted = "".join(abstracted_parts)
            output.append(AbstractedValue(original, annotated, abstracted, tuple(spans)))
        return output

    def _load_cache(self) -> dict[str, Any]:
        if self.cache_path and self.cache_path.is_file():
            try: return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): return {}
        return {}

    def _save_cache(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
