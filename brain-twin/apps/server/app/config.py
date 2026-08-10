"""
環境変数から設定を読み込む。すべて .env / .env.example と対応させること。
ここに書かれたデフォルト値は「ローカルPCでDocker Composeを使う」前提の安全側の値。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.paths import packages_dir as _resolve_packages_dir


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 基本 ---
    app_name: str = "Brain Twin"
    environment: str = "local"  # local | production だが常にTailscale内部利用が前提
    log_level: str = "INFO"
    packages_dir: Path = Path(_resolve_packages_dir())

    # --- データ保存先 ---
    # docker-compose.yml で /app/data にバインドマウントされる想定。
    data_dir: Path = Path("/app/data")
    database_path: Optional[Path] = None  # Noneならdata_dir/database/brain_twin.sqlite3
    backups_dir: Optional[Path] = None  # Noneならdata_dir/backups
    exports_dir: Optional[Path] = None  # Noneならdata_dir/exports

    # --- Ollama ---
    ollama_base_url: str = "http://ollama:11434"  # Docker Compose内サービス名。ホストOllama利用時は http://host.docker.internal:11434
    ollama_model: str = "qwen2.5:7b-instruct"
    # 生成モデルとは別の専用埋め込みモデル(仕様追加指示: 埋め込みモデルを生成モデルから分離)。
    # bge-m3は日本語を含む100+言語の意味検索に強く、MITライセンスでOllamaから軽量に導入できる。
    ollama_embedding_model: str = "bge-m3"
    ollama_request_timeout_seconds: float = 60.0
    ollama_connect_timeout_seconds: float = 3.0
    ollama_max_retries: int = 2

    # --- 認証 ---
    # ペアリングコードの有効期限(秒)。
    pairing_code_ttl_seconds: int = 600
    # 端末トークンの長さ(バイト数、hex化されるので文字列は2倍の長さになる)。
    device_token_bytes: int = 32
    # レート制限 (簡易実装。1端末あたり1分間の許容リクエスト数)
    rate_limit_per_minute: int = 120

    # --- CORS ---
    # Tailscale内部からのみアクセスされる前提だが、iPhone SafariのPWAからの
    # クロスオリジン(サービスワーカー経由等)を考慮し、許可originを明示指定する。
    allowed_origins_raw: str = ""  # カンマ区切り。空なら同一オリジンのみ。

    # --- バックアップ ---
    backup_retention_generations: int = 7
    backup_schedule_hour: int = 3  # 毎日この時刻(ローカル時刻, 24h)に自動バックアップ

    # --- ジョブワーカー ---
    job_poll_interval_seconds: float = 2.0
    job_max_attempts: int = 5

    @property
    def resolved_database_path(self) -> Path:
        return self.database_path or (self.data_dir / "database" / "brain_twin.sqlite3")

    @property
    def resolved_backups_dir(self) -> Path:
        return self.backups_dir or (self.data_dir / "backups")

    @property
    def resolved_exports_dir(self) -> Path:
        return self.exports_dir or (self.data_dir / "exports")

    @property
    def allowed_origins(self) -> list[str]:
        if not self.allowed_origins_raw.strip():
            return []
        return [o.strip() for o in self.allowed_origins_raw.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.resolved_database_path}"

    @property
    def sync_database_url(self) -> str:
        """Alembic (同期エンジン) 用。"""
        return f"sqlite:///{self.resolved_database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
