from __future__ import annotations

import json
import urllib.request


class LocalModelError(RuntimeError):
    pass


class LocalModelClient:
    """Client for a llama.cpp server running only on localhost."""

    def __init__(self, endpoint: str = "http://127.0.0.1:8080"):
        self.endpoint = endpoint.rstrip("/")
        if not self.endpoint.startswith(("http://127.0.0.1", "http://localhost")):
            raise ValueError("Разрешен только локальный адрес модели")

    def review(self, text: str, standard_excerpts: list[str]) -> str:
        context = "\n\n".join(standard_excerpts[:8])
        prompt = (
            "Проверь фрагмент технического документа по приведенным требованиям. "
            "Не выдумывай требования. Верни краткий JSON с полями issue, suggestion, "
            "reason и confidence. /no_think\n\n"
            f"ТРЕБОВАНИЯ:\n{context}\n\nФРАГМЕНТ:\n{text}"
        )
        payload = json.dumps(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты локальный помощник нормоконтролера.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 350,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result = json.load(response)
        except Exception as exc:
            raise LocalModelError(f"Локальная модель недоступна: {exc}") from exc
        return result["choices"][0]["message"]["content"]

