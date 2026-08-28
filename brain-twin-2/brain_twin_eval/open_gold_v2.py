from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCENARIOS = [{'key': 'hoshimidai_trip',
  'entity': '星見台旅行',
  'title': '星見台旅行の宿泊キャンセル',
  'target': '星見台旅行の宿は、到着日の三日前までなら手数料なしでキャンセルできる。二日前以降は宿泊料金の半額がかかるので、予定変更は早めに判断する。',
  'partial': '星見台旅行の移動は午前九時の特急を第一候補にし、混雑時だけ一本早い便へ変更する。',
  'queries': ['星見台の宿、いつまでなら無料で取り消せる？', '予定が変わった時に宿代を取られない期限', '宿泊のキャンセル料が発生する境目', '星見台旅行 キャンセル']},
 {'key': 'aorango_car',
  'entity': '青嵐号',
  'title': '青嵐号の長距離前点検',
  'target': '青嵐号で長距離を走る前は、冷間時のタイヤ空気圧、ウォッシャー液、燃料残量を確認する。空気圧は出発直前ではなくタイヤが冷えている時に測る。',
  'partial': '青嵐号の車内清掃は月末に行い、荷室の非常用品も同時に確認する。',
  'queries': ['青嵐号で遠出する前のタイヤ確認', '長距離運転の前に冷えている時に測るもの', '出発直前じゃなく冷間時に見る項目', '青嵐号 点検']},
 {'key': 'fuyunagi_curry',
  'entity': '冬凪カレー',
  'title': '冬凪カレーの作り置き',
  'target': '冬凪カレーを作り置きする時は、じゃがいもを入れずにルーを小分け冷凍し、食べる日に具材を足す。冷凍容器には作成日を記入する。',
  'partial': '冬凪カレーは辛さを控えめにし、仕上げで各自が香辛料を足せるようにする。',
  'queries': ['冬凪カレーを冷凍するとき何を抜く？', '作り置きで食感が悪くならない保存方法', 'ルーを小分けして当日に具を足すやつ', 'カレー 作り置き']},
 {'key': 'transparent_garden',
  'entity': '透明な庭',
  'title': '『透明な庭』読書メモ',
  'target': '架空小説『透明な庭』で残したかった要点は、主人公が答えを急がず観察を続けたことで、最初は無関係に見えた出来事のつながりに気づいた点。',
  'partial': '『透明な庭』の読書会では第三章までを前半の範囲として扱う。',
  'queries': ['透明な庭で覚えておきたかった考え', '答えを急がず観察したことで何に気づいた？', '最初は関係なさそうな出来事がつながる話', '透明な庭 要点']},
 {'key': 'nebulabox',
  'entity': 'NebulaBox',
  'title': 'NebulaBoxの更新判断',
  'target': 'NebulaBoxの年間契約は自動更新にせず、更新日の二週間前に過去三か月の利用回数を確認し、ほとんど使っていなければ解約する。',
  'partial': 'NebulaBoxの請求書はPDFで保存し、家計フォルダへ月ごとにまとめる。',
  'queries': ['NebulaBoxを更新するか何で決める？', '使ってないサブスクをそのまま継続しないルール', '更新前に三か月分の利用回数を見るサービス', 'annual subscription の見直し']},
 {'key': 'kestrel',
  'entity': 'Project Kestrel',
  'title': 'Kestrelのロールバック条件',
  'target': 'Project Kestrelのリリースでは、主要APIのエラー率が五分間連続で二パーセントを超えたら新バージョンを止め、直前の安定版へロールバックする。',
  'partial': 'Project Kestrelの週次レビューは木曜日の午後に行い、未解決issueを優先して確認する。',
  'queries': ['Kestrelを前の版に戻す条件', '新バージョンを止めるエラー率の基準', '五分続けて2%を超えた時の対応', 'Project Kestrel rollback']},
 {'key': 'english_shadowing',
  'entity': '英語シャドーイング',
  'title': '英語シャドーイングの習慣',
  'target': '英語シャドーイングは朝に十分だけ行い、同じ音声を三日続けてから次へ進む。聞き取れなかった箇所だけ夜にスクリプトで確認する。',
  'partial': '英単語の復習は昼休みに五分だけ行い、新規単語より前日の復習を優先する。',
  'queries': ['シャドーイングは何日同じ音声を使う？', '朝の英語練習を続けやすくしたルール', '夜は聞けなかった所だけ台本で確認する練習', 'shadowing routine']},
 {'key': 'desk_lumen',
  'entity': 'Lumenデスク',
  'title': 'Lumenデスクの組立部品',
  'target': 'Lumenデスクの脚を固定するワッシャーを紛失した場合は、内径8ミリの平ワッシャーで代替する。ばね座金だけで締めない。',
  'partial': 'Lumenデスクの天板は壁から五センチ離して設置し、配線スペースを確保する。',
  'queries': ['Lumenデスクのワッシャー何ミリ？', '脚の部品をなくした時の代用品', 'ばね座金だけにしないで使う平たい部品', 'デスク ワッシャー']},
 {'key': 'gift_ciel',
  'entity': 'Cielギフト',
  'title': 'Cielギフトの受け取り予約',
  'target': 'Cielギフトは土曜日の午後に店頭受け取りで予約してあり、本人確認用の予約番号はメールではなくメモアプリの専用項目に記録する。',
  'partial': 'Cielギフトの包装は青系ではなく無地のクラフト紙を指定する。',
  'queries': ['Cielギフトを受け取る時間帯', '土曜に店で受け取る予定の贈り物', '予約番号をどこに控えることにした？', 'gift pickup Saturday']},
 {'key': 'tomato_planter',
  'entity': 'ベランダトマト',
  'title': 'ベランダトマトの水やり',
  'target': 'ベランダトマトは土の表面が乾いてから朝にたっぷり水を与える。毎日決まった量を足すのではなく、鉢の乾き具合を先に確認する。',
  'partial': 'ベランダトマトの追肥は二週間ごとに少量ずつ行う。',
  'queries': ['トマトは毎日決まった量を水やりする？', '鉢の乾き具合を見てから朝にすること', 'ベランダのトマトの水やり判断', 'トマト 水']},
 {'key': 'asterworks',
  'entity': 'AsterWorks',
  'title': 'AsterWorks面接の持ち物',
  'target': 'AsterWorksの二次面接には写真付き履歴書の予備一部と職務経歴書を持参する。ポートフォリオは紙ではなくオフライン閲覧できる端末版を準備する。',
  'partial': 'AsterWorksの面接会場には開始二十分前を目安に到着する。',
  'queries': ['AsterWorks二次面接に持っていく書類', '紙でなく端末に入れておく応募資料は？', '履歴書の予備と職務経歴書を用意する面接', 'AsterWorks interview documents']},
 {'key': 'printer_aurora',
  'entity': 'Auroraプリンター',
  'title': 'Auroraプリンターの登録方法',
  'target': 'Auroraプリンターは固定IPを端末へ直接登録せず、社内DNSのホスト名 printer-aurora.local で追加する。機器交換時の再設定を減らすため。',
  'partial': 'Auroraプリンターの両面印刷は長辺綴じを既定値にする。',
  'queries': ['AuroraプリンターはIP直打ちだっけ？', '機器交換しても再設定を減らす登録方法', 'printer-aurora.local を使う理由', 'プリンター hostname']},
 {'key': 'meshlink',
  'entity': 'MeshLink',
  'title': 'MeshLinkの接続確認',
  'target': 'MeshLinkで端末同士が直接通信できない時は、まず双方のオンライン状態と名前解決を確認し、その後に経路情報を見る。いきなり設定を初期化しない。',
  'partial': 'MeshLinkの端末名は所有者名ではなく用途ベースで付ける。',
  'queries': ['MeshLinkが直接つながらない時の最初の確認', '接続不良でいきなり初期化しない手順', 'オンライン状態と名前解決を先に見るやつ', 'MeshLink troubleshooting']},
 {'key': 'local_notes',
  'entity': 'LocalNote',
  'title': 'LocalNoteの同期方針',
  'target': 'LocalNoteは端末内のMarkdownを正本にし、同期サービスが停止していても閲覧と追記を続けられるようにする。復旧後に差分だけ同期する。',
  'partial': 'LocalNoteの添付画像は月ごとのサブフォルダに保存する。',
  'queries': ['LocalNoteは同期が止まったら書けなくなる？', 'ネットなしでも追記できるノートの正本', '復旧後に差分だけ合わせるlocal-first方針', 'LocalNote offline sync']},
 {'key': 'passkey_sora',
  'entity': 'Sora Passkey',
  'title': 'Sora Passkeyの予備経路',
  'target': 'Sora Passkeyを設定した端末を失った場合に備え、第二端末にも別のパスキーを登録し、復旧コードは暗号化したオフライン保管先へ置く。',
  'partial': 'Sora Passkeyの名称は端末種別が分かるように登録する。',
  'queries': ['Sora Passkeyの端末をなくした時の備え', '第二端末にも登録しておく認証方法', '復旧コードをオンラインメモに置かない理由', 'passkey backup']},
 {'key': 'fishing_nagi',
  'entity': '凪港ルアー',
  'title': '凪港ルアーの使い分け',
  'target': '凪港で朝まずめに小魚が表層へ出ている時は、銀色の小型メタルジグを先に投げ、反応がなければゆっくり沈めるワームへ切り替える。',
  'partial': '凪港では足元が濡れている日は滑りにくい靴を優先する。',
  'queries': ['凪港で朝に表層へ小魚がいる時の最初のルアー', '朝まずめで銀色の小さいジグから試す場所', '反応がなければワームへ変える釣り方', '凪港 lure']},
 {'key': 'kayak_pedal',
  'entity': 'AquaPedal',
  'title': 'AquaPedalの使用後整備',
  'target': 'AquaPedalのペダルユニットは海で使った日に真水で洗い、砂を落としてから可動部を乾燥させる。保管前に無理な高圧洗浄はしない。',
  'partial': 'AquaPedalの予備パドルは二分割式を船体横へ固定する。',
  'queries': ['AquaPedalを海で使った後の洗い方', 'ペダル部分の塩と砂を落とす手入れ', '高圧洗浄じゃなく真水で流して乾かすもの', 'kayak pedal maintenance']},
 {'key': 'photo_raw',
  'entity': 'MoonCam',
  'title': 'MoonCam写真のバックアップ',
  'target': 'MoonCamで撮影したRAWは、撮影日の夜にPCへコピーし、確認後に外付けSSDへ二重化する。二か所のコピーを確認するまでSDカードを初期化しない。',
  'partial': 'MoonCamのJPEG書き出しは長辺2400ピクセルを共有用の既定値にする。',
  'queries': ['MoonCamのSDカードを消していい条件', 'RAWを二か所に置くまで残すもの', '撮影日の夜にPCとSSDへ二重化する手順', 'photo RAW backup']},
 {'key': 'story_iris',
  'entity': 'Iris稿',
  'title': 'Iris稿の人物名ルール',
  'target': 'Iris稿では主人公の仮名を『ミナト』で統一し、旧メモに残る『ハル』は同一人物として扱う。公開前に旧名だけが残っていないか検索する。',
  'partial': 'Iris稿の章タイトルは数字ではなく短い名詞句にする。',
  'queries': ['Iris稿のハルって誰と同じ？', '旧メモの人物名をミナトに統一する話', '公開前に旧名が残ってないか探す原稿', 'Iris character alias']},
 {'key': 'movie_lantern',
  'entity': 'Lantern映画会',
  'title': 'Lantern映画会の候補決定',
  'target': 'Lantern映画会では、二時間を超える作品は平日候補から外し、参加者三人以上が未視聴の作品を優先する。',
  'partial': 'Lantern映画会の飲み物は各自持参にする。',
  'queries': ['Lantern映画会で平日に長い映画は選ぶ？', '未視聴の人が三人以上いる作品を優先する条件', '上映時間が2時間超なら平日から外す会', 'movie night rule']},
 {'key': 'leak_valve',
  'entity': '洗面台漏水',
  'title': '洗面台漏水の初動',
  'target': '洗面台の給水管から漏れた時は、まず止水栓を閉めて水を止め、床を拭いて被害範囲を確認する。工具で分解するのは止水後にする。',
  'partial': '洗面台の収納は洗剤と掃除用品を左右で分ける。',
  'queries': ['洗面台から水が漏れた時に最初に閉めるもの', '分解する前に水を止める初動', '給水管の漏れで床を拭く前後の順番', '洗面台 漏水']},
 {'key': 'electric_bill',
  'entity': 'Hikari電気',
  'title': 'Hikari電気の支払い確認',
  'target': 'Hikari電気は口座振替だが、毎月の請求額が前月比で三割以上増えた時だけ明細を確認し、使用量と単価のどちらが変わったかを見る。',
  'partial': 'Hikari電気の契約番号は紙の検針票ではなく家計メモに保存する。',
  'queries': ['Hikari電気の明細を毎月見る必要ある？', '請求が前月より3割以上増えた時に確認すること', '電気代の増加が使用量か単価かを見るルール', 'electric bill check']},
 {'key': 'calendar_orbit',
  'entity': 'Orbit定例',
  'title': 'Orbit定例の繰り返し予定',
  'target': 'Orbit定例は隔週水曜の15時に設定し、祝日に重なる回だけ翌木曜へ移す。シリーズ全体ではなく該当回だけ変更する。',
  'partial': 'Orbit定例の議事録は会議終了後に共有フォルダへ置く。',
  'queries': ['Orbit定例が祝日ならいつにずらす？', '繰り返し予定全部を動かさず該当回だけ変える会議', '隔週水曜15時の予定', 'Orbit recurring calendar']},
 {'key': 'api_comet',
  'entity': 'Comet API',
  'title': 'Comet APIのレート制限対応',
  'target': 'Comet APIが429を返した場合はRetry-Afterを優先し、値がなければ指数バックオフを使う。同じリクエストを即時連打しない。',
  'partial': 'Comet APIのレスポンスIDは障害調査用ログへ保存する。',
  'queries': ['Comet APIで429が返った時の待ち方', 'Retry-Afterがなければどう再試行する？', '同じ要求を連打せず指数的に待つAPI', 'API rate limit backoff']},
 {'key': 'db_nova',
  'entity': 'NovaDB',
  'title': 'NovaDB移行の戻し方',
  'target': 'NovaDBのスキーマ移行は先に読み取り互換を保つ列追加を行い、旧アプリが動く状態を確認してから書き込み先を切り替える。破壊的削除は次回リリースへ分離する。',
  'partial': 'NovaDBのバックアップは移行開始前にスナップショットを作る。',
  'queries': ['NovaDBで破壊的削除を同じリリースに入れる？', '旧アプリを動かしたまま列を追加してから切り替える移行', '戻しやすくするため削除を次回へ分けるDB変更', 'database migration rollback']},
 {'key': 'decision_echo',
  'entity': 'Echo会議',
  'title': 'Echo会議の決定ログ',
  'target': 'Echo会議では議論全文ではなく、決定事項、決めた理由、保留事項、次の担当だけを決定ログへ残す。後から結論を追えることを優先する。',
  'partial': 'Echo会議の参加者一覧は招待カレンダーを正とする。',
  'queries': ['Echo会議でログに残す四つの項目', '議論全部じゃなく結論を後から追えるようにする記録', '決定理由と保留と担当を残す会議メモ', 'meeting decision log']},
 {'key': 'shop_return',
  'entity': 'Maple Store',
  'title': 'Maple Storeの返品期限',
  'target': 'Maple Storeの未使用品は受取日から十四日以内なら返品できる。箱を捨ててもよいが、付属品と注文番号は必要。',
  'partial': 'Maple Storeの配送日時変更は発送前ならアプリから行える。',
  'queries': ['Maple Storeは何日以内なら返品できる？', '箱がなくても付属品と注文番号があれば返せる店', '受取から2週間の返品ルール', 'return window Maple']},
 {'key': 'commute_snow',
  'entity': '雪の日通勤',
  'title': '雪の日通勤判断',
  'target': '雪の日通勤は所要時間だけでなく運休情報を先に確認し、主要路線が止まっている場合は代替交通を探す前に在宅へ切り替えられるか確認する。',
  'partial': '雪の日は靴底の滑りやすさも出発前に確認する。',
  'queries': ['雪の日に交通手段を探す前に確認する選択肢', '主要路線が止まってたらまず在宅にできるか見る', '所要時間より運休情報を先に見る通勤判断', 'snow commute']},
 {'key': 'writing_variation',
  'entity': '取扱メモ',
  'title': '取扱メモの表記ゆれ',
  'target': '取扱メモでは『取扱い』『取り扱い』『とりあつかい』を同じ検索語グループとして扱い、どの表記で入力しても同じ関連メモへ到達できるようにする。',
  'partial': '取扱メモの見出しでは常用漢字を優先する。',
  'queries': ['とりあつかいって漢字のメモも出る？', '取り扱いと取扱いを同じものとして探したい', 'ひらがなでも同じ関連メモへ行く表記ルール', '取扱い 表記']},
 {'key': 'offline_model',
  'entity': 'Offline Model Pack',
  'title': 'Offline Model Packの取得方針',
  'target': 'Offline Model Packは初回セットアップ時に利用者が明示的に取得し、実行時はlocal-files-onlyで読み込む。検索中にネットから自動ダウンロードしない。',
  'partial': 'Offline Model Packの保存先にはモデル名と固定revisionを含むmanifestを置く。',
  'queries': ['モデルを検索中に勝手にダウンロードする？', '最初に明示取得して実行時はローカルだけ使う方針', 'local-files-onlyで動かすモデルパック', 'offline model download']}]

