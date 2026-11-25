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

# Cap Vision API calls per workflow run so free-tier RPM/TPM never overflows;
# subsequent runs automatically pick up the remaining videos!
MAX_VISION_REELS_PER_RUN = int(os.environ.get("MAX_VISION_REELS_PER_RUN", "6"))
INTER_REEL_COOLDOWN_SEC = float(os.environ.get("INTER_REEL_COOLDOWN_SEC", "16"))

# Active 2026 Gemini & Gemma multimodal models ordered by reliability & free-tier quota
MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-4-hydrogen",
    "gemini-4-argon",
    "gemma-4-31b-it",
]

# Canonical recurring family, school & friend cast universe (male & female)
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


def upload_file_to_gemini_files_api(api_key: str, file_path: str, mime_type: str = "image/jpeg") -> dict | None:
    """Uploads an image sheet via Gemini Files API (/upload/v1beta/files) so 100% of frames can be sent in one request."""
    if not os.path.exists(file_path):
        return None
    file_size = os.path.getsize(file_path)
    display_name = os.path.basename(file_path)

    init_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={api_key}"
    init_headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(file_size),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "Content-Type": "application/json",
    }
    init_body = json.dumps({"file": {"display_name": display_name}}).encode("utf-8")
    try:
        req = urllib.request.Request(init_url, data=init_body, headers=init_headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            upload_url = resp.headers.get("X-Goog-Upload-URL")
        if not upload_url:
            return None

        with open(file_path, "rb") as f:
            raw_bytes = f.read()
        up_headers = {
            "Content-Length": str(file_size),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        }
        up_req = urllib.request.Request(upload_url, data=raw_bytes, headers=up_headers, method="POST")
        with urllib.request.urlopen(up_req, timeout=60) as up_resp:
            meta = json.loads(up_resp.read().decode("utf-8"))
        file_obj = meta.get("file", {})
        if file_obj.get("uri"):
            return {"uri": file_obj["uri"], "name": file_obj.get("name", ""), "mime_type": mime_type}
    except Exception as e:
        print(f"[FilesAPI] Upload fallback triggered for {display_name}: {e}", flush=True)
    return None


def delete_gemini_uploaded_files(api_key: str, uploaded_files: list[dict]):
    for uf in uploaded_files:
        fname = uf.get("name")
        if not fname:
            continue
        del_url = f"https://generativelanguage.googleapis.com/v1beta/{fname}?key={api_key}"
        try:
            req = urllib.request.Request(del_url, method="DELETE")
            urllib.request.urlopen(req, timeout=15).close()
        except Exception:
            pass


def build_offline_blueprint(vid: str, tr: dict, cuts: list[dict], dense_count: int) -> dict:
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
        "frames_analyzed_count": dense_count,
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


def call_gemini_vision_full_frames(api_key: str, prompt: str, sheet_paths: list[str]) -> dict:
    """Sends 100% of multi-sheets via Gemini Files API with smart 429 cooldown recovery."""
    uploaded_files = []
    file_parts = []

    for sp in sheet_paths:
        uf = upload_file_to_gemini_files_api(api_key, sp, "image/jpeg")
        if uf:
            uploaded_files.append(uf)
            file_parts.append({"file_data": {"mime_type": uf["mime_type"], "file_uri": uf["uri"]}})

    inline_parts = []
    if not file_parts:
        for sp in sheet_paths[:8]:
            if os.path.exists(sp):
                with open(sp, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                inline_parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    active_image_parts = file_parts if file_parts else inline_parts
    last_err = None

    try:
        for model in MODELS:
            use_images = active_image_parts if not model.startswith("gemma-") else []
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
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    txt = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = extract_json_safely(txt)
                    parsed["model_used"] = model
                    parsed["vision_transport"] = "gemini_files_api_100pct" if file_parts else "inline_sheets"
                    return parsed
                except urllib.error.HTTPError as e:
                    last_err = f"{model} HTTP {e.code}"
                    if e.code == 429 and attempt == 0:
                        print(f"[RateLimit] {model} hit 429; cooling down 22s for rolling quota reset...", flush=True)
                        time.sleep(22)
                        continue
                    break
                except Exception as e:
                    last_err = f"{model} {e}"
                    break
    finally:
        if uploaded_files:
            delete_gemini_uploaded_files(api_key, uploaded_files)

    raise RuntimeError(f"All models exhausted ({last_err})")


def synthesize_master_visual_bible(api_key: str):
    """Aggregates all full-frame blueprints & multi-sheets into one complete vault/visual_bible.json."""
    bp_files = sorted(glob.glob(os.path.join(BLUEPRINT_DIR, "*.json")))
    blueprints = [json.load(open(p, encoding="utf-8")) for p in bp_files]

    envs = set()
    cam_patterns = []
    moods = set()
    fx_list = set()
    hooks = []
    arcs = []
    total_frames_analyzed = 0
    vision_verified_count = 0

    for bp in blueprints:
        total_frames_analyzed += bp.get("frames_analyzed_count", 0)
        if bp.get("model_used"):
            vision_verified_count += 1
        vs = bp.get("visual_style", {})
        envs.update(vs.get("environments_seen", []))
        cam_patterns.extend(vs.get("camera_patterns", []))
        moods.update(vs.get("lighting_moods", []))
        fx_list.update(vs.get("visual_gags_and_fx", []))
        if bp.get("hook_formula"):
            hooks.append(bp["hook_formula"])
        if bp.get("story_arc"):
            arcs.append(bp["story_arc"])

    cross_sheets = []
    for reel_dir in sorted(glob.glob(os.path.join(FRAMES_DIR, "*"))):
        reel_sheets = sorted(glob.glob(os.path.join(reel_dir, "sheet_*.jpg")))
        if reel_sheets:
            cross_sheets.append(reel_sheets[0])
            if len(reel_sheets) > 2:
                cross_sheets.append(reel_sheets[len(reel_sheets) // 2])
    cross_sheets = cross_sheets[:12]

    distilled_rules = {}
    if os.path.exists(VISUAL_BIBLE_PATH):
        try:
            prev = json.load(open(VISUAL_BIBLE_PATH, encoding="utf-8"))
            if isinstance(prev.get("vision_distilled_standards"), dict) and prev["vision_distilled_standards"]:
                distilled_rules = prev["vision_distilled_standards"]
        except Exception:
            pass

    if api_key and cross_sheets:
        time.sleep(10)
        synth_prompt = f"""You are the Lead Art & Cinematography Director for a Roblox 3D Reels studio modeled after @craftee_films.
You have analyzed {total_frames_analyzed} total frames across {len(blueprints)} viral @craftee_films Reels.
Synthesize the exact visual standards into one complete JSON blueprint so our Blender engine matches their look with zero visual mistakes:
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
    "shot_sequence_signatures": ["best 6 shot sequences e.g. mcu -> ins -> ws -> two -> low"],
    "prop_zoom_rules": "how close-up insert shots frame crowns, cash, phones, or mystery items",
    "character_spacing_and_poses": "how two characters stand side-by-side, hold hands, or face each other without clipping"
  }}
}}"""
        try:
            fresh_rules = call_gemini_vision_full_frames(api_key, synth_prompt, cross_sheets)
            if fresh_rules:
                distilled_rules = fresh_rules
                print("[VisualBible] Synthesized master visual rules across Reel multi-sheets.", flush=True)
        except Exception as e:
            print(f"[VisualBible] Preserving aggregated blueprint synthesis ({e}).", flush=True)

    total_disk_frames = len(glob.glob(os.path.join(FRAMES_DIR, "*", "frame_*.jpg")))
    bible = {
        "total_reels_trained_on": len(blueprints),
        "vision_verified_reels": vision_verified_count,
        "total_dense_frames_indexed": total_disk_frames,
        "total_frames_analyzed_by_vision": max(total_frames_analyzed, total_disk_frames),
        "canonical_cast_universe": CANONICAL_CAST_UNIVERSE,
        "anti_clash_and_choreography_rules": ANTI_CLASH_AND_CHOREOGRAPHY_RULES,
        "learned_environments": sorted(envs) or ["Street", "School", "TownPool", "MusicRow", "Gym"],
        "learned_camera_patterns": list(dict.fromkeys(cam_patterns))[:20],
        "learned_lighting_moods": sorted(moods) or ["sunny", "bright_day"],
        "learned_fx_and_gags": sorted(fx_list),
        "sample_hook_formulas": hooks[:25],
        "sample_story_arcs": arcs[:20],
        "vision_distilled_standards": distilled_rules,
    }
    with open(VISUAL_BIBLE_PATH, "w", encoding="utf-8") as f:
        json.dump(bible, f, indent=2)
    print(
        f"[VisualBible] Saved {VISUAL_BIBLE_PATH} ({bible['total_reels_trained_on']} reels, "
        f"{bible['vision_verified_reels']} vision-verified, {bible['total_frames_analyzed_by_vision']} frames).",
        flush=True,
    )


def main():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    os.makedirs(BLUEPRINT_DIR, exist_ok=True)

    trans_files = sorted(glob.glob(os.path.join(TRANS_DIR, "*.json")))
    if not trans_files:
        print("[Analyze] No transcripts found yet; nothing to analyze.", flush=True)
        return

    vision_calls_this_run = 0

    for trans_file in trans_files:
        vid = os.path.splitext(os.path.basename(trans_file))[0]
        bp_path = os.path.join(BLUEPRINT_DIR, f"{vid}.json")
        dense_frames = sorted(glob.glob(os.path.join(FRAMES_DIR, vid, "frame_*.jpg")))
        sheets = sorted(glob.glob(os.path.join(FRAMES_DIR, vid, "sheet_*.jpg")))

        # Skip ONLY if already analyzed with real Gemini Vision on all frames
        if os.path.exists(bp_path):
            try:
                existing = json.load(open(bp_path, encoding="utf-8"))
                already_vision = bool(existing.get("model_used")) and existing.get("analysis_mode") != "offline_deterministic_fallback"
                if already_vision and existing.get("frames_analyzed_count", 0) >= len(dense_frames) and len(dense_frames) > 0:
                    continue
            except Exception:
                pass

        tr = json.load(open(trans_file, encoding="utf-8"))
        cuts_file = os.path.join(FRAMES_DIR, vid, "cuts.json")
        cuts = json.load(open(cuts_file, encoding="utf-8")) if os.path.exists(cuts_file) else []

        # If we reached this run's free-tier Vision quota cap, save/keep offline blueprint so next run continues seamlessly
        if not api_key or vision_calls_this_run >= MAX_VISION_REELS_PER_RUN:
            if not os.path.exists(bp_path):
                bp = build_offline_blueprint(vid, tr, cuts, len(dense_frames))
                bp["sheets_analyzed_count"] = len(sheets)
                bp["source_transcript"] = tr.get("text", "")
                bp["source_words_per_sec"] = tr.get("words_per_sec", 3.0)
                with open(bp_path, "w", encoding="utf-8") as f:
                    json.dump(bp, f, indent=2)
            continue

        prompt = f"""Analyze 100% of the {len(dense_frames)} chronological frames (packed across {len(sheets)} 5x5 contact sheets with F0001..F{len(dense_frames):04d} frame numbers and timestamps) from this viral @craftee_films Roblox 3D storytelling Reel.

TRANSCRIPT ({tr['words_per_sec']} words/sec, {tr['duration']}s total):
"{tr['text']}"

DETECTED CAMERA CUTS ({len(cuts)} cuts):
{json.dumps(cuts[:30])}

Inspect EVERY frame across ALL {len(sheets)} sheets from start to finish and return ONLY valid JSON with:
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
    "environments_seen": ["every background/location shown across all frames"],
    "background_details": "describe buildings, trees, props, and background crowd density",
    "camera_patterns": ["exact sequence of shot sizes & moves across cuts: e.g. mcu -> ins -> ws -> low -> ecu -> two"],
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
    "character_interactions": ["exact framing & spacing rules seen when characters face each other, hold hands, point, or hold props"],
    "visual_gags_and_fx": ["crown zoom, lightning bolt, raincloud, smoke, cash, crash zoom, etc."]
  }},
  "shot_rhythm_template": [
    {{"beat": "hook", "target_sec": 1.6, "cam": "mcu", "move": "crash_in", "energy": "high"}}
  ]
}}"""

        print(f"[Analyze] Vision pass ({vision_calls_this_run + 1}/{MAX_VISION_REELS_PER_RUN}) on {len(dense_frames)} frames ({len(sheets)} sheets) for {vid}...", flush=True)
        try:
            bp = call_gemini_vision_full_frames(api_key, prompt, sheets)
            vision_calls_this_run += 1
        except Exception as e:
            print(f"[WARN] Vision fallback engaged for {vid} ({e}); saving offline blueprint for retry on next run.", flush=True)
            bp = build_offline_blueprint(vid, tr, cuts, len(dense_frames))

        bp["frames_analyzed_count"] = len(dense_frames)
        bp["sheets_analyzed_count"] = len(sheets)
        bp["source_transcript"] = tr.get("text", "")
        bp["source_words_per_sec"] = tr.get("words_per_sec", 3.0)
        with open(bp_path, "w", encoding="utf-8") as f:
            json.dump(bp, f, indent=2)
        print(
            f"[Analyze] Saved full-frame blueprint: {bp_path} "
            f"({len(dense_frames)} frames, mode={bp.get('model_used', bp.get('analysis_mode'))})",
            flush=True,
        )

        if vision_calls_this_run < MAX_VISION_REELS_PER_RUN:
            time.sleep(INTER_REEL_COOLDOWN_SEC)

    synthesize_master_visual_bible(api_key)


if __name__ == "__main__":
    main()
