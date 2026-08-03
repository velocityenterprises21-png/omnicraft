"""Subtitle translation with timing preserved."""
from __future__ import annotations

import json
from typing import Any

from .llm import llm
from ..utils.errors import FeatureUnavailable

LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "pl": "Polish", "ru": "Russian", "uk": "Ukrainian",
    "tr": "Turkish", "ar": "Arabic", "he": "Hebrew", "fa": "Persian", "hi": "Hindi",
    "bn": "Bengali", "ur": "Urdu", "ta": "Tamil", "te": "Telugu", "th": "Thai",
    "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay", "tl": "Filipino",
    "zh": "Chinese (Simplified)", "zh-TW": "Chinese (Traditional)", "ja": "Japanese",
    "ko": "Korean", "sv": "Swedish", "no": "Norwegian", "da": "Danish", "fi": "Finnish",
    "cs": "Czech", "sk": "Slovak", "hu": "Hungarian", "ro": "Romanian", "bg": "Bulgarian",
    "el": "Greek", "sr": "Serbian", "hr": "Croatian", "sw": "Swahili", "af": "Afrikaans",
    "am": "Amharic", "yo": "Yoruba", "zu": "Zulu", "ha": "Hausa", "pa": "Punjabi",
    "gu": "Gujarati", "mr": "Marathi", "kn": "Kannada", "ml": "Malayalam", "ne": "Nepali",
    "si": "Sinhala", "km": "Khmer", "lo": "Lao", "my": "Burmese", "mn": "Mongolian",
    "ka": "Georgian", "hy": "Armenian", "az": "Azerbaijani", "kk": "Kazakh", "uz": "Uzbek",
    "et": "Estonian", "lv": "Latvian", "lt": "Lithuanian", "sl": "Slovenian", "is": "Icelandic",
    "ga": "Irish", "cy": "Welsh", "eu": "Basque", "ca": "Catalan", "gl": "Galician",
}

BATCH_SIZE = 40


async def translate_segments(
    segments: list[dict[str, Any]], target_language: str
) -> list[dict[str, Any]]:
    if not llm.available:
        raise FeatureUnavailable(
            "Translation",
            "OPENAI_API_KEY",
            "Subtitle extraction still works without it. Only translation needs a language model.",
        )

    label = LANGUAGES.get(target_language, target_language)
    output: list[dict[str, Any]] = []

    for start in range(0, len(segments), BATCH_SIZE):
        batch = segments[start:start + BATCH_SIZE]
        numbered = json.dumps(
            [{"i": i, "t": seg["text"]} for i, seg in enumerate(batch)], ensure_ascii=False
        )
        prompt = (
            f"Translate each subtitle line into {label}. Keep the same index for each line. "
            f"Match the register of the original and keep lines short enough to read on screen.\n\n{numbered}"
        )
        result = await llm.json_complete(
            prompt,
            system="You are a subtitle translator. Return a JSON array of {\"i\": int, \"t\": string}.",
            fallback={"lines": [{"i": i, "t": s["text"]} for i, s in enumerate(batch)]},
        )
        lines = result if isinstance(result, list) else result.get("lines", [])
        mapping = {item.get("i"): item.get("t", "") for item in lines if isinstance(item, dict)}
        for i, seg in enumerate(batch):
            output.append({**seg, "text": mapping.get(i) or seg["text"]})

    return output
