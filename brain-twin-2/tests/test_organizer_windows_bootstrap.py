from __future__ import annotations

from pathlib import Path

from brain_twin_eval.organizer_local_runtime import _encode_chat


ROOT = Path(__file__).resolve().parent.parent


class _Encoded(dict):
    def __init__(self):
        super().__init__({"input_ids": _Tensor()})
        self.to_device = None

    def to(self, device: str):
        self.to_device = device
        return self


class _Tensor:
    def __init__(self):
        self.to_device = None

    def to(self, device: str):
        self.to_device = device
        return self


class _Processor:
    def __init__(self):
        self.kwargs = None

    def apply_chat_template(self, messages, **kwargs):
        self.kwargs = kwargs
        return _Encoded()


def test_qwen_chat_encoding_uses_official_direct_tokenization_contract() -> None:
    processor = _Processor()
    encoded = _encode_chat(processor, [{"role": "user", "content": "x"}])
    assert processor.kwargs == {
        "add_generation_prompt": True,
        "tokenize": True,
        "return_dict": True,
        "return_tensors": "pt",
        "enable_thinking": False,
    }
    assert "input_ids" in encoded
    assert encoded["input_ids"].to_device == "cpu"


def test_windows_eval_requirements_are_exact_and_isolated() -> None:
    requirements = (ROOT / "evaluation_profiles" / "organizer_windows_requirements_v1.txt").read_text(encoding="utf-8")
    assert "torch==2.13.0" in requirements
    assert "torchvision==0.28.0" in requirements
    assert "transformers==5.16.1" in requirements
    assert "huggingface-hub==1.28.0" in requirements
    assert "Pillow==12.3.0" in requirements
    assert ">=" not in requirements
    production_requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "torch==" not in production_requirements
    assert "transformers==" not in production_requirements


def test_windows_smoke_script_downloads_only_qwen08_before_comparison() -> None:
    smoke = (ROOT / "scripts" / "smoke_organizer_qwen08_windows.ps1").read_text(encoding="utf-8")
    assert "--candidate-id qwen3.5-0.8b" in smoke
    executable_lines = [line for line in smoke.splitlines() if line.strip().startswith("& $EvalPython")]
    assert all("qwen3.5-2b" not in line for line in executable_lines)
    assert "--sample-limit $SampleLimit" in smoke


def test_setup_script_uses_separate_organizer_venv_and_ff_only_pull() -> None:
    setup = (ROOT / "scripts" / "setup_organizer_eval_windows.ps1").read_text(encoding="utf-8")
    assert ".venv-organizer" in setup
    assert "git pull --ff-only" in setup
    assert "dirty worktree" in setup
    assert "organizer_windows_requirements_v1.txt" in setup
    assert "preflight_organizer_windows.py" in setup


def test_organizer_venv_is_gitignored() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".venv-organizer/" in ignore
