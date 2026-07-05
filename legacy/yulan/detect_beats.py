"""
yulan step 4: BGM 节拍检测
- 输入：bgm.mp3
- 输出：beats.json（节拍时间戳列表 + BPM）
"""
import json
import sys
import sys as _sys
from pathlib import Path

try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import librosa
import numpy as np

ROOT = Path(__file__).parent
BGM = ROOT / "bgm.mp3"
OUT = ROOT / "beats.json"


def main():
    y, sr = librosa.load(str(BGM))
    result = librosa.beat.beat_track(y=y, sr=sr)
    tempo = result[0] if isinstance(result, tuple) else result
    beats_frames = result[1] if isinstance(result, tuple) and len(result) > 1 else None
    if hasattr(tempo, "__len__"):
        tempo = float(tempo[0]) if len(tempo) > 0 else 0
    else:
        tempo = float(tempo)
    beat_times = librosa.frames_to_time(beats_frames, sr=sr).tolist() if beats_frames is not None else []

    data = {
        "bpm": round(tempo, 2),
        "beat_count": len(beat_times),
        "duration_sec": round(len(y) / sr, 2),
        "beat_times": [round(b, 3) for b in beat_times],
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[beats] BPM={data['bpm']}, {data['beat_count']} beats in {data['duration_sec']}s")
    print(f"[beats] 输出: {OUT.name}")


if __name__ == "__main__":
    main()
