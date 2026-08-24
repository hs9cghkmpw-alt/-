from brain_twin.entity_extract import extract_entities


def test_extracts_katakana_proper_nouns():
    # ヒューリスティックは「カタカナの連続」を拾うだけなので、"カバン"(bag)のような
    # 一般名詞の外来語も一緒に拾ってしまう。これは既知の限界として entity_extract.py の
    # docstring / README に明記している(誤検出はあるが見逃しより検出寄りに倒す設計)。
    result = extract_entities("ナイキのカバンだ")
    assert "ナイキ" in result
    assert "カバン" in result


def test_extracts_multiple_distinct_entities_in_order():
    result = extract_entities("クラルティに応募する前にナイキの本社も調べた")
    assert result == ["クラルティ", "ナイキ"]


def test_deduplicates_repeated_entity():
    result = extract_entities("ナイキが好き。やっぱりナイキが一番好き。")
    assert result == ["ナイキ"]


def test_no_katakana_returns_empty_list():
    assert extract_entities("病院いったら診断書お願いしなきゃ") == []


def test_empty_text_returns_empty_list():
    assert extract_entities("") == []


def test_single_katakana_character_is_ignored():
    # 1文字だけのカタカナは誤検出が多いため拾わない(正規表現の{2,}制約)。
    assert extract_entities("ア") == []
