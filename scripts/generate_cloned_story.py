import glob
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

BLUEPRINT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vault", "blueprints"))

# Active 2026 Gemini & Gemma models ordered by free-tier speed & reliability
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

RICH_SETS = [
    "MusicRow", "TownPool", "Gym", "Street", "Park",
    "Store", "Classroom", "Office", "LivingRoom", "Kitchen", "Bedroom",
]

OUTFIT_PALETTES = [
    {"skin": [0.95, 0.78, 0.62], "shirt": [0.12, 0.45, 0.95], "pants": [0.15, 0.18, 0.25], "hair_color": [0.12, 0.08, 0.05]},
    {"skin": [0.88, 0.68, 0.50], "shirt": [0.92, 0.22, 0.25], "pants": [0.12, 0.14, 0.20], "hair_color": [0.08, 0.06, 0.05]},
    {"skin": [0.55, 0.36, 0.24], "shirt": [0.15, 0.78, 0.42], "pants": [0.20, 0.22, 0.28], "hair_color": [0.06, 0.05, 0.05]},
    {"skin": [0.96, 0.82, 0.68], "shirt": [0.95, 0.72, 0.12], "pants": [0.18, 0.25, 0.45], "hair_color": [0.45, 0.25, 0.10]},
    {"skin": [0.76, 0.54, 0.38], "shirt": [0.62, 0.20, 0.88], "pants": [0.14, 0.14, 0.18], "hair_color": [0.10, 0.07, 0.05]},
]

VALID_CAMS = {"ecu", "cu", "mcu", "ms", "mls", "ws", "low", "high", "ots", "two"}
VALID_MOVES = {"crash_in", "push", "reveal_push", "creep", "drift", "lock"}
VALID_MOODS = {"sunny", "sunset", "storm", "night"}
VALID_ANIMS = {
    "idle", "talk", "walk", "run", "nod", "headshake", "flinch",
    "slump", "jump_joy", "shock", "surrender", "what", "facepalm", "clap",
}
VALID_FACES = {"neutral", "happy", "angry", "scared", "worried", "think", "shock", "smug", "sad"}


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


