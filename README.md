# kyara

指定した曜日・時間帯ごとに、PowerPoint / 動画を自動で全画面再生する Windows 常駐アプリ。
仕様は [docs/SPEC.md](docs/SPEC.md)。

## 使い方 (kyara.exe)
1. kyara.exe を起動。
   - 動画(.mov/.mp4 など)と **PDF** は、PowerPoint なしで再生できる。
   - PowerPoint ファイル(.pptx)は PowerPoint が入った PC でのみ再生できる。
     PowerPoint のない PC では、PowerPoint で「ファイル → エクスポート → PDF」に書き出した PDF を指定する(1 ページが 1 スライド、枠の秒数ごとに送られる)。
2. 「素材フォルダ...」でファイルの置き場所、「既定ファイル...」で空き時間に流すファイルを設定。
3. 週表示の空き枠をドラッグして枠を追加(ファイル・曜日・時間・1 スライドの表示時間)。
   枠はダブルクリックで編集、右クリックで削除。入っている枠は固定で、重ねて登録はできない。
4. ウィンドウを閉じるとタスクトレイに常駐し、再生を続ける。
5. 「Windows 起動時に自動起動」にチェックすると、ログオン時にトレイに入って起動する。
- 全画面再生中にマウスクリック(または Esc)で終了。次のスケジュール切替時刻に自動再開(「停止から再開」で即再開)。
- 設定: `%APPDATA%\kyara\schedule.json` / ログ: `%APPDATA%\kyara\kyara.log`

## exe の作り方
- GitHub Actions の `build-exe` を実行し、成果物 `kyara-exe` を取得する。
- または Windows で `build_exe.bat` を実行(`dist\kyara.exe` ができる)。

## 開発
`python -m pytest -q`(ロジックのテスト)/ `python -m kyara`(GUI 起動)/ `python -m kyara --headless 設定.json`
