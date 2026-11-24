import glob
import json
import os
import random
import sys
import urllib.request

BLUEPRINT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vault", "blueprints"))
MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]

# Verified rich sets in Blox Studio (sets.py + places_built.py)
RICH_SETS = [
    "MusicRow", "TownPool", "Gym", "Street", "Park",
    "Store", "Classroom", "Office", "LivingRoom", "Kitchen", "Bedroom"
]

# Vibrant recolored character palettes so every Reel has fresh, distinct outfits
OUTFIT_PALETTES = [
    {"skin": [0.95, 0.78, 0.62], "shirt": [0.12, 0.45, 0.95], "pants": [0.15, 0.18, 0.25], "hair_color": [0.12, 0.08, 0.05]},
    {"skin": [0.88, 0.68, 0.50], "shirt": [0.92, 0.22, 0.25], "pants": [0.12, 0.14, 0.20], "hair_color": [0.08, 0.06, 0.05]},
    {"skin": [0.55, 0.36, 0.24], "shirt": [0.15, 0.78, 0.42], "pants": [0.20, 0.22, 0.28], "hair_color": [0.06, 0.05, 0.05]},
    {"skin": [0.96, 0.82, 0.68], "shirt": [0.95, 0.72, 0.12], "pants": [0.18, 0.25, 0.45], "hair_color": [0.45, 0.25, 0.10]},
    {"skin": [0.76, 0.54, 0.38], "shirt": [0.62, 0.20, 0.88], "pants": [0.14, 0.14, 0.18], "hair_color": [0.10, 0.07, 0.05]},
]


def call_gemini_json(api_key: str, prompt: str) -> dict:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.85},
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
    raise RuntimeError(f"Gemini generation failed: {last_err}")


def main(project_dir: str):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        sys.exit("ERROR: GEMINI_API_KEY is missing.")

    os.makedirs(project_dir, exist_ok=True)
    blueprints = sorted(glob.glob(os.path.join(BLUEPRINT_DIR, "*.json")))
    bp = json.load(open(random.choice(blueprints), encoding="utf-8")) if blueprints else {}
    theme = os.environ.get("STORY_THEME", "").strip()

    palettes = random.sample(OUTFIT_PALETTES, 3)

    prompt = f"""You are a viral Roblox 3D Reels director cloning the exact pacing, hook intensity, rapid camera cuts, and visual variety of top creator @craftee_films.

REFERENCE BLUEPRINT TO CLONE STYLE FROM:
{json.dumps(bp, indent=2) if bp else "Fast-paced 22-to-28-shot Roblox comedic/dramatic twist Reel with 1.4s cuts, punchy 3-second hook, escalating stakes, and rich set changes."}

OPTIONAL USER THEME: "{theme or 'Create a brand-new original viral twist story (do NOT copy the reference plot word-for-word, clone its pacing, hook structure, and visual energy)'}"

STRICT PRODUCTION RULES (CRITICAL FOR HIGH VISUAL QUALITY):
1. TOTAL LENGTH: 210 to 250 words across **22 to 28 rapid shots** (each shot is 1 short punchy sentence or clause, ~8-11 words, so the camera cuts every ~1.5 to 2.2 seconds!).
2. MULTI-LOCATION VISUAL VARIETY: Use 2 to 3 DIFFERENT rich sets across the story from this exact list:
   {json.dumps(RICH_SETS)}
   (Especially use "MusicRow", "TownPool", "Gym", "Street", "Store", "Park" — they have rich buildings, cars, bleachers, pools, signs, and props!).
3. DYNAMIC CAMERA WORK: Never repeat the same camera angle twice in a row! Alternate:
   - cam: "ecu", "cu", "mcu", "ms", "mls", "ws", "low", "high", "ots", "two"
   - move: "crash_in" (on twists/shocks), "push", "reveal_push", "creep", "drift", "lock"
   - Add "flash": true on major twist/lightning shots.
4. EXPRESSIVE ACTING & FX:
   - anim: "idle", "talk", "walk", "run", "nod", "headshake", "flinch", "slump", "jump_joy", "shock", "surrender", "what", "facepalm", "clap"
   - face: "neutral", "happy", "angry", "scared", "worried", "think", "shock", "smug", "sad"
   - fx (optional on dramatic actors): ["raincloud@0.0"], ["storm@0.0"], ["bolt@0.1"], ["smoke@0.0"], ["money@0.0"]
   - sfx (optional on shots): ["whoosh@0.0"], ["boom@0.0"], ["impact@0.0"], ["ding@0.1"], ["cash@0.0"], ["pop@0.0"], ["riser@0.0"]
5. CHARACTERS (2 or 3 distinct characters with different heights and vibrant recolored outfits):
   Use these exact color palettes for the cast:
   - Character 1: {json.dumps(palettes[0])}
   - Character 2: {json.dumps(palettes[1])}
   - Character 3 (optional): {json.dumps(palettes[2])}

Return ONLY valid JSON matching this exact schema:
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

    story = call_gemini_json(api_key, prompt)

    # Defensive sanitization so compile.py never fails
    valid_sets = set(RICH_SETS)
    cast_names = list(story.get("cast", {}).keys()) or ["Alex", "Jax"]
    t_cursor = 0.0
    for idx, sh in enumerate(story.get("shots", [])):
        if sh.get("set") not in valid_sets:
            sh["set"] = RICH_SETS[idx % len(RICH_SETS)]
        sh["t0"] = round(t_cursor, 2)
        t_cursor += 2.0
        sh["t1"] = round(t_cursor, 2)
        if not sh.get("actors"):
            sh["actors"] = [{"who": cast_names[0], "at": [0, 0], "yaw": 0, "anim": "talk", "face": "neutral", "talk": [0.0, 1.8]}]

    story["dur"] = round(t_cursor, 2)

    with open(os.path.join(project_dir, "timed.json"), "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2)

    with open(os.path.join(project_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": story.get("title", "Blox Story"),
                "caption": story.get("caption", "#roblox #storytime #shorts #reels"),
                "reference_blueprint": bp.get("reel_id", "none"),
            },
            f,
            indent=2,
        )

    print(f"[CloneStory] Generated {len(story['shots'])} rapid-cut shots using blueprint={bp.get('reel_id', 'default')}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python scripts/generate_cloned_story.py <PROJECT_DIR>")
    main(os.path.abspath(sys.argv[1]))