KATAKANA_MAP = {'api_comet': 'コメットAPI',
 'kayak_pedal': 'アクアペダル',
 'nebulabox': 'ネビュラボックス',
 'printer_aurora': 'オーロラプリンター',
 'story_iris': 'アイリス稿'}
VARIATION_MAP = {'desk_lumen': 'デスクの組み立てで、なくした座金の代わり',
 'fishing_nagi': 'あさまずめで最初に投げるもの',
 'fuyunagi_curry': 'つくりおきで、じゃがいもを入れない保存方法',
 'tomato_planter': 'ベランダトマトのみずやり判断',
 'writing_variation': 'とりあつかいの漢字表記も同じ検索結果にしたい'}
LONG_KEYS = {'photo_raw', 'local_notes', 'kestrel', 'offline_model', 'db_nova'}
DISTRACTOR_TEMPLATES = ['{entity}の連絡用メモは、担当者が変わっても参照できる共有フォルダに置く。',
 '{entity}の資料では見出しを短くし、日付を先頭に付けて並び替えやすくする。',
 '{entity}の定例確認は木曜午後に行い、未処理の項目だけを一覧で確認する。',
 '{entity}の古い画像や添付ファイルは月末にアーカイブへ移し、本文は残す。',
 '{entity}の名称を変更した場合は、旧名を別名として検索できるよう記録する。',
 '{entity}に関する雑談メモは正式な決定事項と区別し、決定ログへ混ぜない。',
 '{entity}のチェックリストは完了項目を削除せず、実施日だけ追記する。',
 '{entity}の共有リンクは期限付きにし、期限切れ後は新しいリンクを発行する。',
 '{entity}のレビューでは誤字修正と仕様変更を同じ変更として扱わず、理由を分けて残す。',
 '{entity}のバックアップ資料は作業用コピーと区別し、復元に使える版を明記する。']

