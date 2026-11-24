import base64
import glob
import json
import os
import sys
import urllib.request

TRANS_DIR = os.path.abspath("vault/transcripts")
FRAMES_DIR = os.path.abspath("vault/frames")
BLUEPRINT_DIR = os.path.abspath("vault/blueprints")

MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]


def call_gemini_vision(api_key: str, prompt: str, image_paths: list[str]) -> dict:
    parts = [{"text": prompt}]
    for p in image_paths[:10]:  # Sample up to 10 evenly spaced keyframes
        if os.path.exists(p):
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    }

    last_err = None
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
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
            return json.loads(txt)
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"All Gemini models failed: {last_err}")


def main():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        sys.exit("ERROR: GEMINI_API_KEY is required for blueprint analysis.")

    os.makedirs(BLUEPRINT_DIR, exist_ok=True)
    for trans_file in sorted(glob.glob(os.path.join(TRANS_DIR, "*.json"))):
        vid = os.path.splitext(os.path.basename(trans_file))[0]
        bp_path = os.path.join(BLUEPRINT_DIR, f"{vid}.json")
        if os.path.exists(bp_path):
            continue

        tr = json.load(open(trans_file, encoding="utf-8"))
        cuts_file = os.path.join(FRAMES_DIR, vid, "cuts.json")
        cuts = json.load(open(cuts_file, encoding="utf-8")) if os.path.exists(cuts_file) else []

        # Pick up to 10 keyframes across the Reel
        frame_files = [
            os.path.join(FRAMES_DIR, vid, c["frame"])
            for c in cuts
            if c.get("frame") and os.path.exists(os.path.join(FRAMES_DIR, vid, c["frame"]))
        ]
        if len(frame_files) > 10:
            step = len(frame_files) / 10.0
            frame_files = [frame_files[int(i * step)] for i in range(10)]

        prompt = f"""Analyze this viral Roblox 3D storytelling Reel from @craftee_films.
TRANSCRIPT ({tr['words_per_sec']} words/sec, {tr['duration']}s total):
"{tr['text']}"

DETECTED CAMERA CUTS ({len(cuts)} cuts):
{json.dumps(cuts[:25])}

Inspect the attached keyframes and transcript. Return a JSON blueprint with:
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

        print(f"[Analyze] Reverse-engineering {vid} with Gemini Vision...", flush=True)
        bp = call_gemini_vision(api_key, prompt, frame_files)
        bp["source_transcript"] = tr["text"]
        bp["source_words_per_sec"] = tr["words_per_sec"]
        with open(bp_path, "w", encoding="utf-8") as f:
            json.dump(bp, f, indent=2)
        print(f"[Analyze] Saved blueprint: {bp_path}", flush=True)


if __name__ == "__main__":
    main()
