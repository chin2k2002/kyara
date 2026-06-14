"""
MimicMotion のセットアップスクリプト。
初回のみ実行してください。
"""

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent
MIMIC_DIR = BASE / "MimicMotion"


def run(cmd: str, cwd=None) -> None:
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if result.returncode != 0:
        print(f"エラーが発生しました (code={result.returncode})")
        sys.exit(1)


def hf_download(repo_id: str, local_dir: Path, allow_patterns: list = None) -> None:
    from huggingface_hub import list_repo_files, hf_hub_download

    local_dir.mkdir(parents=True, exist_ok=True)
    files = list(list_repo_files(repo_id))
    if allow_patterns:
        import fnmatch
        files = [f for f in files if any(fnmatch.fnmatch(f, p) for p in allow_patterns)]

    for f in files:
        dest = local_dir / f
        if dest.exists():
            print(f"  スキップ (既存): {f}")
            continue
        print(f"  ダウンロード中: {f}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        hf_hub_download(repo_id=repo_id, filename=f, local_dir=str(local_dir))


def main():
    # 1. MimicMotion をクローン
    if not MIMIC_DIR.exists():
        print("MimicMotion をダウンロード中...")
        run(f'git clone https://github.com/Tencent/MimicMotion "{MIMIC_DIR}"')
    else:
        print("MimicMotion はすでにダウンロード済みです")

    # 2. 依存ライブラリ
    print("\n依存ライブラリをインストール中...")
    run("py -3.11 -m pip install diffusers accelerate omegaconf einops imageio imageio-ffmpeg av onnxruntime huggingface_hub")

    # 3. モデルをダウンロード
    print("\nモデルをダウンロード中...")
    models_dir = MIMIC_DIR / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # MimicMotion checkpoint
    ckpt = models_dir / "MimicMotion_1-1.pth"
    if not ckpt.exists():
        print("  MimicMotion チェックポイントをダウンロード中...")
        from huggingface_hub import hf_hub_download
        hf_hub_download(repo_id="tencent/MimicMotion", filename="MimicMotion_1-1.pth", local_dir=str(models_dir))
    else:
        print("  スキップ (既存): MimicMotion_1-1.pth")

    # DWPose (姿勢推定) - リポジトリの実際のファイル名を確認してダウンロード
    dwpose_dir = models_dir / "DWPose"
    dwpose_dir.mkdir(parents=True, exist_ok=True)
    print("  DWPose モデルをダウンロード中...")
    hf_download("yzd-v/DWPose", dwpose_dir, allow_patterns=["*.onnx"])

    # 参照動画 - MimicMotion の assets から取得
    ref_video = BASE / "presenter_reference.mp4"
    if not ref_video.exists():
        print("\nプレゼン参照動画をダウンロード中...")
        from huggingface_hub import list_repo_files, hf_hub_download
        # assets/demo 以下の mp4 を探す
        demo_files = [f for f in list_repo_files("tencent/MimicMotion") if f.endswith(".mp4")]
        print(f"  利用可能な動画: {demo_files}")
        if demo_files:
            fname = demo_files[0]
            tmp = BASE / fname
            hf_hub_download(repo_id="tencent/MimicMotion", filename=fname, local_dir=str(BASE))
            import shutil
            if tmp.exists():
                shutil.copy2(tmp, ref_video)
                print(f"  参照動画を保存: {ref_video}")
    else:
        print(f"  スキップ (既存): presenter_reference.mp4")

    print("\nセットアップ完了！")
    print("次のコマンドで全身プレゼン動画を生成できます:")
    print('  py -3.11 generate_avatar_video.py --text "セリフ" --photo 写真.jpg --voice_sample 録音.m4a --output output.mp4')


if __name__ == "__main__":
    main()
