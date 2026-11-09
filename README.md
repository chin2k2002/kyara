# Kyara — 自分の声でテキストを読み上げる動画生成ツール

自分の声のサンプル音声から声をクローニングし、任意のテキストを読み上げる動画を生成します。

## 仕組み

- **XTTS-v2**（Coqui TTS）: 3〜30秒の音声サンプルから声をクローニングしてテキストを読み上げ（日本語対応）
- **moviepy**: 生成した音声 + テキスト字幕を合成して動画を生成

## Windows 版（アプリ）

[toyxyz/toyxyz_RGBMocap](https://github.com/toyxyz/toyxyz_RGBMocap) と同じく、
PC に Python や Git を入れなくても、このフォルダの中だけで完結して動きます。

### インストール

1. このリポジトリを ZIP でダウンロードして展開します（GitHub の「Code」→「Download ZIP」）。
   `C:\kyara` のように、日本語やスペースを含まない短いパスに置くと安全です。
   git を使う場合は `git clone` でも構いません（`update.cmd` で更新できます）。
2. `install.cmd` をダブルクリックします。次のものが **このフォルダ内** に入ります。
   - `.setup\` … uv（パッケージ管理ツール）と専用の Python 3.11
   - `runtime\` … アプリ用の Python 環境とライブラリ一式（PyTorch は NVIDIA GPU があれば GPU 版）
   - `models\` … 姿勢推定モデル
   - 最後に MimicMotion（アバター動画用、約 15GB）を入れるか聞かれます。あとでアプリからも導入できます。
3. `Kyara.cmd` をダブルクリックするとアプリが起動します。

> インストール後にフォルダを移動すると `runtime\` が動かなくなります。その場合は `install.cmd` をもう一度実行してください。

### アプリの使い方

| タブ | できること |
|---|---|
| モーション収録 | Web カメラで収録 / 動画ファイルからモーション抽出。お手本動画を指定すると、横に並べて表示しながら収録（お手本の長さで自動収録） |
| アバター動画 | セリフ・写真・声のサンプルを指定して生成。動きは「既定」「Web カメラで収録」「動画の動きを使う」から選択 |
| セットアップ | Python / GPU / mediapipe / MimicMotion の状態確認、MimicMotion の導入 |

ログは画面下に表示されます。入力した内容は `kyara_settings.json` に保存され、次回起動時に復元されます。

### その他のファイル

| ファイル | 内容 |
|---|---|
| `update.cmd` | 最新版に更新（git clone した場合） |
| `guide_mocap.bat` | お手本動画をドラッグ＆ドロップ → お手本を見ながら収録 |
| `mocap.bat` / `avatar.bat` | コマンドラインで使う場合 |

## 環境構築（手動）

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

## RGB モーションキャプチャ（自分の動きでアバターを動かす）

深度センサーやマーカーは不要で、普通の Web カメラや撮影済みの動画（RGB）から
MediaPipe Pose で全身の姿勢を推定し、その動きでアバター（MimicMotion）を動かせます。

### 音声に合わせて Web カメラで収録 → アバター動画を生成

```bash
py -3.11 generate_avatar_video.py --text "セリフ" --photo 写真.jpg --voice_sample 録音.m4a --mocap
```

生成された音声の長さぶん、カウントダウン後に自動で収録されます（収録中は生成音声が流れるので、
それに合わせて身振りをしてください）。

### 撮影済みの自分の動画を使う

```bash
py -3.11 generate_avatar_video.py --text "セリフ" --photo 写真.jpg --voice_sample 録音.m4a --motion_video 自撮り動画.mp4
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--mocap` | Web カメラで動きを収録して使う | false |
| `--motion_video` | 自分の動きを撮影した動画を使う | - |
| `--camera` | カメラ番号 | `0` |
| `--countdown` | 収録前のカウントダウン秒数 | `3` |
| `--guide` | `--mocap` 収録中に横に表示するお手本動画 | - |
| `--mirror_guide` | お手本を左右反転して表示 | false |
| `--motion_start` | `--motion_video` / `--guide` の何秒目から使うか | `0` |
| `--mocap_model` | 姿勢推定モデル（`lite` / `full` / `heavy`） | `full` |

### モーションだけを収録・抽出する

```bash
# Web カメラ（SPACE で開始/停止、Q/ESC で終了）
py -3.11 rgb_mocap.py --camera 0 --output my_motion.mp4

# 10 秒間を自動収録
py -3.11 rgb_mocap.py --camera 0 --duration 10 --output my_motion.mp4

# 撮影済み動画から抽出（骨格だけの確認用動画も出力）
py -3.11 rgb_mocap.py --input 自撮り動画.mp4 --output my_motion.mp4 --skeleton_video
```

### お手本動画の動きを取り入れる

映画やゲームの映像、ダンス動画などは、カット割り・アップ・複数人物・エフェクトが多く、
そのままではモーションとしてきれいに取り出せないことがほとんどです。
その場合は、お手本動画を横に流しながら自分で同じ動きを演じて収録してください。

```bash
# お手本の長さぶん自動収録（--start で何秒目からかを指定、--mirror_guide で鏡表示）
py -3.11 rgb_mocap.py --camera 0 --guide お手本.mov --output my_motion.mp4

# 音声生成 → お手本を見ながら収録 → アバター動画 まで一括で
py -3.11 generate_avatar_video.py --text "セリフ" --photo 写真.jpg --voice_sample 録音.m4a --mocap --guide お手本.mov
```

人物の全身が 1 カットで映り続けている動画であれば、区間を指定して直接使うこともできます。

```bash
py -3.11 generate_avatar_video.py ... --motion_video お手本.mp4 --motion_start 1.2
```

出力ファイル:

- `my_motion.mp4` — 30fps に揃えたモーション参照動画（`--motion_video` にそのまま渡せます）
- `my_motion_pose.json` — フレームごとの 33 点ランドマーク（画像座標 + 3D ワールド座標）。他ツールでの利用向け
- `my_motion_skeleton.mp4` — 骨格のみの確認用動画（`--skeleton_video` 指定時）

撮影のコツ: 頭から足まで全身が映るようにカメラから離れ、明るい場所で、背景と服の色が近すぎないようにしてください。
初回実行時に姿勢推定モデル（数 MB〜30MB）を `models/` に自動ダウンロードします。
