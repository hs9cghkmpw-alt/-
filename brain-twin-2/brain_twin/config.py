"""設定。Vault/DBの場所を一箇所に集約する。

環境変数で上書き可能:
  BRAIN_TWIN_VAULT_DIR — Obsidian Vaultのルート (既定: <project>/vault)
  BRAIN_TWIN_DATA_DIR  — SQLite index等の置き場所 (既定: <project>/data)

Markdown(Vault)が正本、SQLiteはあくまでindex/cache という設計原則(指示書25)
のため、この2つは意図的に別ディレクトリに分離している。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    project_root: Path
    vault_dir: Path
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "index.sqlite3"

    # --- Vault内の主要ディレクトリ(指示書 6章のVault構成) ---
    @property
    def inbox_dir(self) -> Path:
        return self.vault_dir / "00_Inbox"

    @property
    def daily_dir(self) -> Path:
        return self.vault_dir / "10_Daily"

    @property
    def memory_dir(self) -> Path:
        return self.vault_dir / "20_Memory"

    @property
    def projects_dir(self) -> Path:
        return self.vault_dir / "30_Projects"

    @property
    def knowledge_dir(self) -> Path:
        return self.vault_dir / "40_Knowledge"

    @property
    def people_dir(self) -> Path:
        return self.vault_dir / "50_People"

    @property
    def goals_dir(self) -> Path:
        return self.vault_dir / "60_Goals"

    @property
    def timeline_dir(self) -> Path:
        return self.vault_dir / "70_Timeline"

    @property
    def ai_dir(self) -> Path:
        return self.vault_dir / "80_AI"

    @property
    def system_dir(self) -> Path:
        return self.vault_dir / "90_System"

    @property
    def attachments_dir(self) -> Path:
        return self.vault_dir / "Attachments"


def load_config() -> Config:
    vault_dir = Path(os.environ.get("BRAIN_TWIN_VAULT_DIR", str(_PROJECT_ROOT / "vault"))).resolve()
    data_dir = Path(os.environ.get("BRAIN_TWIN_DATA_DIR", str(_PROJECT_ROOT / "data"))).resolve()
    return Config(project_root=_PROJECT_ROOT, vault_dir=vault_dir, data_dir=data_dir)
