"""Obsidian Vaultのフォルダ構成を用意する(指示書6章)。

`00_Inbox` / `10_Daily` / `20_Memory/*` はPhase 1で実際に書き込む。
`30_Projects` 以降はPhase 2以降で使う拡張用の空フォルダとして先に用意しておく
(指示書31章「拡張可能性だけ保持する」)。Obsidianは空フォルダをVaultとして
開けるが、Git管理下では空フォルダを追跡できないため、Vault自体はgitignore対象
とし、コマンド実行時に毎回冪等に作成する。
"""
from __future__ import annotations

from pathlib import Path

from brain_twin.config import Config

_SYSTEM_README = """\
# 90_System

このフォルダはBrain Twin 2.0が生成した内部情報の置き場所です。
手動で編集しても壊れませんが、通常は触る必要はありません。

- SQLiteの検索indexはVaultの外(`data/index.sqlite3`)に置かれます。
  Markdown(このVault)が正本で、SQLiteはいつでも再構築できるindexです。
  壊れたり消えたりした場合は `python brain.py reindex` で再構築してください。
"""

_FOLDER_NOTES: dict[str, str] = {
    "30_Projects": "# 30_Projects\n\nプロジェクト単位のMemory(type: project)がここに置かれます。Phase 2以降で本格運用します。\n",
    "40_Knowledge": "# 40_Knowledge\n\n知識系のMemory(type: knowledge)がここに置かれます。Phase 2以降で本格運用します。\n",
    "50_People": "# 50_People\n\n人物に関するMemory(type: person)がここに置かれます。Phase 2以降で本格運用します。\n",
    "60_Goals": "# 60_Goals\n\n目標の俯瞰・まとめ用ビューを置く想定です(個々のgoal Memory自体は20_Memory/Goalsにあります)。Phase 5「Reflection」で使う想定です。\n",
    "70_Timeline": "# 70_Timeline\n\n人生・仕事・興味の変化を時系列で追うためのビューを置く想定です。Phase 5「Timeline analysis」で使う想定です。\n",
    "80_AI": "# 80_AI\n\nAIによる推論結果(type: ai_inference)がここに置かれます。事実(FACT)とは明確に区別されます(指示書5章)。Phase 4以降で本格運用します。\n",
}


def ensure_vault(config: Config) -> None:
    """Vaultの全フォルダを冪等に作成する。既に存在する場合は何もしない。"""
    config.vault_dir.mkdir(parents=True, exist_ok=True)

    for sub in ("00_Inbox", "10_Daily", "30_Projects", "40_Knowledge", "50_People", "60_Goals", "70_Timeline", "80_AI", "90_System", "Attachments"):
        (config.vault_dir / sub).mkdir(parents=True, exist_ok=True)

    for sub in ("Experiences", "Thoughts", "Decisions", "Preferences", "Goals", "Facts"):
        (config.memory_dir / sub).mkdir(parents=True, exist_ok=True)

    system_readme = config.system_dir / "README.md"
    if not system_readme.exists():
        system_readme.write_text(_SYSTEM_README, encoding="utf-8")

    for folder_name, note_text in _FOLDER_NOTES.items():
        note_path = config.vault_dir / folder_name / "README.md"
        if not note_path.exists():
            note_path.write_text(note_text, encoding="utf-8")

    config.data_dir.mkdir(parents=True, exist_ok=True)


def relative_to_vault(path: Path, config: Config) -> str:
    return str(path.resolve().relative_to(config.vault_dir.resolve())).replace("\\", "/")
