from brain_twin import frontmatter as fm


def test_roundtrip_preserves_unicode_and_lists():
    front = {
        "id": "mem_20260814_001",
        "importance": 4,
        "confidence": 1.0,
        "topics": ["work", "health"],
        "entities": [],
        "note": None,
    }
    body = "封筒仕分け作業で高い処理速度\n\n本文がここに入る。"

    text = fm.dump(front, body)
    parsed = fm.parse(text)

    assert parsed.frontmatter["id"] == "mem_20260814_001"
    assert parsed.frontmatter["importance"] == 4
    assert parsed.frontmatter["confidence"] == 1.0
    assert parsed.frontmatter["topics"] == ["work", "health"]
    assert parsed.frontmatter["entities"] == []
    assert parsed.frontmatter["note"] is None
    assert "封筒仕分け作業で高い処理速度" in parsed.body


def test_dump_uses_readable_unicode_not_escapes():
    text = fm.dump({"title": "テスト"}, "本文")
    assert "テスト" in text
    assert "\\u" not in text


def test_parse_without_frontmatter_returns_empty_dict():
    parsed = fm.parse("frontmatterが無いプレーンな本文\n")
    assert parsed.frontmatter == {}
    assert "frontmatterが無いプレーンな本文" in parsed.body
