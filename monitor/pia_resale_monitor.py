#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ぴあ公式リセールサイト 監視スクリプト（通知のみ / 購入操作は一切行いません）
================================================================

対象ページ（リセール出品一覧）を一定間隔でチェックし、

  - 対象日付（デフォルト: 8/26）
  - 対象枚数（デフォルト: 2枚）

の両方に一致する出品を検知したら、デスクトップ通知・PC音・コンソール表示・
ログファイル記録でお知らせします。

このスクリプトは「通知」までしか行いません。出品ページを開く／購入に進む／
決済する、といった操作は一切自動化していません。検知後の操作（購入に進む
〜決済〜最終購入）は必ずご自身の手で行ってください。

【重要な注意】
- 本スクリプトの一覧ページの解析ロジックは、実際のページHTML構造を確認
  できない環境で作成したため、暫定的なヒューリスティック（見出しの近く
  にある日付表現・枚数表現をテキストベースで探す方式）になっています。
  初回は `--dump-html` オプションで実際に取得したHTMLをファイルに保存し、
  意図通りに検知できているか確認してください。もし検知漏れ・誤検知が
  あれば、保存したHTMLの該当箇所を教えていただければロジックを調整します。
- 短い間隔（数秒単位）でのアクセスはサイト側の負荷やアクセス制限（bot対策）
  の対象になる可能性があります。まずは長めの間隔（例: 15〜30秒）で動作を
  確認し、問題なければ間隔を調整することを推奨します。
- 本スクリプトは利用者ご自身の環境で、ご自身の責任において実行してください。

使い方:
    pip install -r requirements.txt
    python pia_resale_monitor.py

    # 間隔・条件を変える場合
    python pia_resale_monitor.py --interval 10 --date "8/26" --qty "2枚"

    # まずページのHTMLを保存して構造を確認したいだけの場合
    python pia_resale_monitor.py --dump-html
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# 監視対象URL（ユーザー指定のリセール一覧ページ）
# ----------------------------------------------------------------------
DEFAULT_URL = (
    "https://cloak.pia.jp/resale/item/list"
    "?eventCd=2619297&rlsCd=&lotRlsCd="
    "&acptCliCd=ATM043&acptCliCd=ATM053&acptCliCd=ATM003"
    "&acptCliCd=ATM013&acptCliCd=ATM023&acptCliCd=ATM033"
    "&acptCliCd=ATM063&acptCliCd=ATM073"
)

# 「該当する商品がありません」的な、出品ゼロを表す代表的な文言
NO_ITEM_PHRASES = [
    "該当する商品がありません",
    "対象の商品がありません",
    "現在お申込みいただける",  # 「現在お申込みいただける商品はありません」等の言い回し対策
    "販売中の商品はありません",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

LOG_FILE = Path(__file__).parent / "matches.log"
STATE_FILE = Path(__file__).parent / ".last_state"


def notify(title: str, message: str) -> None:
    """デスクトップ通知 + PC音 + コンソール表示。失敗しても落ちないようにする。"""
    print("\a", end="", flush=True)  # ターミナルベル
    print(f"\n{'=' * 60}\n[通知] {title}\n{message}\n{'=' * 60}\n", flush=True)

    # デスクトップ通知（plyerが入っていれば使う。無ければ静かにスキップ）
    try:
        from plyer import notification as plyer_notification

        plyer_notification.notify(title=title, message=message, timeout=15)
    except Exception:
        pass

    # Windowsであれば追加でビープ音
    if sys.platform.startswith("win"):
        try:
            import winsound

            winsound.Beep(1000, 400)
            winsound.Beep(1400, 400)
        except Exception:
            pass

    # macOSであれば追加で通知センター（osascript）
    if sys.platform == "darwin":
        try:
            import subprocess

            safe_title = title.replace('"', "'")
            safe_message = message.replace('"', "'").replace("\n", " ")
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{safe_message}" with title "{safe_title}" sound name "Glass"',
                ],
                check=False,
            )
        except Exception:
            pass


def log_match(text: str) -> None:
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] MATCH:\n{text.strip()}\n{'-' * 40}\n")


def fetch_page(url: str, timeout: int = 15) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


def normalize_date_variants(date_str: str) -> list[str]:
    """
    "8/26" のような指定から、ページ上でありそうな表記ゆれを何パターンか作る。
    例: "8/26" -> ["8/26", "08/26", "8月26日"]
    """
    variants = {date_str}
    m = re.match(r"^(\d{1,2})[/月](\d{1,2})日?$", date_str)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        variants.add(f"{month}/{day}")
        variants.add(f"{month:02d}/{day:02d}")
        variants.add(f"{month}月{day}日")
        variants.add(f"{month:02d}月{day:02d}日")
    return list(variants)


