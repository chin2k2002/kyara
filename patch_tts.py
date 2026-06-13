"""TTS の io.py に weights_only=False を追加するパッチ"""
import site
from pathlib import Path

for s in site.getsitepackages():
    io_path = Path(s) / "TTS" / "utils" / "io.py"
    if io_path.exists():
        text = io_path.read_text(encoding="utf-8")
        if "weights_only=False" not in text:
            text = text.replace(
                "return torch.load(f, map_location=map_location, **kwargs)",
                "return torch.load(f, map_location=map_location, weights_only=False, **kwargs)",
            )
            io_path.write_text(text, encoding="utf-8")
            print(f"パッチ適用: {io_path}")
        else:
            print("すでにパッチ済みです")
        break
else:
    print("TTS が見つかりませんでした")
