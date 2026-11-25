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
VISUAL_BIBLE_PATH = os.path.abspath("vault/visual_bible.json")

# Valid Gemini & Gemma multimodal models ordered by speed, vision accuracy & free-tier availability
MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemma-3-27b-it",
]

# Canonical recurring family, school & friend cast universe (male & female) + dynamic role archetypes
CANONICAL_CAST_UNIVERSE = {
    "Leo": {
        "role": "main_character",
        "gender": "male",
        "skin": "#f5c29b",
        "hair": "spiky",
        "hair_color": "#261b14",
        "shirt": "#1e73f2",
        "pants": "#1b2234",
        "extras": [],
        "personality": "curious, energetic, bold underdog hero",
    },
    "Maya": {
        "role": "sister",
        "gender": "female",
        "skin": "#f7c7a3",
        "hair": "pigtails",
        "hair_color": "#3b2316",
        "shirt": "#ff4f8b",
        "pants": "#2a2d43",
        "extras": [],
        "personality": "clever, sharp-tongued younger sister who spots traps first",
    },
    "Max": {
        "role": "brother",
        "gender": "male",
        "skin": "#e8b087",
        "hair": "curly",
        "hair_color": "#1e1612",
        "shirt": "#22b855",
        "pants": "#1d2432",
        "extras": ["cap"],
        "personality": "confident older brother, sporty and competitive",
    },
    "Mom": {
        "role": "mother",
        "gender": "female",
        "skin": "#f5c29b",
        "hair": "bun",
        "hair_color": "#4a2c18",
        "shirt": "#9b51e0",
        "pants": "#25293a",
        "extras": ["cardigan"],
        "personality": "caring yet strict when rules are broken",
    },
    "Dad": {
        "role": "father",
        "gender": "male",
        "skin": "#eab38a",
        "hair": "short",
        "hair_color": "#2d221c",
        "shirt": "#2f80ed",
        "pants": "#1f2533",
        "extras": ["tie"],
        "personality": "calm, hardworking dad with dry humor",
    },
    "Uncle_Sam": {
        "role": "uncle",
        "gender": "male",
        "skin": "#e2a77d",
        "hair": "short",
        "hair_color": "#5c5856",
        "shirt": "#f2994a",
        "pants": "#2c3342",
        "extras": ["glasses"],
        "personality": "funny, eccentric uncle with wild stories and secret gadgets",
    },
    "Ms_Clara": {
        "role": "teacher",
        "gender": "female",
        "skin": "#f6c9a6",
        "hair": "long",
        "hair_color": "#3d2516",
        "shirt": "#27ae60",
        "pants": "#1e2430",
        "extras": ["glasses", "cardigan"],
        "personality": "observant school teacher who catches every sneaky move",
    },
    "Zoe": {
        "role": "best_friend_female",
        "gender": "female",
        "skin": "#c68658",
        "hair": "long",
        "hair_color": "#191412",
        "shirt": "#f2c94c",
        "pants": "#232938",
        "extras": [],
        "personality": "loyal, enthusiastic best friend always ready for a challenge",
    },
    "Sam": {
        "role": "best_friend_male",
        "gender": "male",
        "skin": "#8d5524",
        "hair": "curly",
        "hair_color": "#141110",
        "shirt": "#eb5757",
        "pants": "#1c2230",
        "extras": [],
        "personality": "funny best friend who panics dramatically at plot twists",
    },
}

