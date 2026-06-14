"""MimicMotion の新しい torchvision 互換パッチ"""
from pathlib import Path

BASE = Path(__file__).parent
MIMIC_DIR = BASE / "MimicMotion"

utils_path = MIMIC_DIR / "mimicmotion" / "utils" / "utils.py"
if not utils_path.exists():
    print("エラー: MimicMotion が見つかりません。setup_mimicmotion.py を先に実行してください。")
    exit(1)

text = utils_path.read_text(encoding="utf-8")

if "imageio" not in text:
    text = text.replace(
        "from torchvision.io import write_video",
        "import imageio\nimport numpy as _np"
    )
    # write_video(path, frames, fps) の呼び出しを置き換え
    # MimicMotion では通常 save_to_mp4 関数内で使われる
    text = text.replace(
        "write_video(",
        "_write_video_imageio("
    )
    # ヘルパー関数を追加
    helper = '''

def _write_video_imageio(filename, video_array, fps, **kwargs):
    """torchvision.write_video の代替実装"""
    import imageio
    import numpy as _np
    if hasattr(video_array, 'numpy'):
        frames = video_array.numpy()
    else:
        frames = _np.array(video_array)
    if frames.dtype != _np.uint8:
        frames = (frames * 255).clip(0, 255).astype(_np.uint8)
    writer = imageio.get_writer(str(filename), fps=fps, codec='libx264', quality=8)
    for frame in frames:
        writer.append_data(frame)
    writer.close()

'''
    # ファイルの先頭のimportの後に追加
    text = text + helper

    utils_path.write_text(text, encoding="utf-8")
    print(f"パッチ適用: {utils_path}")
else:
    print("すでにパッチ済みです")
