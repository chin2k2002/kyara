# 送信前チェッカー（.msg）

Outlook の `.msg` ファイルを読み、送信前に宛先・本文・添付を確認する簡易アプリです。
`.msg` を読むだけで、送信や書き換えはしません。

## インストール

```
pip install -r requirements.txt
```

`pypdf` は任意です（無い場合は PDF の中身チェックだけ省略します）。

## 使い方

```
python msg_checker.py              # GUI で起動
python msg_checker.py A.msg        # GUI で起動してすぐチェック
python msg_checker.py --cli A.msg  # 結果を文字で出力
```

## exe にする（Windows）

`build.bat` をダブルクリックするか、次を実行します。`dist\` に exe ができます。

```
pip install -r requirements.txt pyinstaller
python -m PyInstaller --onefile --windowed --name msg_checker --collect-all extract_msg msg_checker.py
python -m PyInstaller --onefile --console  --name msg_checker_cli --collect-all extract_msg msg_checker.py
```

- `msg_checker.exe`: 画面版。`.msg` をドラッグ＆ドロップしてもチェックできます
- `msg_checker_cli.exe --cli A.msg`: 文字で結果を出すコンソール版
- 設定（`config.json`）は exe と同じフォルダに保存されます

## 主なチェック

- **宛先**: お客様リストにないアドレス、似ているが違うドメイン（打ち間違い）、複数のお客様が混在、Bcc
- **件名・本文**: 空の件名、NG ワード、他のお客様名の混入、仮の文字（〇〇・TBD など）、引用・転送、パスワードの記載、「添付」の書き忘れ／添付忘れ
- **添付**: Office（docx/xlsx/pptx）の変更履歴・コメント・非表示シート/行/スライド・ノート・プロパティ・マクロ、PDF の注釈・メタデータ、ZIP の中身、実行形式、0 バイト
- **パスワード付き添付**: 添付置き場（と `.msg` と同じフォルダ）から同名の元ファイルを探して代わりに確認。パスワード付き ZIP はサイズと CRC で同一か照合

## 設定

GUI で入力した設定は `msg_checker.py` と同じフォルダの `config.json` に保存されます。
お客様リストは手入力（1 行 1 社「ドメイン = お客様名, 別名」）か Excel（「ひな形を作る…」で作成可）で登録します。
