import glob
import json
import math
import os
import re
import subprocess
from PIL import Image
from faster_whisper import WhisperModel

RAW_DIR = os.path.abspath("vault/raw")
TRANS_DIR = os.path.abspath("vault/transcripts")
FRAMES_DIR = os.path.abspath("vault/frames")
CORPUS_PATH = os.path.abspath("vault/master_script_corpus.json")


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


def build_contact_sheet(frame_paths: list[str], out_path: str, cols: int = 4, thumb_w: int = 270, thumb_h: int = 480) -> str | None:
    """Stitches up to 20 keyframes into a single high-res contact sheet so Gemini Vision can inspect 20 shots at once."""
    selected = frame_paths[:20]
    if not selected:
        return None
    rows = math.ceil(len(selected) / cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), (18, 18, 22))
    for idx, fp in enumerate(selected):
        try:
            with Image.open(fp) as im:
                im_resized = im.convert("RGB").resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
                r, c = divmod(idx, cols)
                sheet.paste(im_resized, (c * thumb_w, r * thumb_h))
        except Exception:
            continue
    sheet.save(out_path, "JPEG", quality=85)
    return out_path


def extract_massive_frames_and_cuts(mp4_path: str, out_dir: str, total_dur: float) -> list[dict]:
    """Extracts 4-fps dense frames (~200+ frames/video -> thousands across vault) + exact scene cuts + contact sheet."""
    os.makedirs(out_dir, exist_ok=True)

    # 1. Dense frame extraction: 4 frames per second (every 0.25s) across the entire video
    dense_cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", mp4_path,
        "-vf", "fps=4,scale=540:-2",
        "-q:v", "4",
        os.path.join(out_dir, "frame_%04d.jpg"),
    ]
    subprocess.run(dense_cmd, check=True)

    # 2. Exact camera cut detection (scene change threshold 0.22)
    cut_cmd = [
        "ffmpeg", "-v", "info", "-y", "-i", mp4_path,
        "-vf", "select='eq(n,2)+gt(scene,0.22)',showinfo,scale=540:-2",
        "-vsync", "vfr",
        "-q:v", "3",
        os.path.join(out_dir, "cut_%03d.jpg"),
    ]
    res = subprocess.run(cut_cmd, capture_output=True, text=True, check=True)
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
        if t - clean_ts[-1] >= 0.35:
            clean_ts.append(t)

    cuts = []
    cut_imgs = []
    for idx, t0 in enumerate(clean_ts):
        t1 = clean_ts[idx + 1] if idx + 1 < len(clean_ts) else round(total_dur, 3)
        img_name = f"cut_{idx + 1:03d}.jpg"
        full_img = os.path.join(out_dir, img_name)
        exists = os.path.exists(full_img)
        if exists:
            cut_imgs.append(full_img)
        cuts.append({
            "cut_index": idx,
            "t0": t0,
            "t1": t1,
            "dur": round(t1 - t0, 3),
            "frame": img_name if exists else None,
        })

    # Sample evenly across all cuts + dense frames to build a 20-shot visual contact sheet
    if len(cut_imgs) < 16:
        all_dense = sorted(glob.glob(os.path.join(out_dir, "frame_*.jpg")))
        if all_dense:
            step = max(1, len(all_dense) // 20)
            cut_imgs = all_dense[::step][:20]
    elif len(cut_imgs) > 20:
        step = len(cut_imgs) / 20.0
        cut_imgs = [cut_imgs[int(i * step)] for i in range(20)]

    build_contact_sheet(cut_imgs, os.path.join(out_dir, "contact_sheet.jpg"))
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
    hook_words = [w[0] for w in words if w[1] <= 3.5]
    hook_line = " ".join(hook_words).strip() or " ".join(full_text.split()[:12])

    return {
        "duration": round(total_dur, 3),
        "word_count": len(words),
        "words_per_sec": wps,
        "hook_0_to_3s": hook_line,
        "text": full_text,
        "words": words,
    }


def rebuild_master_corpus():
    """Compiles every harvested transcript, hook & frame count into one master training corpus for Gemini."""
    entries = []
    total_words = 0
    total_frames = 0
    for tf in sorted(glob.glob(os.path.join(TRANS_DIR, "*.json"))):
        vid = os.path.splitext(os.path.basename(tf))[0]
        tr = json.load(open(tf, encoding="utf-8"))
        if not tr.get("text"):
            continue
        cuts_file = os.path.join(FRAMES_DIR, vid, "cuts.json")
        cuts = json.load(open(cuts_file, encoding="utf-8")) if os.path.exists(cuts_file) else []
        dense_count = len(glob.glob(os.path.join(FRAMES_DIR, vid, "*.jpg")))
        total_words += tr.get("word_count", 0)
        total_frames += dense_count
        entries.append({
            "id": vid,
            "duration": tr.get("duration", 0),
            "words_per_sec": tr.get("words_per_sec", 0),
            "total_cuts": len(cuts),
            "frames_saved": dense_count,
            "hook_0_to_3s": tr.get("hook_0_to_3s", ""),
            "full_script": tr.get("text", ""),
        })

    corpus = {
        "total_scripts_collected": len(entries),
        "total_words_collected": total_words,
        "total_frames_collected": total_frames,
        "avg_words_per_sec": round(sum(e["words_per_sec"] for e in entries) / max(len(entries), 1), 2),
        "avg_cuts_per_video": round(sum(e["total_cuts"] for e in entries) / max(len(entries), 1), 1),
        "all_hooks": [e["hook_0_to_3s"] for e in entries if e["hook_0_to_3s"]],
        "scripts": entries,
    }
    with open(CORPUS_PATH, "w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2)
    print(
        f"[Corpus] Rebuilt {CORPUS_PATH}: {corpus['total_scripts_collected']} scripts, "
        f"{corpus['total_frames_collected']} total frames, {corpus['total_words_collected']} words.",
        flush=True,
    )


def main():
    os.makedirs(TRANS_DIR, exist_ok=True)
    os.makedirs(FRAMES_DIR, exist_ok=True)

    mp4_files = sorted(glob.glob(os.path.join(RAW_DIR, "*.mp4")))
    model = None

    for mp4 in mp4_files:
        vid = os.path.splitext(os.path.basename(mp4))[0]
        trans_path = os.path.join(TRANS_DIR, f"{vid}.json")
        cuts_path = os.path.join(FRAMES_DIR, vid, "cuts.json")
        dense_frames = glob.glob(os.path.join(FRAMES_DIR, vid, "frame_*.jpg"))

        if os.path.exists(trans_path) and os.path.exists(cuts_path) and len(dense_frames) >= 10:
            continue

        if model is None:
            print("[Whisper] Loading faster-whisper base.en on CPU...", flush=True)
            model = WhisperModel("base.en", device="cpu", compute_type="int8")

        dur = probe_duration(mp4)
        print(f"[Extract] Processing {vid} ({dur:.1f}s)...", flush=True)

        tr = transcribe_video(model, mp4, dur)
        with open(trans_path, "w", encoding="utf-8") as f:
            json.dump(tr, f, indent=2)

        cuts = extract_massive_frames_and_cuts(mp4, os.path.join(FRAMES_DIR, vid), dur)
        with open(cuts_path, "w", encoding="utf-8") as f:
            json.dump(cuts, f, indent=2)

        frame_total = len(glob.glob(os.path.join(FRAMES_DIR, vid, "*.jpg")))
        print(
            f"[Extract] {vid}: {tr['word_count']} words ({tr['words_per_sec']} wps), "
            f"{len(cuts)} cuts, {frame_total} total frames saved.",
            flush=True,
        )

    rebuild_master_corpus()


if __name__ == "__main__":
    main()
