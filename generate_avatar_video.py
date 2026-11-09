#!/usr/bin/env python3
"""
写真から全身プレゼン動画を自動生成するスクリプト。

使い方:
  py -3.11 generate_avatar_video.py \
    --text "読み上げるテキスト" \
    --photo 写真.jpg \
    --voice_sample 録音ファイル.m4a \
    --output output.mp4

自分の動きで動かす（RGB モーションキャプチャ）:
  # 生成した音声を流しながら Web カメラで動きを収録し、その動きでアバターを動かす
  py -3.11 generate_avatar_video.py --text "..." --photo 写真.jpg --voice_sample 録音.m4a --mocap

  # 撮影済みの自分の動画（普通の RGB 動画）の動きを使う
  py -3.11 generate_avatar_video.py --text "..." --photo 写真.jpg --voice_sample 録音.m4a \
    --motion_video 自撮り動画.mp4

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
REF_VIDEO_FALLBACK = BASE / "MimicMotion" / "assets" / "example_data" / "videos" / "pose1.mp4"


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


def play_audio_async(audio_path: str):
    """収録中に音声を流す（ベストエフォート）。停止用の関数を返す。"""
    import platform
    import shutil
    if platform.system() == "Windows":
        import winsound
        winsound.PlaySound(audio_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        return lambda: winsound.PlaySound(None, 0)
    for player in (["afplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["aplay", "-q"]):
        if shutil.which(player[0]):
            proc = subprocess.Popen(player + [audio_path])
            return proc.terminate
    print("(音声プレーヤーが見つからないため、音声なしで収録します)")
    return lambda: None


def prepare_motion(args, speech_path: str, duration: float, work_dir: Path) -> Path | None:
    """--mocap / --motion_video 指定時、RGB モーションキャプチャで参照動画を作る。"""
    if not (args.mocap or args.motion_video):
        return None
    import rgb_mocap

    motion_path = work_dir / "_avatar_motion.mp4"
    try:
        if args.mocap:
            print(f"\nWeb カメラで動きを収録します（{duration:.1f} 秒）。"
                  "カウントダウン後、流れる音声に合わせて身振りをしてください。")
            stop = [lambda: None]
            def on_start():
                stop[0] = play_audio_async(speech_path)
            try:
                summary = rgb_mocap.capture_webcam(motion_path, camera=args.camera, duration=duration,
                                                   countdown=args.countdown, complexity=args.mocap_model,
                                                   on_start=on_start)
            finally:
                stop[0]()
        else:
            print(f"\nモーション動画を解析中: {args.motion_video}")
            summary = rgb_mocap.process_video(args.motion_video, motion_path, complexity=args.mocap_model,
                                              max_duration=duration)
    except RuntimeError as e:
        print(f"エラー: {e}")
        sys.exit(1)
    rgb_mocap.report(summary)
    if summary["detection_rate"] == 0:
        print("エラー: モーション動画から人物を検出できませんでした")
        sys.exit(1)
    return motion_path


def generate_avatar(photo: str, audio_duration: float, output_video: str, motion_video: Path | None = None) -> None:
    if not MIMIC_DIR.exists():
        print("エラー: MimicMotion が見つかりません。先に setup_mimicmotion.py を実行してください。")
        sys.exit(1)
    if motion_video is not None:
        ref_video = Path(motion_video).resolve()  # RGB モーションキャプチャで作った参照動画 (30fps)
    else:
        ref_video = REF_VIDEO if REF_VIDEO.exists() else REF_VIDEO_FALLBACK
    if not ref_video.exists():
        print("エラー: 参照動画が見つかりません。先に setup_mimicmotion.py を実行してください。")
        sys.exit(1)
    print(f"参照動画: {ref_video}")

    # 設定ファイルを動的に生成
    num_frames = max(72, int(audio_duration * 15) + 10)
    config_content = f"""base_model_path: stabilityai/stable-video-diffusion-img2vid-xt-1-1
ckpt_path: models/MimicMotion_1-1.pth

test_case:
  - ref_video_path: {str(ref_video).replace(chr(92), '/')}
    ref_image_path: {str(Path(photo).resolve()).replace(chr(92), '/')}
    num_frames: {num_frames}
    resolution: 576
    frames_overlap: 6
    num_inference_steps: 25
    noise_aug_strength: 0
    guidance_scale: 2.0
    sample_stride: 2
    fps: 15
    seed: 42
"""
    config_path = MIMIC_DIR / "configs" / "inference_tmp.yaml"
    config_path.write_text(config_content, encoding="utf-8")

    print("全身アバター動画を生成中 (数分かかります)...")
    output_dir = Path(output_video).parent / "_mimic_output"
    cmd = [
        sys.executable, "inference.py",
        "--inference_config", "configs/inference_tmp.yaml",
        "--output_dir", str(output_dir),
    ]
    result = subprocess.run(cmd, cwd=str(MIMIC_DIR))
    if result.returncode != 0:
        print("MimicMotion の実行に失敗しました")
        sys.exit(1)

    # 生成された動画を output_video にコピー
    import glob, shutil
    generated = sorted(glob.glob(str(output_dir / "**" / "*.mp4"), recursive=True))
    if generated:
        shutil.copy2(generated[-1], output_video)
        print(f"アバター動画を保存: {output_video}")
    else:
        print("生成された動画が見つかりませんでした")
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
    motion = parser.add_mutually_exclusive_group()
    motion.add_argument("--mocap", action="store_true",
                        help="Web カメラ (RGB) で自分の動きを収録してアバターを動かす")
    motion.add_argument("--motion_video", help="自分の動きを撮影した RGB 動画を参照モーションに使う")
    parser.add_argument("--camera", type=int, default=0, help="--mocap で使うカメラ番号")
    parser.add_argument("--countdown", type=int, default=3, help="--mocap の収録前カウントダウン秒数")
    parser.add_argument("--mocap_model", choices=["lite", "full", "heavy"], default="full",
                        help="モーションキャプチャの姿勢推定モデル")
    args = parser.parse_args()

    if args.motion_video and not Path(args.motion_video).exists():
        print(f"エラー: モーション動画が見つかりません: {args.motion_video}")
        sys.exit(1)

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

    motion_path = prepare_motion(args, speech_path, duration, Path(args.output).resolve().parent)
    generate_avatar(args.photo, duration, avatar_path, motion_path)
    merge_audio(avatar_path, speech_path, args.output)


if __name__ == "__main__":
    main()
