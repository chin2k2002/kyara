#!/usr/bin/env python3
"""
自分の声でテキストを読み上げる動画を生成するスクリプト。

使い方:
  python generate_video.py \
    --text "こんにちは、これは私の声で生成した音声です。" \
    --voice_sample my_voice.wav \
    --output output.mp4
"""

import argparse
import os
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import AudioFileClip, ImageSequenceClip


def convert_to_wav(input_path: str) -> str:
    """m4a など wav 以外の音声を wav に変換する。"""
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
    """XTTS-v2 で音声クローニングしてテキストを読み上げる。"""
    from TTS.api import TTS

    voice_sample = convert_to_wav(voice_sample)

    print("モデルをロード中... (初回は数分かかる場合があります)")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

    print(f"音声を生成中: {text[:30]}...")
    tts.tts_to_file(
        text=text,
        speaker_wav=voice_sample,
        language=language,
        file_path=output_audio,
    )
    print(f"音声を保存: {output_audio}")


def make_subtitle_frames(
    text: str,
    duration: float,
    fps: int = 24,
    width: int = 1280,
    height: int = 720,
    bg_color: tuple = (20, 20, 20),
    text_color: tuple = (255, 255, 255),
    font_size: int = 48,
) -> list:
    """テキストを表示する静止フレームのリストを生成する。"""
    wrapped = textwrap.fill(text, width=30)

    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # フォント: システムに日本語フォントがあれば使用、なければデフォルト
    font = None
    font_candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    ]
    for path in font_candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except Exception:
                continue

    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), wrapped, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2
    y = (height - text_h) // 2

    draw.text((x, y), wrapped, font=font, fill=text_color)

    frame = np.array(img)
    total_frames = int(duration * fps)
    return [frame] * total_frames


def create_video(text: str, audio_path: str, output_path: str, fps: int = 24) -> None:
    """音声と字幕フレームを合成して動画を生成する。"""
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration

    print(f"フレームを生成中 (duration={duration:.1f}s)...")
    frames = make_subtitle_frames(text, duration=duration, fps=fps)

    video_clip = ImageSequenceClip(frames, fps=fps)
    video_clip = video_clip.set_audio(audio_clip)

    print(f"動画をエンコード中: {output_path}")
    video_clip.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None)
    print(f"完了: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="自分の声でテキストを読み上げる動画を生成")
    parser.add_argument("--text", required=True, help="読み上げるテキスト")
    parser.add_argument("--voice_sample", required=True, help="声のサンプル音声ファイル (wav, 3〜30秒推奨)")
    parser.add_argument("--output", default="output.mp4", help="出力動画ファイル名")
    parser.add_argument("--language", default="ja", help="言語コード (デフォルト: ja)")
    parser.add_argument("--audio_only", action="store_true", help="動画を作らず音声ファイルのみ出力")
    args = parser.parse_args()

    if not Path(args.voice_sample).exists():
        print(f"エラー: 音声サンプルが見つかりません: {args.voice_sample}")
        return

    audio_path = Path(args.output).with_suffix(".wav")

    generate_speech(
        text=args.text,
        voice_sample=args.voice_sample,
        output_audio=str(audio_path),
        language=args.language,
    )

    if args.audio_only:
        print(f"音声ファイルを保存しました: {audio_path}")
        return

    create_video(
        text=args.text,
        audio_path=str(audio_path),
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
