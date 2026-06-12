# Kyara — 自分の声でテキストを読み上げる動画生成ツール

自分の声のサンプル音声から声をクローニングし、任意のテキストを読み上げる動画を生成します。

## 仕組み

- **XTTS-v2**（Coqui TTS）: 3〜30秒の音声サンプルから声をクローニングしてテキストを読み上げ（日本語対応）
- **moviepy**: 生成した音声 + テキスト字幕を合成して動画を生成

## 環境構築

```bash
pip install -r requirements.txt
```

> GPU（CUDA）があると生成が高速になりますが、CPUのみでも動作します。

## 使い方

### 1. 声のサンプルを用意する

自分の声を 3〜30秒 録音した WAV ファイルを用意してください（ノイズが少ない環境で録音推奨）。

### 2. 動画を生成する

```bash
python generate_video.py \
  --text "こんにちは、これは私の声で生成した音声です。" \
  --voice_sample my_voice.wav \
  --output output.mp4
```

### オプション

| オプション | 説明 | デフォルト |
|---|---|---|
| `--text` | 読み上げるテキスト（必須） | - |
| `--voice_sample` | 声のサンプル音声ファイル（必須） | - |
| `--output` | 出力ファイル名 | `output.mp4` |
| `--language` | 言語コード | `ja` |
| `--audio_only` | 音声ファイルのみ出力（動画なし） | false |

### 音声のみ出力する場合

```bash
python generate_video.py \
  --text "読み上げたいテキスト" \
  --voice_sample my_voice.wav \
  --output result.wav \
  --audio_only
```

## 初回実行について

初回起動時は XTTS-v2 モデル（約 2GB）を自動ダウンロードします。

## 日本語フォントについて

字幕表示には日本語フォントが必要です。インストールされていない場合はデフォルトフォントで表示されます。

```bash
# Ubuntu/Debian の場合
sudo apt-get install fonts-noto-cjk
```