def build_offline_fast_story(palettes: list[dict]) -> dict:
    """Zero-API emergency backup story with 24 rapid cuts across 3 rich sets."""
    beats = [
        ("MusicRow", "sunny", "mcu", "crash_in", "Alex", "STOP scrolling! Never take a mystery bet!", "shock", "shock", ["whoosh@0.0"]),
        ("MusicRow", "sunny", "two", "push", "Jax", "Jax bet me a hundred bucks right here.", "talk", "smug", []),
        ("MusicRow", "sunny", "cu", "creep", "Alex", "He said I couldn't last ten minutes.", "talk", "angry", []),
        ("MusicRow", "sunny", "low", "crash_in", "Alex", "I accepted without reading the rules!", "what", "shock", ["boom@0.0"]),
        ("MusicRow", "sunny", "ws", "drift", "Jax", "Suddenly the whole street went dead silent.", "idle", "smug", []),
        ("MusicRow", "storm", "mcu", "crash_in", "Alex", "Dark clouds rolled in out of nowhere!", "flinch", "scared", ["impact@0.0"]),
        ("MusicRow", "storm", "ecu", "push", "Alex", "The timer started counting down fast!", "run", "worried", []),
        ("TownPool", "sunny", "ws", "reveal_push", "Alex", "Round two moved straight to the pool!", "run", "shock", ["whoosh@0.0"]),
        ("TownPool", "sunny", "mcu", "push", "Jax", "Jax laughed thinking I would quit now.", "clap", "smug", []),
        ("TownPool", "sunny", "low", "creep", "Alex", "Every second felt ten times harder.", "slump", "worried", []),
        ("TownPool", "sunny", "cu", "crash_in", "Alex", "Then I spotted his secret cheat code!", "shock", "shock", ["ding@0.1"]),
        ("TownPool", "sunny", "two", "push", "Alex", "He rigged the timer from the start!", "angry", "angry", []),
        ("Gym", "sunny", "ws", "reveal_push", "Alex", "So I challenged him to sudden death!", "walk", "angry", ["whoosh@0.0"]),
        ("Gym", "sunny", "mcu", "push", "Jax", "Jax started sweating bullets on the court.", "headshake", "scared", []),
        ("Gym", "sunny", "low", "crash_in", "Alex", "Three seconds left on the clock!", "run", "shock", ["riser@0.0"]),
        ("Gym", "sunny", "ecu", "crash_in", "Alex", "Two seconds left and zero room!", "shock", "shock", []),
        ("Gym", "sunny", "ws", "crash_in", "Alex", "BUZZER BEATER! I actually pulled it off!", "jump_joy", "happy", ["boom@0.0"]),
        ("Gym", "sunny", "mcu", "push", "Jax", "Jax dropped his jaw in total disbelief.", "facepalm", "sad", ["pop@0.0"]),
        ("Gym", "sunny", "two", "drift", "Alex", "He had to hand over the whole prize.", "nod", "happy", ["cash@0.0"]),
        ("Gym", "sunny", "cu", "push", "Alex", "Never underestimate someone who refuses to quit!", "clap", "happy", ["ding@0.1"]),
    ]
    shots = []
    for st, md, cm, mv, subj, txt, anim, face, sfx in beats:
        other = "Jax" if subj == "Alex" else "Alex"
        shots.append({
            "set": st,
            "mood": md,
            "cam": cm,
            "move": mv,
            "subject": subj,
            "text": txt,
            "sfx": sfx,
            "actors": [
                {"who": subj, "at": [-1.4, 0], "yaw": 15, "anim": anim, "face": face, "talk": [0.0, 1.6]},
                {"who": other, "at": [1.6, 0.4], "yaw": -20, "anim": "idle", "face": "smug" if other == "Jax" else "neutral"},
            ],
        })
    return {
        "title": "I Accepted a Rigged $100 Challenge!",
        "caption": "He rigged the rules from the start! #roblox #storytime #shorts #reels #fyp",
        "keys": ["STOP", "MYSTERY", "HUNDRED", "CHEAT", "BUZZER", "NEVER"],
        "music": [[0, "playful"], [0.35, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
        "cast": {
            "Alex": {"height": 1.0, **palettes[0]},
            "Jax": {"height": 1.05, **palettes[1]},
        },
        "shots": shots,
    }


def call_gemini_json_defensive(api_key: str, prompt: str) -> dict:
    last_err = None
    for model in MODELS:
        gen_cfg = {"temperature": 0.85}
        if not model.startswith("gemma-"):
            gen_cfg["responseMimeType"] = "application/json"

        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_cfg}
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


def main(project_dir: str):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    os.makedirs(project_dir, exist_ok=True)
    blueprints = sorted(glob.glob(os.path.join(BLUEPRINT_DIR, "*.json")))
    bp = json.load(open(random.choice(blueprints), encoding="utf-8")) if blueprints else {}
    theme = os.environ.get("STORY_THEME", "").strip()
    palettes = random.sample(OUTFIT_PALETTES, 3)

    prompt = f"""You are a viral Roblox 3D Reels director cloning the exact pacing, hook intensity, rapid camera cuts, and visual variety of top creator @craftee_films.

REFERENCE BLUEPRINT TO CLONE STYLE FROM:
{json.dumps(bp, indent=2) if bp else "Fast-paced 22-to-28-shot Roblox comedic/dramatic twist Reel with 1.4s cuts, punchy 3-second hook, escalating stakes, and rich set changes."}

OPTIONAL USER THEME: "{theme or 'Create a brand-new original viral twist story (do NOT copy the reference plot word-for-word, clone its pacing, hook structure, and visual energy)'}"

STRICT PRODUCTION RULES:
1. TOTAL LENGTH: 210 to 250 words across 22 to 28 rapid shots (each shot is 1 short punchy sentence, ~8-11 words, cutting every ~1.6 to 2.0 seconds).
2. MULTI-LOCATION VISUAL VARIETY: Use 2 to 3 DIFFERENT rich sets from: {json.dumps(RICH_SETS)}
3. DYNAMIC CAMERA WORK: Never repeat the same angle twice in a row! Alternate cam ({json.dumps(sorted(VALID_CAMS))}) and move ({json.dumps(sorted(VALID_MOVES))}).
4. CHARACTERS: Use Alex and Jax with these exact color palettes:
   - Alex: {json.dumps(palettes[0])}
   - Jax: {json.dumps(palettes[1])}

Return ONLY valid JSON matching:
{{
  "title": "Catchy viral title",
  "caption": "Short Instagram Reels caption with 5 viral hashtags",
  "keys": ["UPPERCASE", "IMPACT", "WORDS", "TO", "HIGHLIGHT", "YELLOW"],
  "music": [[0, "playful"], [0.45, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
  "cast": {{
    "Alex": {{"height": 1.0, "skin": {json.dumps(palettes[0]['skin'])}, "shirt": {json.dumps(palettes[0]['shirt'])}, "pants": {json.dumps(palettes[0]['pants'])}, "hair_color": {json.dumps(palettes[0]['hair_color'])}}},
    "Jax": {{"height": 1.05, "skin": {json.dumps(palettes[1]['skin'])}, "shirt": {json.dumps(palettes[1]['shirt'])}, "pants": {json.dumps(palettes[1]['pants'])}, "hair_color": {json.dumps(palettes[1]['hair_color'])}}}
  }},
  "shots": [
    {{
      "set": "MusicRow",
      "mood": "sunny",
      "cam": "mcu",
      "move": "crash_in",
      "subject": "Alex",
      "text": "Punchy hook line under 11 words!",
      "sfx": ["whoosh@0.0"],
      "actors": [
        {{"who": "Alex", "at": [-1.5, 0], "yaw": 15, "anim": "shock", "face": "shock", "talk": [0.0, 1.8]}},
        {{"who": "Jax", "at": [1.8, 0.5], "yaw": -25, "anim": "idle", "face": "smug"}}
      ]
    }}
  ]
}}"""

    try:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY empty")
        story = call_gemini_json_defensive(api_key, prompt)
    except Exception as e:
        print(f"[WARN] Story LLM fallback engaged ({e}); using offline 20-shot fast-cut story.", flush=True)
        story = build_offline_fast_story(palettes)

    # Full schema sanitization so compile.py never fails
    valid_sets = set(RICH_SETS)
    cast = story.get("cast")
    if not isinstance(cast, dict) or not cast:
        story["cast"] = {
            "Alex": {"height": 1.0, **palettes[0]},
            "Jax": {"height": 1.05, **palettes[1]},
        }
    cast_names = list(story["cast"].keys())

    shots = story.get("shots")
    if not isinstance(shots, list) or len(shots) < 4:
        story = build_offline_fast_story(palettes)
        shots = story["shots"]

    t_cursor = 0.0
    prev_cam = None
    cam_cycle = ["mcu", "ws", "low", "cu", "two", "ots", "ecu", "ms"]
    for idx, sh in enumerate(shots):
        if sh.get("set") not in valid_sets:
            sh["set"] = RICH_SETS[(idx // 7) % 3]
        if sh.get("mood") not in VALID_MOODS:
            sh["mood"] = "sunny"
        if sh.get("cam") not in VALID_CAMS or sh.get("cam") == prev_cam:
            sh["cam"] = cam_cycle[idx % len(cam_cycle)]
        prev_cam = sh["cam"]
        if sh.get("move") not in VALID_MOVES:
            sh["move"] = "crash_in" if idx % 4 == 0 else "push"
        if sh.get("subject") not in cast_names:
            sh["subject"] = cast_names[0]

        sh["t0"] = round(t_cursor, 2)
        t_cursor += 1.85
        sh["t1"] = round(t_cursor, 2)

        actors = sh.get("actors")
        if not isinstance(actors, list) or not actors:
            sh["actors"] = [
                {"who": cast_names[0], "at": [-1.4, 0], "yaw": 15, "anim": "talk", "face": "neutral", "talk": [0.0, 1.6]},
            ]
        else:
            for act in actors:
                if act.get("who") not in cast_names:
                    act["who"] = cast_names[0]
                if act.get("anim") not in VALID_ANIMS:
                    act["anim"] = "talk"
                if act.get("face") not in VALID_FACES:
                    act["face"] = "neutral"

    story["dur"] = round(t_cursor, 2)

    with open(os.path.join(project_dir, "timed.json"), "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2)

    with open(os.path.join(project_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": story.get("title", "Blox Story"),
                "caption": story.get("caption", "#roblox #storytime #shorts #reels"),
                "reference_blueprint": bp.get("reel_id", "none"),
                "model_used": story.get("model_used", "offline_fallback"),
            },
            f,
            indent=2,
        )

    print(
        f"[CloneStory] Generated {len(story['shots'])} rapid-cut shots "
        f"(blueprint={bp.get('reel_id', 'default')}, model={story.get('model_used', 'offline')})",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python generate_cloned_story.py <PROJECT_DIR>")
    main(os.path.abspath(sys.argv[1]))
