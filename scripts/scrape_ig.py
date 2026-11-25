import glob
import json
import os
import re
import subprocess
import urllib.request

TARGET_USER = os.environ.get("IG_TARGET_USER", "craftee_films").strip().lstrip("@")
MAX_REELS = int(os.environ.get("MAX_REELS_PER_RUN", "5"))
RAW_DIR = os.path.abspath("vault/raw")
META_DIR = os.path.abspath("vault/raw_meta")


def save_meta(vid: str, source_url: str, platform: str, caption: str = "", views: int = 0, duration: float = 0):
    meta_path = os.path.join(META_DIR, f"{vid}.json")
    if not os.path.exists(meta_path):
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": vid,
                    "source": source_url,
                    "platform": platform,
                    "username": TARGET_USER,
                    "caption": caption,
                    "views": views,
                    "duration": duration,
                },
                f,
                indent=2,
            )


def download_direct_mp4(url: str, out_path: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(out_path, "wb") as f:
            f.write(resp.read())
        return os.path.exists(out_path) and os.path.getsize(out_path) > 15_000
    except Exception:
        if os.path.exists(out_path):
            os.remove(out_path)
        return False


def layer1_curl_cffi_ig(username: str, max_count: int) -> list[str]:
    """Cookie-free Instagram public web profile + embed MP4 fetcher."""
    from curl_cffi import requests as cffi_req

    downloaded = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "X-IG-App-ID": "936619743392459",
    }
    api_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    r = cffi_req.get(api_url, headers=headers, impersonate="chrome", timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"IG web_profile_info HTTP {r.status_code}")

    data = r.json()
    edges = (
        data.get("data", {})
        .get("user", {})
        .get("edge_owner_to_timeline_media", {})
        .get("edges", [])
    )

    for edge in edges:
        node = edge.get("node", {})
        if not node.get("is_video"):
            continue
        sc = node.get("shortcode")
        if not sc:
            continue
        mp4_path = os.path.join(RAW_DIR, f"{sc}.mp4")
        if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 15_000:
            continue

        video_url = node.get("video_url")
        if not video_url:
            emb = cffi_req.get(f"https://www.instagram.com/reel/{sc}/embed/captioned/", impersonate="chrome", timeout=20)
            m = re.search(r'"video_url":"(https:[^"]+)"', emb.text)
            if m:
                video_url = m.group(1).replace("\\u0026", "&").replace("\\/", "/")

        if video_url and download_direct_mp4(video_url, mp4_path):
            cap_edges = node.get("edge_media_to_caption", {}).get("edges", [])
            cap = cap_edges[0]["node"]["text"] if cap_edges else ""
            save_meta(sc, f"https://www.instagram.com/reel/{sc}/", "instagram", cap, node.get("video_view_count", 0))
            downloaded.append(sc)
            if len(downloaded) >= max_count:
                break

    return downloaded


def layer2_ytdlp_shorts(query_or_url: str, platform: str, max_count: int) -> list[str]:
    """Downloads short vertical Roblox stories (<= 90s) via yt-dlp without cookies."""
    archive_file = os.path.join(RAW_DIR, "downloaded_ids.txt")
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--ignore-errors",
        "--download-archive", archive_file,
        "--playlist-end", "35",
        "--max-downloads", str(max_count),
        "--match-filter", "duration >= 20 & duration <= 95",
        "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "--merge-output-format", "mp4",
        "-o", os.path.join(RAW_DIR, "%(id)s.%(ext)s"),
        "--write-info-json",
        query_or_url,
    ]
    subprocess.run(cmd, check=False)

    downloaded = []
    for info_file in glob.glob(os.path.join(RAW_DIR, "*.info.json")):
        try:
            info = json.load(open(info_file, encoding="utf-8"))
            vid = info.get("id")
            mp4_path = os.path.join(RAW_DIR, f"{vid}.mp4")
            if vid and os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 15_000:
                save_meta(
                    vid,
                    info.get("webpage_url", query_or_url),
                    platform,
                    info.get("description") or info.get("title") or "",
                    info.get("view_count") or 0,
                    info.get("duration") or 0,
                )
                downloaded.append(vid)
        finally:
            if os.path.exists(info_file):
                os.remove(info_file)
    return downloaded


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(META_DIR, exist_ok=True)
    print(f"[Scraper] Harvesting up to {MAX_REELS} new videos for @{TARGET_USER} (cookie-free)...", flush=True)

    downloaded = []

    # 1. Cookie-free Instagram Chrome-TLS scraper
    try:
        downloaded.extend(layer1_curl_cffi_ig(TARGET_USER, MAX_REELS))
    except Exception as e:
        print(f"[Layer 1 IG] Skipped ({e})", flush=True)

    # 2. YouTube Shorts filter URL (sp=EgIYAQ%3D%3D forces <4 min / Shorts only) for exact @craftee_films / In This Town series
    queries = [
        "https://www.youtube.com/results?search_query=In+This+Town+Roblox+Stories+%23shorts&sp=EgIYAQ%253D%253D",
        "https://www.youtube.com/results?search_query=In+This+World+Roblox+Stories+%23shorts&sp=EgIYAQ%253D%253D",
        "https://www.youtube.com/results?search_query=craftee_films+roblox+%23shorts&sp=EgIYAQ%253D%253D",
        "https://www.youtube.com/@gopal70374/shorts",
    ]
    for q in queries:
        if len(downloaded) >= MAX_REELS:
            break
        need = MAX_REELS - len(downloaded)
        print(f"[Layer 2 Shorts] Searching ({need} needed): {q}", flush=True)
        downloaded.extend(layer2_ytdlp_shorts(q, "youtube_shorts", need))

    print(f"[Scraper] Finished! Newly harvested IDs: {downloaded}", flush=True)


if __name__ == "__main__":
    main()