ANTI_CLASH_AND_CHOREOGRAPHY_RULES = {
    "min_actor_separation_studs": 3.4,
    "hold_hands_pair_offset_studs": 2.15,
    "hold_hands_shared_yaw_deg": 0.0,
    "auto_face_listener_atan2": True,
    "prevent_mesh_overlap": True,
    "forbidden_clipping_patterns": [
        "Never spawn two characters at the same (x, y) coordinate",
        "Never path a walkTo trajectory straight through a stationary actor's bounding box",
        "Keep background crowd NPCs at least 4.5 studs behind foreground speakers (y >= 4.5)",
    ],
    "lighting_and_color_standards": {
        "workbench_light_mode": "FLAT",
        "color_space": "sRGB_bright",
        "avoid_dark_muddy_skin": True,
        "remove_grey_chest_plates": True,
    },
    "custom_roblox_asset_builder_rules": {
        "enabled": True,
        "instruction": (
            "Whenever the script mentions an object, prop, crown, vehicle, gadget, trophy, or structure "
            "not already present in standard places, Gemini MUST define it in `things` using blocky Roblox "
            "primitive parts (box/cylinder/sphere with exact size [w,d,h], pos [x,y,z], and bright hex color) "
            "and target it with `cam: 'ins', focus: '<ThingName>'` during key reveal beats."
        ),
    },
}


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
    cams = ["mcu", "ins", "ws", "low", "ecu", "two", "ms", "ots"]
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
            "environments_seen": ["MusicRow", "TownPool", "Gym", "Street", "School"],
            "camera_patterns": ["mcu -> ins -> ws -> low -> ecu -> two"],
            "lighting_moods": ["sunny", "bright_day", "sunset"],
            "character_archetypes": [
                {"role": "protagonist", "gender": "male", "outfit_style": "vibrant streetwear", "primary_colors": ["#1e73f2", "#f5c29b"]},
                {"role": "sister_or_friend", "gender": "female", "outfit_style": "colorful casual", "primary_colors": ["#ff4f8b", "#f7c7a3"]},
            ],
            "background_crowd_density": "4-6 background NPCs in wide shots",
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
        use_images = image_parts if not model.startswith("gemma-") else []
        parts = [{"text": prompt}] + use_images
        gen_cfg = {"temperature": 0.35}
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


