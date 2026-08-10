"""
Ollama (ローカルLLM) とのHTTP通信。仕様書5「Ollama API連携」/13「AIが使用できない場合」対応。

設計方針:
 - Ollamaが落ちていても例外で全体を落とさない。呼び出し側(pipeline.py)が
   OllamaUnavailableError / OllamaModelMissingError を見て、processing_jobsを
   'unavailable'や'failed'へ倒せるようにする。
 - format='json' に加え、Ollama側が対応していれば厳密なJSON Schemaを渡す
   (構造化出力)。未対応バージョンでは自動的にformat='json'のみへフォールバックする。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

settings = get_settings()


class OllamaError(Exception):
    """Ollama呼び出しに関する基底例外。"""


class OllamaUnavailableError(OllamaError):
    """接続できない/タイムアウトした(一時的である可能性が高い)。"""


class OllamaModelMissingError(OllamaError):
    """指定モデルが未取得(pullが必要)。"""


@dataclass
class GenerationResult:
    raw_text: str
    model: str
    total_duration_ns: int | None = None


class OllamaClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                timeout or settings.ollama_request_timeout_seconds,
                connect=settings.ollama_connect_timeout_seconds,
            ),
        )

    async def check_health(self) -> bool:
        try:
            async with self._client(timeout=settings.ollama_connect_timeout_seconds) as client:
                resp = await client.get("/api/version")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
            return False

    async def list_models(self) -> list[str]:
        try:
            async with self._client(timeout=settings.ollama_connect_timeout_seconds) as client:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m.get("name", "") for m in data.get("models", [])]
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
            raise OllamaUnavailableError(f"Ollama ({self.base_url}) に接続できませんでした")

    async def is_model_ready(self, model_name: str | None = None) -> bool:
        target = model_name or settings.ollama_model
        models = await self.list_models()
        # タグ(:latest等)の有無を許容して緩めに一致を見る
        return any(m == target or m.startswith(target.split(":")[0] + ":") for m in models)

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> GenerationResult:
        """
        /api/chat を format='json' (可能ならJSON Schema付き) で呼び出す。
        Ollama未起動・タイムアウト・モデル未取得はここで判別し、専用の例外にして返す。
        """
        target_model = model or settings.ollama_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.2},
        }
        # Ollamaが対応していればJSON Schemaで出力を拘束する(未対応バージョンではエラーになりうるため、
        # 失敗したらformat='json'のみで再試行する)。
        payload["format"] = json_schema if json_schema else "json"

        try:
            async with self._client() as client:
                resp = await client.post("/api/chat", json=payload)
        except httpx.ConnectError as e:
            raise OllamaUnavailableError(f"Ollamaに接続できませんでした: {e}") from e
        except httpx.TimeoutException as e:
            raise OllamaUnavailableError(f"Ollamaへのリクエストがタイムアウトしました: {e}") from e

        if resp.status_code == 404:
            # モデル未取得の可能性が高い
            raise OllamaModelMissingError(f"モデル '{target_model}' が見つかりません。`ollama pull {target_model}` が必要です")

        if resp.status_code >= 500 and json_schema is not None:
            # JSON Schema指定が原因で失敗した可能性 -> format='json'のみで再試行
            payload["format"] = "json"
            try:
                async with self._client() as client:
                    resp = await client.post("/api/chat", json=payload)
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                raise OllamaUnavailableError(str(e)) from e

        if resp.status_code != 200:
            body = resp.text[:500]
            if "model" in body.lower() and ("not found" in body.lower() or "pull" in body.lower()):
                raise OllamaModelMissingError(f"モデル '{target_model}' が利用できません: {body}")
            raise OllamaError(f"Ollamaがエラーを返しました (status={resp.status_code}): {body}")

        data = resp.json()
        content = (data.get("message") or {}).get("content", "")
        return GenerationResult(raw_text=content, model=target_model, total_duration_ns=data.get("total_duration"))

    async def generate_embedding(self, text: str, model: str | None = None) -> list[float] | None:
        """意味検索/類似度計算用の埋め込み。失敗時はNoneを返し呼び出し側でスキップさせる
        (=埋め込みが取れなくても全文検索等の他の検索手段は機能し続ける)。

        注意: Ollamaの `/api/embeddings` (prompt引数, 単数embedding返却) は非推奨であり、
        タイムアウトや空配列を返すなど不安定な挙動が報告されている。現行の `/api/embed`
        (input引数, embeddings配列を返却。単一文字列を渡してもembeddings[0]に1件入る)を使う。
        """
        target_model = model or settings.ollama_embedding_model
        try:
            async with self._client() as client:
                resp = await client.post("/api/embed", json={"model": target_model, "input": text})
                if resp.status_code != 200:
                    return None
                data = resp.json()
                embeddings = data.get("embeddings")
                if isinstance(embeddings, list) and len(embeddings) > 0 and isinstance(embeddings[0], list):
                    return embeddings[0]
                return None
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError):
            return None

    async def generate_embeddings_batch(self, texts: list[str], model: str | None = None) -> list[list[float] | None]:
        """複数件をまとめて埋め込む(/api/embedはinputに配列を渡せるため、N回のHTTP呼び出しを1回にできる)。
        一部だけ失敗しても例外にせず、該当位置をNoneにして返す。"""
        if not texts:
            return []
        target_model = model or settings.ollama_embedding_model
        try:
            async with self._client() as client:
                resp = await client.post("/api/embed", json={"model": target_model, "input": texts})
                if resp.status_code != 200:
                    return [None] * len(texts)
                data = resp.json()
                embeddings = data.get("embeddings")
                if isinstance(embeddings, list) and len(embeddings) == len(texts):
                    return embeddings
                return [None] * len(texts)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError):
            return [None] * len(texts)
