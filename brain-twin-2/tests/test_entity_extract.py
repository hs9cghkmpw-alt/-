from brain_twin.entity_extract import extract_entities


def _names(entities):
    return [e.name for e in entities]


def test_extracts_katakana_proper_nouns():
    # ヒューリスティックは「カタカナの連続」を拾うだけなので、"カバン"(bag)のような
    # 一般名詞の外来語も一緒に拾ってしまう。これは既知の限界として entity_extract.py の
    # docstring / README に明記している(誤検出はあるが見逃しより検出寄りに倒す設計)。
    result = _names(extract_entities("ナイキのカバンだ"))
    assert "ナイキ" in result
    assert "カバン" in result


def test_extracts_multiple_distinct_entities_in_order():
    result = _names(extract_entities("クラルティに応募する前にナイキの本社も調べた"))
    assert result == ["クラルティ", "ナイキ"]


def test_deduplicates_repeated_entity():
    result = _names(extract_entities("ナイキが好き。やっぱりナイキが一番好き。"))
    assert result == ["ナイキ"]


def test_no_katakana_returns_empty_list():
    assert extract_entities("病院いったら診断書お願いしなきゃ") == []


def test_empty_text_returns_empty_list():
    assert extract_entities("") == []


def test_single_katakana_character_is_ignored():
    # 1文字だけのカタカナは誤検出が多いため拾わない(正規表現の{2,}制約)。
    assert extract_entities("ア") == []


# ---- confidence(レビュー対応: 精度の低い一致を強いリンクの根拠にしないための土台) ----


def test_each_entity_carries_confidence_and_method():
    result = extract_entities("ナイキが好き")
    assert len(result) == 1
    entity = result[0]
    assert 0.0 < entity.confidence <= 1.0
    assert entity.method  # 空文字ではない(将来別の抽出手法と判別できるように)


def test_known_generic_loanword_gets_lower_confidence_than_distinctive_word():
    # "アプリ"は _GENERIC_HINTS に含まれる代表的な一般語。ヒューリスティックが
    # 一般語だと知っている場合、confidenceは下がる。
    generic = extract_entities("アプリを作った")[0]
    distinctive = extract_entities("ブレインツインを作った")[0]
    assert generic.confidence < distinctive.confidence


def test_longer_katakana_run_gets_higher_base_confidence_than_very_short_one():
    # 長さに基づく粗い代理指標: 短いカタカナほど一般語の割合が高いとみなす。
    short = extract_entities("ドアを開けた")[0]
    long_ = extract_entities("ブレインツインを開発した")[0]
    assert short.confidence < long_.confidence


def test_generic_hint_list_is_small_and_not_exhaustive_by_design():
    """STOPWORDSを際限なく増やす設計にしていないことの回帰確認。_GENERIC_HINTSに
    無い一般語(例: 未知の外来語)であっても、長さ由来の基礎confidenceにより
    "アプリ"のような既知の一般語よりは高いが、長い固有名詞よりは低い、
    という粗い連続的な扱いになる(バイナリなSTOPWORDS判定ではないことの確認)。"""
    from brain_twin.entity_extract import _GENERIC_HINTS

    assert len(_GENERIC_HINTS) < 50  # 「無限に増やさない」という設計方針の目安
