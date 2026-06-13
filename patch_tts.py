"""TTS ライブラリの互換性パッチ"""
import site
from pathlib import Path


def patch_io(site_path: Path) -> None:
    io_path = site_path / "TTS" / "utils" / "io.py"
    if not io_path.exists():
        return
    text = io_path.read_text(encoding="utf-8")
    if "weights_only=False" not in text:
        text = text.replace(
            "return torch.load(f, map_location=map_location, **kwargs)",
            "return torch.load(f, map_location=map_location, weights_only=False, **kwargs)",
        )
        io_path.write_text(text, encoding="utf-8")
        print(f"パッチ適用: {io_path}")
    else:
        print(f"io.py: 適用済み")


def patch_load_audio(site_path: Path) -> None:
    """torchaudio.load を soundfile で代替する。"""
    xtts_path = site_path / "TTS" / "tts" / "models" / "xtts.py"
    if not xtts_path.exists():
        return
    text = xtts_path.read_text(encoding="utf-8")
    old = "    audio, lsr = torchaudio.load(audiopath)"
    new = (
        "    import soundfile as sf, numpy as _np, torch as _torch\n"
        "    _data, lsr = sf.read(audiopath, dtype='float32', always_2d=True)\n"
        "    audio = _torch.from_numpy(_data.T)"
    )
    if old in text and "import soundfile" not in text:
        text = text.replace(old, new)
        xtts_path.write_text(text, encoding="utf-8")
        print(f"パッチ適用: {xtts_path}")
    else:
        print(f"xtts.py: 適用済みまたは対象なし")


for s in site.getsitepackages():
    p = Path(s)
    if (p / "TTS").exists():
        patch_io(p)
        patch_load_audio(p)
        break
else:
    print("TTS が見つかりませんでした")
