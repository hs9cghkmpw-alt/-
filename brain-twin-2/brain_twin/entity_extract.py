"""Phase 2: Entity Extraction(指示書9・28章)。

classify.py(type/topics/importance/confidence)とは責務を分離し、
「本文から固有名詞らしき語を拾い、その信頼度を見積もる」ことだけを行う。

Phase 1のダミー分類器と同じ方針で、重いNLP依存(MeCab/GiNZA等)は追加しない
(指示書24章の簡素な構成という方針、および指示書38章「最小差分」を踏まえた判断。
形態素解析の追加はモデル選定・Windowsでの動作確認まで含む大きな設計変更になるため、
このPhaseの範囲外とする)。

ヒューリスティック: カタカナ連続2文字以上を固有名詞候補として拾う。
指示書に登場する実例("ナイキ"「クラルティ」)がいずれもカタカナ表記であることからも、
Phase 2として十分に価値のある粗いルールと判断した。

--- 誤検出とconfidenceについて(レビュー対応) ---

このヒューリスティックは"アプリ"「スマホ」のような、固有名詞ではない一般的な
外来語(loanword)も一緒に拾ってしまう。これをSTOPWORDSの拡充だけで対処すると、
語彙が増えるたびにリストを際限なく追加し続けることになり破綻する。

代わりに、抽出結果へ ExtractedEntity.confidence(0.0-1.0)を持たせ、
下流(linking.py)がその信頼度をリンクの強さに反映する設計にした。これにより、

  - 誤検出そのものは許容する(見逃しより検出寄りに倒すPhase 1/2の一貫方針)
  - ただし信頼度の低い一致が、単独で強いリンクの根拠にはならない
  - 「代表的な一般語」の小さな補助リストはあるが、これを網羅する必要はない
    (網羅していない一般語も、カタカナの長さに基づく基礎confidenceで
    ある程度低く見積もられる)

の3つを両立させる。confidenceの算出根拠(長さ・既知の一般語かどうか)は
`method`フィールドと合わせて記録され、将来LLM/NLPベースの抽出器に差し替える際は
`ExtractedEntity`という同じ形の値を返させれば済む。
"""
from __future__ import annotations

import re

from brain_twin.models import ExtractedEntity

# ァ-ヴー: カタカナ本体 + 長音符(ー)。「ッ」等の促音・拗音も範囲に含まれる。
_KATAKANA_RUN_RE = re.compile(r"[ァ-ヴー]{2,}")

_METHOD = "katakana_heuristic_v1"

# 単独では固有名詞として弱すぎる/誤検出が多い一般語は、そもそも候補にしない
# (助詞の断片等、"語"としてすら扱いたくないもの)。この一覧は意図的に小さく保つ。
_STOPWORDS = frozenset({"コト", "モノ", "トキ", "ノデ", "ナド"})

# 「際限なく増やすSTOPWORDS」ではなく、既知の代表的な一般語だけを軽く減点するための
# 小さな補助リスト。ここに無い一般語も、長さ由来の基礎confidenceである程度カバーされる。
_GENERIC_HINTS = frozenset({
    "アプリ", "スマホ", "パソコン", "カバン", "ノート", "ケータイ",
    "インターネット", "メール", "データ", "サイト", "ページ", "サービス",
})
_GENERIC_PENALTY = 0.4


def _base_confidence(length: int) -> float:
    """カタカナは短いほど一般的な外来語(アプリ/スマホ等)である割合が高く、
    長いほど固有名詞(ブランド名・地名・サービス名等)である可能性が上がる、
    という大まかな傾向のみに基づく粗い代理指標(厳密な言語的根拠ではない)。"""
    if length <= 2:
        return 0.3
    if length <= 4:
        return 0.55
    return 0.8


def extract_entities(text: str) -> list[ExtractedEntity]:
    """本文からカタカナの連続を固有名詞候補として抽出する(重複を除き出現順)。"""
    if not text:
        return []

    seen: set[str] = set()
    entities: list[ExtractedEntity] = []
    for match in _KATAKANA_RUN_RE.finditer(text):
        word = match.group(0)
        if word in _STOPWORDS or word in seen:
            continue
        seen.add(word)

        confidence = _base_confidence(len(word))
        if word in _GENERIC_HINTS:
            confidence *= _GENERIC_PENALTY

        entities.append(ExtractedEntity(name=word, confidence=round(confidence, 3), method=_METHOD))
    return entities
