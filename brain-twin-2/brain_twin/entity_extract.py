"""Phase 2: Entity Extraction(指示書9・28章)。

classify.py(type/topics/importance/confidence)とは責務を分離し、
「本文から固有名詞らしき語を拾う」ことだけを行う。

Phase 1のダミー分類器と同じ方針で、重いNLP依存(MeCab/GiNZA等)は追加しない
(指示書24章の簡素な構成という方針、および指示書38章「最小差分」を踏まえた判断。
形態素解析の追加はモデル選定・Windowsでの動作確認まで含む大きな設計変更になるため、
このPhaseの範囲外とする)。

ヒューリスティック: カタカナ連続2文字以上を固有名詞候補として拾う。
指示書に登場する実例("ナイキ"「クラルティ」)がいずれもカタカナ表記であることからも、
Phase 2として十分に価値のある粗いルールと判断した。人名(漢字)等の抽出は
本格的な形態素解析が必要なため対象外(README「今後」に明記する)。
"""
from __future__ import annotations

import re

# ァ-ヴー: カタカナ本体 + 長音符(ー)。「ッ」等の促音・拗音も範囲に含まれる。
_KATAKANA_RUN_RE = re.compile(r"[ァ-ヴー]{2,}")

# 単独では固有名詞として弱すぎる/誤検出が多い一般語は除外する。
_STOPWORDS = frozenset({"コト", "モノ", "トキ", "ノデ", "ナド"})


def extract_entities(text: str) -> list[str]:
    """本文からカタカナの連続を固有名詞候補として抽出する(重複を除き出現順)。"""
    if not text:
        return []

    seen: set[str] = set()
    entities: list[str] = []
    for match in _KATAKANA_RUN_RE.finditer(text):
        word = match.group(0)
        if word in _STOPWORDS or word in seen:
            continue
        seen.add(word)
        entities.append(word)
    return entities
