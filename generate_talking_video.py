#!/usr/bin/env python3
"""
自分の顔写真と声で喋る動画を生成するスクリプト。

使い方:
  py -3.11 generate_talking_video.py \
    --text "おーれーは、じゃいあーーーん！" \
    --photo 写真.jpg \
    --voice_sample 録音ファイル.m4a \
    --output output.mp4

事前に setup_sadtalker.py を実行してください。
"""

import argparse
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent
SADTALKER_DIR = BASE / "SadTalker"


def convert_to_wav(input_path: str) -> str:
    from moviepy import AudioFileClip
    input_path = Path(input_path)
    if input_path.suffix.lower() == ".wav":
        return str(input_path)
    wav_path = input_path.with_suffix(".wav")
    clip = AudioFileClip(str(input_path))
    clip.write_audiofile(str(wav_path), logger=None)
    clip.close()
    print(f"音声を変換しました: {wav_path}")
    return str(wav_path)


def generate_speech(text: str, voice_sample: str, output_audio: str, language: str = "ja") -> None:
    from TTS.api import TTS
    voice_sample = convert_to_wav(voice_sample)
    print("音声モデルをロード中...")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
    print(f"音声を生成中: {text[:30]}...")
    tts.tts_to_file(
        text=text,
        speaker_wav=voice_sample,
        language=language,
        file_path=output_audio,
    )
    print(f"音声を保存: {output_audio}")


def generate_talking_video(photo: str, audio: str, output: str, size: int = 256) -> None:
    if not SADTALKER_DIR.exists():
        print("エラー: SadTalker が見つかりません。先に setup_sadtalker.py を実行してください。")
        sys.exit(1)

    result_dir = BASE / "results"
    result_dir.mkdir(exist_ok=True)

    cmd = [
        sys.executable,
        str(SADTALKER_DIR / "inference.py"),
        "--driven_audio", audio,
        "--source_image", photo,
        "--result_dir", str(result_dir),
        "--still",
        "--preprocess", "full",
        "--size", str(size),
    ]

    print("顔アニメーションを生成中 (数分かかります)...")
    result = subprocess.run(cmd, cwd=str(SADTALKER_DIR))

    if result.returncode != 0:
        print("SadTalker の実行に失敗しました")
        sys.exit(1)

    # SadTalker が出力した mp4 を output にコピー
    import shutil, glob
    generated = sorted(glob.glob(str(result_dir / "**" / "*.mp4"), recursive=True))
    if generated:
        shutil.copy2(generated[-1], output)
        print(f"完了: {output}")
    else:
        print("動画ファイルが見つかりませんでした")


def main():
    parser = argparse.ArgumentParser(description="顔写真と声で喋る動画を生成")
    parser.add_argument("--text", required=True, help="読み上げるテキスト")
    parser.add_argument("--photo", required=True, help="顔写真ファイル (jpg/png)")
    parser.add_argument("--voice_sample", required=True, help="声のサンプル音声 (wav/m4a)")
    parser.add_argument("--output", default="talking_output.mp4", help="出力動画ファイル名")
    parser.add_argument("--language", default="ja", help="言語コード")
    parser.add_argument("--size", default=256, type=int, choices=[256, 512], help="生成解像度")
    args = parser.parse_args()

    if not Path(args.photo).exists():
        print(f"エラー: 写真が見つかりません: {args.photo}")
        sys.exit(1)
    if not Path(args.voice_sample).exists():
        print(f"エラー: 音声サンプルが見つかりません: {args.voice_sample}")
        sys.exit(1)

    audio_path = Path(args.output).with_name("_generated_speech.wav")
    generate_speech(args.text, args.voice_sample, str(audio_path), args.language)
    generate_talking_video(args.photo, str(audio_path), args.output, args.size)


if __name__ == "__main__":
    main()