def find_matching_blocks(
    html: str, date_variants: list[str], qty_text: str
) -> tuple[list[str], bool]:
    """
    ページHTMLから、日付条件と枚数条件の両方を満たしていそうな「かたまり」を探す。

    実際のDOM構造が未確認のため、2段構えのヒューリスティックで探す:
      1. class名に item / resale / card / list / goods / row を含む要素を
         候補ブロックとして、その中に日付・枚数の両方が含まれるか確認する。
      2. 1で何も見つからなければ、ページ全体のテキストを一定文字数の
         スライディングウィンドウで走査し、日付と枚数が近い位置に
         両方出現する箇所を探す（フォールバック）。

    戻り値: (マッチしたブロックのテキスト一覧, 「出品ゼロ」文言が見つかったか)
    """
    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text("\n", strip=True)

    no_item = any(phrase in full_text for phrase in NO_ITEM_PHRASES)

    matches: list[str] = []

    # --- 1. 構造ベースの探索 ---
    candidate_re = re.compile(
        r"(item|resale|card|list|goods|row|product)", re.IGNORECASE
    )
    candidates = soup.find_all(
        lambda tag: tag.name in ("li", "tr", "div", "section")
        and tag.get("class")
        and candidate_re.search(" ".join(tag.get("class")))
    )
    seen_texts: set[str] = set()
    for tag in candidates:
        text = tag.get_text("\n", strip=True)
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        if any(dv in text for dv in date_variants) and qty_text in text:
            matches.append(text)

    if matches:
        return matches, no_item

    # --- 2. フォールバック: 全文テキストのスライディングウィンドウ探索 ---
    window = 200  # 前後200文字以内に両方の条件が出現していれば「近い」とみなす
    for dv in date_variants:
        for m in re.finditer(re.escape(dv), full_text):
            start = max(0, m.start() - window)
            end = min(len(full_text), m.end() + window)
            snippet = full_text[start:end]
            if qty_text in snippet:
                if snippet not in matches:
                    matches.append(snippet)

    return matches, no_item


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL, help="監視対象のURL")
    parser.add_argument("--date", default="8/26", help="検知したい日付（例: 8/26）")
    parser.add_argument("--qty", default="2枚", help="検知したい枚数の文言（例: 2枚）")
    parser.add_argument("--interval", type=float, default=15.0, help="ポーリング間隔（秒）。既定15秒。短すぎるとアクセス制限のリスクあり")
    parser.add_argument("--remind-interval", type=float, default=60.0, help="条件成立中に再通知する間隔（秒）")
    parser.add_argument("--dump-html", action="store_true", help="通知はせず、取得したHTMLをファイルに保存して終了する（構造確認用）")
    args = parser.parse_args()

    date_variants = normalize_date_variants(args.date)

    if args.dump_html:
        html = fetch_page(args.url)
        out_path = Path(__file__).parent / f"page_dump_{dt.datetime.now():%Y%m%d_%H%M%S}.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"HTMLを保存しました: {out_path}")
        return

    print(f"監視開始: {args.url}")
    print(f"条件: 日付 in {date_variants} かつ 枚数文言 '{args.qty}'")
    print(f"間隔: {args.interval}秒 / 再通知間隔: {args.remind_interval}秒")
    print("Ctrl+C で停止します。\n")

    last_notified_at: float | None = None
    consecutive_errors = 0

    try:
        while True:
            try:
                html = fetch_page(args.url)
                matches, no_item = find_matching_blocks(html, date_variants, args.qty)
                consecutive_errors = 0

                now = dt.datetime.now().strftime("%H:%M:%S")
                if matches:
                    should_notify = (
                        last_notified_at is None
                        or (time.monotonic() - last_notified_at) >= args.remind_interval
                    )
                    print(f"[{now}] ★条件に一致する出品を検知しました（{len(matches)}件）")
                    for text in matches:
                        log_match(text)
                    if should_notify:
                        preview = matches[0][:200]
                        notify(
                            "ぴあリセール: 条件に一致する出品を検知",
                            f"{args.date} / {args.qty} の条件に一致する出品があります。\n"
                            f"手動でページを開いて内容を確認し、購入操作はご自身で行ってください。\n\n{preview}",
                        )
                        last_notified_at = time.monotonic()
                else:
                    status = "出品なし（「該当する商品がありません」等）" if no_item else "条件に一致する出品なし"
                    print(f"[{now}] {status}")
                    last_notified_at = None  # 条件が外れたら再通知タイマーをリセット

            except requests.RequestException as e:
                consecutive_errors += 1
                print(f"[{dt.datetime.now():%H:%M:%S}] 取得エラー（{consecutive_errors}回連続）: {e}")
                if consecutive_errors >= 5:
                    # 連続エラー時は少し長めに待って負荷をかけすぎないようにする
                    time.sleep(min(args.interval * 4, 60))
                    continue

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n監視を停止しました。")


if __name__ == "__main__":
    main()
