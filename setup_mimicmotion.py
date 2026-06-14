"""
MimicMotion のセットアップスクリプト。
初回のみ実行してください。
"""

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
MIMIC_DIR = BASE / "MimicMotion"


def run(cmd: str, cwd=None) -> None:
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if result.returncode != 0:
        print(f"エラーが発生しました (code={result.returncode})")
        sys.exit(1)


def download(url: str, path: Path) -> None:
    if path.exists():
        print(f"  スキップ (既存): {path.name}")
        return
    print(f"  ダウンロード中: {path.name} ...")
    path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, path)
    print(f"  完了: {path.name}")


def main():
    # 1. MimicMotion をクローン
    if not MIMIC_DIR.exists():
        print("MimicMotion をダウンロード中...")
        run(f'git clone https://github.com/Tencent/MimicMotion "{MIMIC_DIR}"')
    else:
        print("MimicMotion はすでにダウンロード済みです")

    # 2. 依存ライブラリ
    print("\n依存ライブラリをインストール中...")
    run(f'py -3.11 -m pip install diffusers transformers accelerate omegaconf einops imageio imageio-ffmpeg av onnxruntime')
    run(f'py -3.11 -m pip install huggingface_hub diffusers accelerate')

    # 3. モデルをダウンロード
    print("\nモデルをダウンロード中...")
    models_dir = MIMIC_DIR / "models"

    from huggingface_hub import hf_hub_download

    # MimicMotion checkpoint
    models_dir.mkdir(parents=True, exist_ok=True)
    mimic_ckpt = models_dir / "MimicMotion_1-1.pth"
    if not mimic_ckpt.exists():
        print("  MimicMotion モデルをダウンロード中...")
        hf_hub_download(
            repo_id="tencent/MimicMotion",
            filename="MimicMotion_1-1.pth",
            local_dir=str(models_dir),
        )

    # DWPose (姿勢推定)
    dwpose_dir = models_dir / "DWPose"
    dwpose_dir.mkdir(parents=True, exist_ok=True)
    for fname in ["dw-ll_ucoco_384.onnx", "yolox_l.onnx"]:
        if not (dwpose_dir / fname).exists():
            print(f"  DWPose {fname} をダウンロード中...")
            hf_hub_download(
                repo_id="yzd-v/DWPose",
                filename=fname,
                local_dir=str(dwpose_dir),
            )
        else:
            print(f"  スキップ (既存): {fname}")

    # プレゼン参照動画
    ref_video = BASE / "presenter_reference.mp4"
    if not ref_video.exists():
        print("\nプレゼン参照動画をダウンロード中...")
        hf_hub_download(
            repo_id="tencent/MimicMotion",
            filename="assets/demo/demo3.mp4",
            local_dir=str(BASE),
            local_dir_use_symlinks=False,
        )
        import shutil
        demo = BASE / "assets" / "demo" / "demo3.mp4"
        if demo.exists():
            shutil.copy2(demo, ref_video)

    print("\nセットアップ完了！")
    print("次のコマンドで全身プレゼン動画を生成できます:")
    print('  py -3.11 generate_avatar_video.py --text "セリフ" --photo 写真.jpg --voice_sample 録音.m4a --output output.mp4')


if __name__ == "__main__":
    main()
