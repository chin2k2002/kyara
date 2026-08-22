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

【重要】対象ページはJavaScriptで一覧データを後から描画するタイプのページ
のため、素のHTML取得（requests）では中身が空になります。そのため本スク
リプトは Playwright（headless Chromium）でページを実際にレンダリングして
から内容を読み取ります。

事前準備:
    pip install -r requirements.txt
    playwright install chromium

【解析ロジックについての注意】
- 出品の有無・内容判定は、レンダリング後のページテキストを対象に、
  日付表現・枚数表現をテキストベースで探すヒューリスティックです。
  初回は `--dump-html` オプションでレンダリング後のHTMLを保存し、
  意図通りに検知できているか確認してください。検知漏れ・誤検知が
  あれば、保存したHTMLの該当箇所を教えていただければロジックを調整します。
- 短い間隔（数秒単位）でのアクセスはサイト側の負荷やアクセス制限（bot対策）
  の対象になる可能性があります。まずは長めの間隔（例: 15〜30秒）で動作を
  確認し、問題なければ間隔を調整することを推奨します。
- 本スクリプトは利用者ご自身の環境で、ご自身の責任において実行してください。

使い方:
    python pia_resale_monitor.py
    python pia_resale_monitor.py --interval 10 --date "8/26" --qty "2枚"
    python pia_resale_monitor.py --dump-html
    python pia_resale_monitor.py --show   # ブラウザ画面を表示してデバッグしたい場合
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

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

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

LOG_FILE = Path(__file__).parent / "matches.log"


def notify(title: str, message: str) -> None:
    """デスクトップ通知 + PC音 + コンソール表示。失敗しても落ちないようにする。"""
    print("\a", end="", flush=True)  # ターミナルベル
    print(f"\n{'=' * 60}\n[通知] {title}\n{message}\n{'=' * 60}\n", flush=True)

    try:
        from plyer import notification as plyer_notification

        plyer_notification.notify(title=title, message=message, timeout=15)
    except Exception:
        pass

    if sys.platform.startswith("win"):
        try:
            import winsound

            winsound.Beep(1000, 400)
            winsound.Beep(1400, 400)
        except Exception:
            pass

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
    レンダリング後のHTMLから、日付条件と枚数条件の両方を満たしていそうな
    「かたまり」を探す。

    2段構えのヒューリスティック:
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

    window = 200
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
    parser.add_argument("--interval", type=float, default=20.0, help="ポーリング間隔（秒）。既定20秒。短すぎるとアクセス制限のリスクあり")
    parser.add_argument("--remind-interval", type=float, default=60.0, help="条件成立中に再通知する間隔（秒）")
    parser.add_argument("--render-wait", type=float, default=3.0, help="ページ読込後、JS描画を待つ秒数。既定3秒")
    parser.add_argument("--show", action="store_true", help="ブラウザ画面を表示する（デバッグ用）。既定は非表示(headless)")
    parser.add_argument("--dump-html", action="store_true", help="通知はせず、レンダリング後のHTMLをファイルに保存して終了する（構造確認用）")
    args = parser.parse_args()

    date_variants = normalize_date_variants(args.date)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.show)
        page = browser.new_page(user_agent=USER_AGENT, locale="ja-JP")

        def fetch_rendered_html() -> str:
            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(int(args.render_wait * 1000))
            return page.content()

        if args.dump_html:
            html = fetch_rendered_html()
            out_path = Path(__file__).parent / f"page_dump_{dt.datetime.now():%Y%m%d_%H%M%S}.html"
            out_path.write_text(html, encoding="utf-8")
            print(f"HTMLを保存しました: {out_path}")
            browser.close()
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
                    html = fetch_rendered_html()
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
                        last_notified_at = None

                except (PlaywrightTimeoutError, PlaywrightError) as e:
                    consecutive_errors += 1
                    print(f"[{dt.datetime.now():%H:%M:%S}] 取得エラー（{consecutive_errors}回連続）: {e}")
                    if consecutive_errors >= 5:
                        time.sleep(min(args.interval * 4, 60))
                        continue

                time.sleep(args.interval)

        except KeyboardInterrupt:
            print("\n監視を停止しました。")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
