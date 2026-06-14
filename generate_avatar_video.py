#!/usr/bin/env python3
"""
写真から全身プレゼン動画を自動生成するスクリプト。

使い方:
  py -3.11 generate_avatar_video.py \
    --text "読み上げるテキスト" \
    --photo 写真.jpg \
    --voice_sample 録音ファイル.m4a \
    --output output.mp4

事前に setup_mimicmotion.py を実行してください。
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).parent
MIMIC_DIR = BASE / "MimicMotion"
REF_VIDEO = BASE / "presenter_reference.mp4"


def convert_to_wav(input_path: str) -> str:
    from moviepy import AudioFileClip
    p = Path(input_path)
    if p.suffix.lower() == ".wav":
        return str(p)
    wav = p.with_suffix(".wav")
    clip = AudioFileClip(str(p))
    clip.write_audiofile(str(wav), logger=None)
    clip.close()
    print(f"音声を変換: {wav}")
    return str(wav)


def generate_speech(text: str, voice_sample: str, output_audio: str, language: str = "ja") -> None:
    from TTS.api import TTS
    voice_sample = convert_to_wav(voice_sample)
    print("音声モデルをロード中...")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
    print(f"音声を生成中...")
    tts.tts_to_file(text=text, speaker_wav=voice_sample, language=language, file_path=output_audio)
    print(f"音声を保存: {output_audio}")


def get_audio_duration(audio_path: str) -> float:
    from moviepy import AudioFileClip
    clip = AudioFileClip(audio_path)
    d = clip.duration
    clip.close()
    return d


def generate_avatar(photo: str, audio_duration: float, output_video: str) -> None:
    if not MIMIC_DIR.exists():
        print("エラー: MimicMotion が見つかりません。先に setup_mimicmotion.py を実行してください。")
        sys.exit(1)
    if not REF_VIDEO.exists():
        print("エラー: 参照動画が見つかりません。先に setup_mimicmotion.py を実行してください。")
        sys.exit(1)

    print("全身アバター動画を生成中 (数分かかります)...")
    cmd = [
        sys.executable, "inference.py",
        "--inference_config", "configs/test.yaml",
        "--ref_video_path", str(REF_VIDEO),
        "--ref_image_path", str(Path(photo).resolve()),
        "--save_path", str(Path(output_video).resolve()),
    ]
    result = subprocess.run(cmd, cwd=str(MIMIC_DIR))
    if result.returncode != 0:
        print("MimicMotion の実行に失敗しました")
        sys.exit(1)


def merge_audio(video_path: str, audio_path: str, output_path: str) -> None:
    from moviepy import VideoFileClip, AudioFileClip
    print("音声と動画を合成中...")
    video = VideoFileClip(video_path)
    audio = AudioFileClip(audio_path)
    # 音声の長さに合わせてループまたはトリム
    if video.duration < audio.duration:
        from moviepy import concatenate_videoclips
        loops = int(audio.duration / video.duration) + 1
        video = concatenate_videoclips([video] * loops)
    video = video.subclipped(0, audio.duration).with_audio(audio)
    video.write_videofile(output_path, codec="libx264", audio_codec="aac", logger=None)
    print(f"完了: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="全身プレゼン動画を自動生成")
    parser.add_argument("--text", required=True, help="読み上げるテキスト")
    parser.add_argument("--photo", required=True, help="顔・全身写真 (jpg/png)")
    parser.add_argument("--voice_sample", required=True, help="声のサンプル音声")
    parser.add_argument("--output", default="avatar_output.mp4", help="出力ファイル名")
    parser.add_argument("--language", default="ja", help="言語コード")
    args = parser.parse_args()

    if not Path(args.photo).exists():
        print(f"エラー: 写真が見つかりません: {args.photo}")
        sys.exit(1)
    if not Path(args.voice_sample).exists():
        print(f"エラー: 音声サンプルが見つかりません: {args.voice_sample}")
        sys.exit(1)

    speech_path = str(Path(args.output).with_name("_avatar_speech.wav"))
    avatar_path = str(Path(args.output).with_name("_avatar_raw.mp4"))

    generate_speech(args.text, args.voice_sample, speech_path, args.language)
    duration = get_audio_duration(speech_path)
    print(f"音声の長さ: {duration:.1f}秒")

    generate_avatar(args.photo, duration, avatar_path)
    merge_audio(avatar_path, speech_path, args.output)


if __name__ == "__main__":
    main()
