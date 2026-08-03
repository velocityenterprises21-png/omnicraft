"""Thin LLM wrapper. Falls back to a local extractive engine when no key is set."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from ..config import settings

log = logging.getLogger("omnicraft.llm")


class LLMClient:
    """Prefers OpenAI, then Anthropic, then a deterministic offline summariser."""

    def __init__(self) -> None:
        self.openai_key = settings.OPENAI_API_KEY
        self.anthropic_key = settings.ANTHROPIC_API_KEY

    @property
    def available(self) -> bool:
        return bool(self.openai_key or self.anthropic_key)

    @property
    def provider(self) -> str:
        if self.openai_key:
            return "openai"
        if self.anthropic_key:
            return "anthropic"
        return "offline"

    async def complete(
        self,
        prompt: str,
        system: str = "You are a precise media production assistant.",
        max_tokens: int = 1200,
        temperature: float = 0.4,
    ) -> str:
        if self.openai_key:
            return await self._openai(prompt, system, max_tokens, temperature)
        if self.anthropic_key:
            return await self._anthropic(prompt, system, max_tokens, temperature)
        return offline_summarise(prompt)

    async def json_complete(self, prompt: str, system: str, fallback: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            return fallback
        raw = await self.complete(
            prompt + "\n\nRespond with JSON only. No prose, no code fences.",
            system=system,
            temperature=0.1,
        )
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("Model returned non-JSON output; using fallback plan.")
            return fallback

    async def _openai(self, prompt: str, system: str, max_tokens: int, temperature: float) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.openai_key}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()

    async def _anthropic(self, prompt: str, system: str, max_tokens: int, temperature: float) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            blocks = resp.json().get("content", [])
            return "".join(b.get("text", "") for b in blocks).strip()


_STOPWORDS = set("""a an the and or but if while of to in on for with without as at by from is are was were be been
being this that these those it its into over under about after before then than so such can could will would may might
you your we our they their he she his her i me my""".split())


def offline_summarise(text: str, sentences: int = 5) -> str:
    """Frequency-scored extractive summary. Runs with zero API keys."""
    body = re.sub(r"\s+", " ", text).strip()
    if not body:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", body)
    if len(parts) <= sentences:
        return body
    words = [w.lower().strip(".,!?;:\"'()[]") for w in body.split()]
    freq: dict[str, int] = {}
    for w in words:
        if w and w not in _STOPWORDS and len(w) > 2:
            freq[w] = freq.get(w, 0) + 1
    scored = []
    for idx, sentence in enumerate(parts):
        tokens = [w.lower().strip(".,!?;:\"'()[]") for w in sentence.split()]
        if not tokens:
            continue
        score = sum(freq.get(t, 0) for t in tokens) / (len(tokens) ** 0.5)
        scored.append((score, idx, sentence))
    scored.sort(reverse=True)
    picked = sorted(scored[:sentences], key=lambda x: x[1])
    return " ".join(s for _, _, s in picked)


def offline_bullets(text: str, count: int = 7) -> list[str]:
    summary = offline_summarise(text, sentences=count)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary) if s.strip()]


llm = LLMClient()
