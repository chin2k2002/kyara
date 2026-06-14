"""MimicMotion の新しい torchvision 互換パッチ"""
from pathlib import Path

BASE = Path(__file__).parent
MIMIC_DIR = BASE / "MimicMotion"

if not MIMIC_DIR.exists():
    print("エラー: MimicMotion が見つかりません。setup_mimicmotion.py を先に実行してください。")
    exit(1)

# 1. utils.py: torchvision.write_video → imageio
utils_path = MIMIC_DIR / "mimicmotion" / "utils" / "utils.py"
text = utils_path.read_text(encoding="utf-8")
if "imageio" not in text:
    text = text.replace(
        "from torchvision.io import write_video",
        "import imageio\nimport numpy as _np"
    )
    text = text.replace("write_video(", "_write_video_imageio(")
    text = text + '''

def _write_video_imageio(filename, video_array, fps, **kwargs):
    import imageio, numpy as _np
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
    utils_path.write_text(text, encoding="utf-8")
    print(f"パッチ適用: {utils_path}")
else:
    print(f"utils.py: 適用済み")

# 2. loader.py: safe_globals(*list) → safe_globals(list) + weights_only=False
loader_path = MIMIC_DIR / "mimicmotion" / "utils" / "loader.py"
text = loader_path.read_text(encoding="utf-8")
if "weights_only=False" not in text:
    text = text.replace(
        "with torch.serialization.safe_globals(*allowed_modules):\n            checkpoint = torch.load(infer_config.ckpt_path, map_location=\"cpu\", weights_only=True)",
        "checkpoint = torch.load(infer_config.ckpt_path, map_location=\"cpu\", weights_only=False)"
    )
    # fallback: simpler replacement
    if "weights_only=False" not in text:
        text = text.replace(
            "weights_only=True",
            "weights_only=False"
        )
        text = text.replace(
            "with torch.serialization.safe_globals(*allowed_modules):",
            "if True:"
        )
    loader_path.write_text(text, encoding="utf-8")
    print(f"パッチ適用: {loader_path}")
else:
    print(f"loader.py: 適用済み")

