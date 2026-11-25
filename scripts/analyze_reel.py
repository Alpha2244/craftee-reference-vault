import base64
import glob
import json
import os
import re
import time
import urllib.error
import urllib.request

TRANS_DIR = os.path.abspath("vault/transcripts")
FRAMES_DIR = os.path.abspath("vault/frames")
BLUEPRINT_DIR = os.path.abspath("vault/blueprints")

# Active 2026 Gemini & Gemma multimodal models ordered by free-tier speed & reliability
MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-4-hydrogen",
    "gemini-4-argon",
    "gemini-2.5-flash",
    "gemma-4-31b-it",
]


def extract_json_safely(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def build_offline_blueprint(vid: str, tr: dict, cuts: list[dict]) -> dict:
    """Zero-API deterministic fallback blueprint built directly from Whisper & FFmpeg cut data."""
    avg_cut = round(tr["duration"] / max(len(cuts), 1), 2)
    template = []
    cams = ["mcu", "crash_in", "ws", "low", "ecu", "two", "ms", "ots"]
    moves = ["crash_in", "push", "reveal_push", "creep", "drift", "lock"]
    for idx, c in enumerate(cuts[:24]):
        template.append({
            "beat": "hook" if idx < 2 else ("climax" if idx >= len(cuts) - 3 else "escalation"),
            "target_sec": max(1.2, min(2.4, c.get("dur", 1.7))),
            "cam": cams[idx % len(cams)],
            "move": moves[idx % len(moves)],
            "energy": "high",
        })
    return {
        "reel_id": vid,
        "analysis_mode": "offline_deterministic_fallback",
        "hook_formula": "Immediate 0-3s high-stakes action line with crash-in zoom and rapid visual cut",
        "story_arc": "Fast hook -> rapid escalating micro-beats -> sudden twist -> comedic/dramatic payoff",
        "pacing": {
            "words_per_sec": tr.get("words_per_sec", 3.2),
            "avg_cut_sec": avg_cut,
            "total_cuts": len(cuts),
        },
        "visual_style": {
            "environments_seen": ["MusicRow", "TownPool", "Gym", "Street"],
            "camera_patterns": ["mcu -> crash_in -> ws -> low -> ecu -> two"],
            "lighting_moods": ["sunny", "sunset", "storm"],
            "character_archetypes": [
                {"role": "protagonist", "outfit_style": "vibrant streetwear", "primary_colors": ["#1e73f2", "#141824"]},
                {"role": "rival", "outfit_style": "bold contrast outfit", "primary_colors": ["#eb3840", "#1f2430"]},
            ],
            "visual_gags_and_fx": ["crash_in", "whoosh", "boom", "raincloud", "bolt"],
        },
        "shot_rhythm_template": template,
    }


def call_gemini_vision_defensive(api_key: str, prompt: str, image_paths: list[str]) -> dict:
    image_parts = []
    for p in image_paths[:8]:
        if os.path.exists(p):
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            image_parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    last_err = None
    for model in MODELS:
        # Gemma models work best with text-only if image payload is rejected
        use_images = image_parts if not model.startswith("gemma-") else []
        parts = [{"text": prompt}] + use_images
        gen_cfg = {"temperature": 0.4}
        if not model.startswith("gemma-"):
            gen_cfg["responseMimeType"] = "application/json"

        body = {"contents": [{"parts": parts}], "generationConfig": gen_cfg}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        for attempt in range(2):
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                txt = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = extract_json_safely(txt)
                parsed["model_used"] = model
                return parsed
            except urllib.error.HTTPError as e:
                last_err = f"{model} HTTP {e.code}"
                if e.code == 429 and attempt == 0:
                    print(f"[RateLimit] {model} hit 429; waiting 6s then trying next...", flush=True)
                    time.sleep(6)
                    continue
                break
            except Exception as e:
                last_err = f"{model} {e}"
                break

    raise RuntimeError(f"All models exhausted ({last_err})")


def main():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    os.makedirs(BLUEPRINT_DIR, exist_ok=True)

    trans_files = sorted(glob.glob(os.path.join(TRANS_DIR, "*.json")))
    if not trans_files:
        print("[Analyze] No transcripts found yet; nothing to analyze.", flush=True)
        return

    for trans_file in trans_files:
        vid = os.path.splitext(os.path.basename(trans_file))[0]
        bp_path = os.path.join(BLUEPRINT_DIR, f"{vid}.json")
        if os.path.exists(bp_path):
            continue

        tr = json.load(open(trans_file, encoding="utf-8"))
        cuts_file = os.path.join(FRAMES_DIR, vid, "cuts.json")
        cuts = json.load(open(cuts_file, encoding="utf-8")) if os.path.exists(cuts_file) else []

        frame_files = [
            os.path.join(FRAMES_DIR, vid, c["frame"])
            for c in cuts
            if c.get("frame") and os.path.exists(os.path.join(FRAMES_DIR, vid, c["frame"]))
        ]
        if len(frame_files) > 8:
            step = len(frame_files) / 8.0
            frame_files = [frame_files[int(i * step)] for i in range(8)]

        prompt = f"""Analyze this viral Roblox 3D storytelling Reel from @craftee_films.
TRANSCRIPT ({tr['words_per_sec']} words/sec, {tr['duration']}s total):
"{tr['text']}"

DETECTED CAMERA CUTS ({len(cuts)} cuts):
{json.dumps(cuts[:25])}

Return ONLY valid JSON with:
{{
  "reel_id": "{vid}",
  "hook_formula": "Exact 0-3s psychological hook structure & why it stops scrolling",
  "story_arc": "Beat-by-beat narrative formula (setup -> escalation -> twist/payoff)",
  "pacing": {{
    "words_per_sec": {tr['words_per_sec']},
    "avg_cut_sec": {round(tr['duration'] / max(len(cuts), 1), 2)},
    "total_cuts": {len(cuts)}
  }},
  "visual_style": {{
    "environments_seen": ["list of environments/locations shown across cuts"],
    "camera_patterns": ["sequence of shot sizes & moves: e.g. mcu -> crash_in -> ws -> low -> ecu"],
    "lighting_moods": ["e.g. sunny, sunset, storm, night"],
    "character_archetypes": [
      {{"role": "protagonist", "outfit_style": "description", "primary_colors": ["#hex1", "#hex2"]}}
    ],
    "visual_gags_and_fx": ["lightning bolt, raincloud, smoke, cash, crash zoom, etc."]
  }},
  "shot_rhythm_template": [
    {{"beat": "hook", "target_sec": 1.6, "cam": "mcu", "move": "crash_in", "energy": "high"}}
  ]
}}"""

        print(f"[Analyze] Reverse-engineering {vid}...", flush=True)
        try:
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY empty")
            bp = call_gemini_vision_defensive(api_key, prompt, frame_files)
        except Exception as e:
            print(f"[WARN] Vision fallback engaged for {vid} ({e}); building offline blueprint.", flush=True)
            bp = build_offline_blueprint(vid, tr, cuts)

        bp["source_transcript"] = tr.get("text", "")
        bp["source_words_per_sec"] = tr.get("words_per_sec", 3.0)
        with open(bp_path, "w", encoding="utf-8") as f:
            json.dump(bp, f, indent=2)
        print(f"[Analyze] Saved blueprint: {bp_path} (mode={bp.get('model_used', bp.get('analysis_mode'))})", flush=True)


if __name__ == "__main__":
    main()