VERSION = "ja-retrieval-v2-open-2026-08-29"


def _is_ascii_mixed(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value))


def build_open_gold_v2() -> dict[str, Any]:
    """Build the deterministic open Japanese retrieval benchmark.

    This dataset is intentionally public/open. Its blind-labelled split is only for
    pipeline split handling and must never be treated as formal held-out acceptance.
    """
    memories: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    memory_number = 1
    query_number = 1

    for index, scenario in enumerate(SCENARIOS):
        target = scenario["target"]
        if scenario["key"] in LONG_KEYS:
            extra = (
                " この記録では、判断の前提、例外条件、失敗した場合の戻し方、確認した時刻を分けて残す。"
                " 後から読み返した人が元の意図を推測しなくても再現できるよう、事実と判断を混ぜずに記述する。"
                " 同じテーマの別メモがあっても、今回の条件と対象範囲が分かるよう固有名詞と具体的な基準を残す。"
            )
            target += extra * 12

        target_id = f"v2-mem-{memory_number:03d}"
        memory_number += 1
        memories.append(
            {
                "memory_id": target_id,
                "title": scenario["title"],
                "content": target,
                "language_tags": ["ja", "en"] if _is_ascii_mixed(scenario["entity"] + target) else ["ja"],
                "length_bucket": "long" if scenario["key"] in LONG_KEYS else "short",
                "active": True,
            }
        )

        partial_id = f"v2-mem-{memory_number:03d}"
        memory_number += 1
        memories.append(
            {
                "memory_id": partial_id,
                "title": f"{scenario['entity']}の関連メモ",
                "content": scenario["partial"],
                "language_tags": ["ja", "en"] if _is_ascii_mixed(scenario["entity"] + scenario["partial"]) else ["ja"],
                "length_bucket": "short",
                "active": True,
            }
        )

        distractor_ids: list[str] = []
        for distractor_index, template in enumerate(DISTRACTOR_TEMPLATES, start=1):
            memory_id = f"v2-mem-{memory_number:03d}"
            memory_number += 1
            content = template.format(entity=scenario["entity"])
            active = not (distractor_index == 10 and index % 6 == 0)
            memories.append(
                {
                    "memory_id": memory_id,
                    "title": f"{scenario['entity']}周辺メモ{distractor_index}",
                    "content": content,
                    "language_tags": ["ja", "en"] if _is_ascii_mixed(scenario["entity"] + content) else ["ja"],
                    "length_bucket": "short",
                    "active": active,
                }
            )
            distractor_ids.append(memory_id)

        splits = ["dev", "dev", "blind", "blind"] if index < 10 else ["dev", "dev", "dev", "blind"]
        q1, q2, q3, _q4 = scenario["queries"]

        q1_tags = ["japanese_to_japanese", "lexical_sufficient", f"domain_{scenario['key']}"]
        if _is_ascii_mixed(scenario["entity"]):
            q1_tags.append("japanese_english_mixed")
        queries.append(
            {
                "query_id": f"v2-q-{query_number:03d}",
                "text": q1,
                "slice_tags": q1_tags,
                "relevance": {target_id: 3, partial_id: 1},
                "must_hit_ids": [target_id],
                "lexical_sufficient": True,
                "adjudication_note": "対象を直接または固有名詞を含めて尋ねる基本query。",
                "split": splits[0],
            }
        )
        query_number += 1

        q2_tags = ["paraphrase", "semantic_only", f"domain_{scenario['key']}"]
        q2_tags.append("synonym" if index % 2 == 0 else "omission_context")
        if scenario["key"] in LONG_KEYS:
            q2_tags.append("long_memory")
        queries.append(
            {
                "query_id": f"v2-q-{query_number:03d}",
                "text": q2,
                "slice_tags": q2_tags,
                "relevance": {target_id: 3, partial_id: 1},
                "must_hit_ids": [target_id],
                "lexical_sufficient": False,
                "adjudication_note": "語彙一致を減らした意味検索query。",
                "split": splits[1],
            }
        )
        query_number += 1

        q3_tags = ["semantic_only", f"domain_{scenario['key']}"]
        q3_text = q3
        if scenario["key"] in KATAKANA_MAP:
            q3_text = f"{KATAKANA_MAP[scenario['key']]}について前に決めたこと"
            q3_tags += ["katakana_transliteration", "proper_noun"]
        elif scenario["key"] in VARIATION_MAP:
            q3_text = VARIATION_MAP[scenario["key"]]
            q3_tags += ["kanji_hiragana_variation", "paraphrase"]
        elif _is_ascii_mixed(scenario["entity"]):
            q3_text = f"{scenario['entity']} {q3}"
            q3_tags += ["japanese_english_mixed", "proper_noun"]
        else:
            q3_tags += ["omission_context", "paraphrase"]
        if scenario["key"] in LONG_KEYS:
            q3_tags.append("long_memory")
        queries.append(
            {
                "query_id": f"v2-q-{query_number:03d}",
                "text": q3_text,
                "slice_tags": q3_tags,
                "relevance": {target_id: 3, partial_id: 1},
                "must_hit_ids": [target_id],
                "lexical_sufficient": False,
                "adjudication_note": "表記ゆれ・日英混在・省略を含む追加query。",
                "split": splits[2],
            }
        )
        query_number += 1

        if index % 3 == 2:
            q4_text = f"{scenario['entity']}の量子転送装置の校正番号"
            q4_tags = ["hard_negative", f"domain_{scenario['key']}"]
            relevance = {distractor_ids[0]: 0, distractor_ids[1]: 0}
            must_hit_ids: list[str] = []
            lexical_sufficient = False
            note = "同一ドメイン/固有名詞を含むが、corpus内に答えがないhard negative。"
        else:
            q4_text = scenario["entity"]
            q4_tags = ["short_query", "proper_noun", "lexical_sufficient", f"domain_{scenario['key']}"]
            if _is_ascii_mixed(scenario["entity"]):
                q4_tags.append("japanese_english_mixed")
            relevance = {target_id: 3, partial_id: 2}
            must_hit_ids = [target_id]
            lexical_sufficient = True
            note = "固有名詞だけの短query。"

        queries.append(
            {
                "query_id": f"v2-q-{query_number:03d}",
                "text": q4_text,
                "slice_tags": q4_tags,
                "relevance": relevance,
                "must_hit_ids": must_hit_ids,
                "lexical_sufficient": lexical_sufficient,
                "adjudication_note": note,
                "split": splits[3],
            }
        )
        query_number += 1

    return {
        "version": VERSION,
        "judgement_visibility": "open",
        "memories": memories,
        "queries": queries,
    }


def write_open_gold_v2(path: str | Path) -> Path:
    target = Path(path)
    payload = build_open_gold_v2()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
