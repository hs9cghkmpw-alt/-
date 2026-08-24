from pathlib import Path

import pytest

from brain_twin import vault


def test_write_text_atomic_creates_file_with_content(tmp_path: Path):
    path = tmp_path / "a.md"
    vault.write_text_atomic(path, "hello")
    assert path.read_text(encoding="utf-8") == "hello"


def test_write_text_atomic_overwrites_existing_file(tmp_path: Path):
    path = tmp_path / "a.md"
    path.write_text("old", encoding="utf-8")
    vault.write_text_atomic(path, "new")
    assert path.read_text(encoding="utf-8") == "new"


def test_write_text_atomic_leaves_no_leftover_tmp_file_on_success(tmp_path: Path):
    path = tmp_path / "a.md"
    vault.write_text_atomic(path, "hello")
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_write_text_atomic_cleans_up_tmp_file_on_failure(tmp_path: Path, monkeypatch):
    """一時ファイルへの書き込み自体が失敗した場合でも、`*.tmp` がVaultに残り続けない
    こと(残骸が残ると、次回の書き込みで同名の一時ファイルにも影響しうるため)。"""
    path = tmp_path / "a.md"

    def boom(self, content, encoding=None):
        raise OSError("simulated disk error")

    monkeypatch.setattr(Path, "write_text", boom)

    with pytest.raises(OSError):
        vault.write_text_atomic(path, "hello")

    assert not path.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_text_atomic_does_not_leave_partial_content_visible_at_target_path(tmp_path: Path, monkeypatch):
    """対象パスの`replace`前に失敗した場合、対象パスには「書き込み前の状態」しか
    存在しないこと(部分的な内容が見えてしまわないこと)。"""
    path = tmp_path / "a.md"
    path.write_text("original", encoding="utf-8")

    real_replace = Path.replace

    def boom_replace(self, target):
        raise OSError("simulated crash right before rename")

    monkeypatch.setattr(Path, "replace", boom_replace)

    with pytest.raises(OSError):
        vault.write_text_atomic(path, "new content")

    assert path.read_text(encoding="utf-8") == "original"


def test_write_text_atomic_temp_filename_includes_pid_to_avoid_collision(tmp_path: Path, monkeypatch):
    """複数プロセスが同じディレクトリへ同時に書き込んでも一時ファイル名が衝突しない
    ように、一時ファイル名にPIDを含めている(実装の意図をテストとして固定する)。"""
    import os

    path = tmp_path / "a.md"
    seen_tmp_names: list[str] = []
    real_write_text = Path.write_text

    def spy_write_text(self, content, encoding=None):
        if self.name.endswith(".tmp"):
            seen_tmp_names.append(self.name)
        return real_write_text(self, content, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", spy_write_text)
    vault.write_text_atomic(path, "hello")

    assert len(seen_tmp_names) == 1
    assert str(os.getpid()) in seen_tmp_names[0]
