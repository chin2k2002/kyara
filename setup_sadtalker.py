"""
SadTalker のセットアップスクリプト。
初回のみ実行してください。
"""

import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent
SADTALKER_DIR = BASE / "SadTalker"


def run(cmd: str, cwd=None) -> None:
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if result.returncode != 0:
        print(f"エラーが発生しました (code={result.returncode})")
        sys.exit(1)


def main():
    # 1. SadTalker をクローン
    if not SADTALKER_DIR.exists():
        print("SadTalker をダウンロード中...")
        run(f'git clone https://github.com/OpenTalker/SadTalker "{SADTALKER_DIR}"')
    else:
        print("SadTalker はすでにダウンロード済みです")

    # 2. 依存ライブラリをインストール
    print("\n依存ライブラリをインストール中...")
    run(f'py -3.11 -m pip install face_alignment dlib gfpgan realesrgan pydub')
    run(f'py -3.11 -m pip install -r "{SADTALKER_DIR / "requirements.txt"}"')

    # 3. モデルをダウンロード
    print("\nモデルをダウンロード中 (数分かかります)...")
    checkpoint_dir = SADTALKER_DIR / "checkpoints"
    gfpgan_dir = SADTALKER_DIR / "gfpgan" / "weights"
    checkpoint_dir.mkdir(exist_ok=True)
    gfpgan_dir.mkdir(parents=True, exist_ok=True)

    models = {
        checkpoint_dir / "SadTalker_V0.0.2_256.safetensors":
            "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/SadTalker_V0.0.2_256.safetensors",
        checkpoint_dir / "SadTalker_V0.0.2_512.safetensors":
            "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/SadTalker_V0.0.2_512.safetensors",
        checkpoint_dir / "mapping_00109-model.pth.tar":
            "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/mapping_00109-model.pth.tar",
        checkpoint_dir / "mapping_00229-model.pth.tar":
            "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/mapping_00229-model.pth.tar",
        gfpgan_dir / "alignment_WFLW_4HG.pth":
            "https://github.com/xinntao/facexlib/releases/download/v0.1.0/alignment_WFLW_4HG.pth",
        gfpgan_dir / "detection_Resnet50_Final.pth":
            "https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth",
        gfpgan_dir / "GFPGANv1.4.pth":
            "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth",
        gfpgan_dir / "RestoreFormer.pth":
            "https://github.com/wzhouxiff/RestoreFormer/releases/download/v1.0.0/RestoreFormer.pth",
    }

    import urllib.request
    for path, url in models.items():
        if path.exists():
            print(f"  スキップ (既存): {path.name}")
            continue
        print(f"  ダウンロード中: {path.name}")
        urllib.request.urlretrieve(url, path)

    print("\nセットアップ完了！")
    print("次のコマンドで動画を生成できます:")
    print('  py -3.11 generate_talking_video.py --text "セリフ" --photo 写真.jpg --voice_sample 録音.m4a --output output.mp4')


if __name__ == "__main__":
    main()