def synthesize_master_visual_bible(api_key: str):
    """Aggregates all harvested blueprints & contact sheets into one master vault/visual_bible.json."""
    bp_files = sorted(glob.glob(os.path.join(BLUEPRINT_DIR, "*.json")))
    blueprints = [json.load(open(p, encoding="utf-8")) for p in bp_files]

    envs = set()
    cam_patterns = []
    moods = set()
    fx_list = set()
    hooks = []
    arcs = []
    for bp in blueprints:
        vs = bp.get("visual_style", {})
        envs.update(vs.get("environments_seen", []))
        cam_patterns.extend(vs.get("camera_patterns", []))
        moods.update(vs.get("lighting_moods", []))
        fx_list.update(vs.get("visual_gags_and_fx", []))
        if bp.get("hook_formula"):
            hooks.append(bp["hook_formula"])
        if bp.get("story_arc"):
            arcs.append(bp["story_arc"])

    # Gather up to 6 contact sheets across different Reels for cross-video visual synthesis
    contact_sheets = sorted(glob.glob(os.path.join(FRAMES_DIR, "*", "contact_sheet.jpg")))[:6]
    distilled_rules = {}
    if api_key and contact_sheets:
        synth_prompt = f"""You are the Lead Art & Cinematography Director for a Roblox 3D Reels studio modeled after @craftee_films.
Inspect these multi-shot contact sheets extracted from {len(blueprints)} viral @craftee_films Reels.
Synthesize the exact visual standards into JSON so our Blender engine matches their look with zero visual mistakes:
{{
  "skin_and_character_palette": {{
    "bright_skin_hexes": ["list 6 warm, bright Roblox skin hex colors (never muddy/dark)"],
    "male_outfit_palettes": [{{"shirt": "#hex", "pants": "#hex", "hair": "#hex"}}],
    "female_outfit_palettes": [{{"shirt": "#hex", "pants": "#hex", "hair": "#hex"}}]
  }},
  "background_and_lighting_standards": {{
    "dominant_backgrounds": ["top environments seen across frames"],
    "background_prop_density": "how busy backgrounds are (trees, buildings, signs, vehicles, crowd NPCs)",
    "lighting_contrast": "bright daytime / high readability rules"
  }},
  "camera_and_staging_rules": {{
    "shot_sequence_signatures": ["best 5 shot sequences e.g. mcu -> ins -> ws -> two -> low"],
    "prop_zoom_rules": "how close-up insert shots frame crowns, cash, phones, or mystery items",
    "character_spacing_and_poses": "how two characters stand side-by-side, hold hands, or face each other without clipping"
  }}
}}"""
        try:
            distilled_rules = call_gemini_vision_defensive(api_key, synth_prompt, contact_sheets)
            print("[VisualBible] Synthesized master visual rules from multi-reel contact sheets.", flush=True)
        except Exception as e:
            print(f"[VisualBible] Using aggregated blueprint synthesis ({e}).", flush=True)

    bible = {
        "total_reels_trained_on": len(blueprints),
        "total_frames_indexed": len(glob.glob(os.path.join(FRAMES_DIR, "*", "*.jpg"))),
        "canonical_cast_universe": CANONICAL_CAST_UNIVERSE,
        "anti_clash_and_choreography_rules": ANTI_CLASH_AND_CHOREOGRAPHY_RULES,
        "learned_environments": sorted(envs) or ["Street", "School", "TownPool", "MusicRow", "Gym"],
        "learned_camera_patterns": list(dict.fromkeys(cam_patterns))[:15],
        "learned_lighting_moods": sorted(moods) or ["sunny", "bright_day"],
        "learned_fx_and_gags": sorted(fx_list),
        "sample_hook_formulas": hooks[:20],
        "sample_story_arcs": arcs[:15],
        "vision_distilled_standards": distilled_rules,
    }
    with open(VISUAL_BIBLE_PATH, "w", encoding="utf-8") as f:
        json.dump(bible, f, indent=2)
    print(
        f"[VisualBible] Saved {VISUAL_BIBLE_PATH} ({bible['total_reels_trained_on']} reels, "
        f"{bible['total_frames_indexed']} frames).",
        flush=True,
    )


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

        # Feed the 20-shot contact sheet FIRST + up to 7 individual keyframe cuts so Gemini sees the entire video visually
        frame_files = []
        sheet_path = os.path.join(FRAMES_DIR, vid, "contact_sheet.jpg")
        if os.path.exists(sheet_path):
            frame_files.append(sheet_path)

        cut_imgs = [
            os.path.join(FRAMES_DIR, vid, c["frame"])
            for c in cuts
            if c.get("frame") and os.path.exists(os.path.join(FRAMES_DIR, vid, c["frame"]))
        ]
        if len(cut_imgs) > 7:
            step = len(cut_imgs) / 7.0
            cut_imgs = [cut_imgs[int(i * step)] for i in range(7)]
        frame_files.extend(cut_imgs)

        prompt = f"""Analyze this viral Roblox 3D storytelling Reel from @craftee_films.
Notice the first image is a 20-frame contact sheet showing the entire Reel's visual progression, followed by individual camera cut frames.

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
    "environments_seen": ["list of backgrounds/locations shown across frames"],
    "background_details": "describe buildings, trees, props, and background crowd density",
    "camera_patterns": ["sequence of shot sizes & moves: e.g. mcu -> ins -> ws -> low -> ecu -> two"],
    "lighting_moods": ["e.g. bright_day, sunny, sunset, storm"],
    "character_archetypes": [
      {{
        "role": "protagonist / sister / teacher / officer / rival",
        "gender": "male or female",
        "skin_hex": "#bright_srgb_hex",
        "hair_style": "spiky / curly / long / pigtails / bun / cap / short",
        "outfit_style": "description",
        "primary_colors": ["#shirt_hex", "#pants_hex"]
      }}
    ],
    "character_interactions": ["how characters stand, face each other, hold hands, point, or hold props without overlapping"],
    "visual_gags_and_fx": ["crown zoom, lightning bolt, raincloud, smoke, cash, crash zoom, etc."]
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

    synthesize_master_visual_bible(api_key)


if __name__ == "__main__":
    main()
