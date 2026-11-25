import glob
import json
import os
import re
import subprocess
from faster_whisper import WhisperModel

RAW_DIR = os.path.abspath("vault/raw")
TRANS_DIR = os.path.abspath("vault/transcripts")
FRAMES_DIR = os.path.abspath("vault/frames")


def probe_duration(mp4_path: str) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            mp4_path,
        ],
        text=True,
    ).strip()
    return float(out)


def detect_scene_cuts(mp4_path: str, out_dir: str, total_dur: float) -> list[dict]:
    """Uses ffmpeg scene detection to extract exact cut timestamps and keyframes."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        "ffmpeg", "-v", "info", "-y", "-i", mp4_path,
        "-vf", "select='eq(n,3)+gt(scene,0.28)',showinfo,scale=540:-2",
        "-vsync", "vfr",
        "-q:v", "4",
        os.path.join(out_dir, "cut_%03d.jpg"),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    timestamps = []
    for line in res.stderr.splitlines():
        if "pts_time:" in line:
            m = re.search(r"pts_time:([0-9.]+)", line)
            if m:
                timestamps.append(round(float(m.group(1)), 3))

    if not timestamps or timestamps[0] > 0.3:
        timestamps.insert(0, 0.0)

    clean_ts = [timestamps[0]]
    for t in timestamps[1:]:
        if t - clean_ts[-1] >= 0.45:
            clean_ts.append(t)

    cuts = []
    for idx, t0 in enumerate(clean_ts):
        t1 = clean_ts[idx + 1] if idx + 1 < len(clean_ts) else round(total_dur, 3)
        img_name = f"cut_{idx + 1:03d}.jpg"
        cuts.append({
            "cut_index": idx,
            "t0": t0,
            "t1": t1,
            "dur": round(t1 - t0, 3),
            "frame": img_name if os.path.exists(os.path.join(out_dir, img_name)) else None,
        })
    return cuts


def transcribe_video(model: WhisperModel, mp4_path: str, total_dur: float) -> dict:
    wav_tmp = mp4_path + ".16k.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", mp4_path, "-ac", "1", "-ar", "16000", wav_tmp],
        check=True,
    )
    segments, _ = model.transcribe(wav_tmp, word_timestamps=True, vad_filter=True)
    words = []
    full_parts = []
    for seg in segments:
        full_parts.append(seg.text.strip())
        for w in seg.words or []:
            words.append([w.word.strip(), round(w.start, 3), round(w.end, 3)])

    if os.path.exists(wav_tmp):
        os.remove(wav_tmp)

    full_text = " ".join(full_parts).strip()
    wps = round(len(words) / max(total_dur, 0.1), 2)
    return {
        "duration": round(total_dur, 3),
        "word_count": len(words),
        "words_per_sec": wps,
        "text": full_text,
        "words": words,
    }


def main():
    os.makedirs(TRANS_DIR, exist_ok=True)
    os.makedirs(FRAMES_DIR, exist_ok=True)

    mp4_files = sorted(glob.glob(os.path.join(RAW_DIR, "*.mp4")))
    if not mp4_files:
        print("[Extract] No MP4 files in vault/raw.", flush=True)
        return

    model = None
    for mp4 in mp4_files:
        vid = os.path.splitext(os.path.basename(mp4))[0]
        trans_path = os.path.join(TRANS_DIR, f"{vid}.json")
        cuts_path = os.path.join(FRAMES_DIR, vid, "cuts.json")

        if os.path.exists(trans_path) and os.path.exists(cuts_path):
            continue

        if model is None:
            print("[Whisper] Loading faster-whisper base.en on CPU...", flush=True)
            model = WhisperModel("base.en", device="cpu", compute_type="int8")

        dur = probe_duration(mp4)
        print(f"[Extract] Processing {vid} ({dur:.1f}s)...", flush=True)

        tr = transcribe_video(model, mp4, dur)
        with open(trans_path, "w", encoding="utf-8") as f:
            json.dump(tr, f, indent=2)

        cuts = detect_scene_cuts(mp4, os.path.join(FRAMES_DIR, vid), dur)
        with open(cuts_path, "w", encoding="utf-8") as f:
            json.dump(cuts, f, indent=2)

        print(f"[Extract] {vid}: {tr['word_count']} words ({tr['words_per_sec']} wps), {len(cuts)} camera cuts.", flush=True)


if __name__ == "__main__":
    main()
