import json
import os
import urllib.request

TARGET_USER = os.environ.get("IG_TARGET_USER", "craftee_films").strip().lstrip("@")
MAX_REELS = int(os.environ.get("MAX_REELS_PER_RUN", "25"))
RAW_DIR = os.path.abspath("vault/raw")
META_DIR = os.path.abspath("vault/raw_meta")


def download_mp4(url: str, out_path: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(out_path, "wb") as f:
            f.write(resp.read())
        return os.path.exists(out_path) and os.path.getsize(out_path) > 15_000
    except Exception as e:
        print(f"[Download WARN] {e}", flush=True)
        if os.path.exists(out_path):
            os.remove(out_path)
        return False


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(META_DIR, exist_ok=True)

    token = os.environ.get("BRIGHTDATA_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing BRIGHTDATA_API_TOKEN in GitHub Secrets!")

    from brightdata import SyncBrightDataClient

    profile_url = f"https://www.instagram.com/{TARGET_USER}/"
    print(f"[BrightData] Fetching up to {MAX_REELS} Reels from {profile_url}...", flush=True)

    with SyncBrightDataClient(api_token=token, auto_create_zones=False) as client:
        result = client.search.instagram.reels_all(
            profile_url,
            num_of_posts=MAX_REELS,
            timeout=420,
        )

    reels = getattr(result, "data", None) or (result if isinstance(result, list) else [])
    downloaded = []

    for item in reels:
        if not isinstance(item, dict):
            continue
        sc = item.get("shortcode") or item.get("id") or item.get("post_id")
        video_url = item.get("video_url") or item.get("url_video")
        if not sc or not video_url:
            continue

        mp4_path = os.path.join(RAW_DIR, f"{sc}.mp4")
        if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 15_000:
            continue

        if download_mp4(video_url, mp4_path):
            with open(os.path.join(META_DIR, f"{sc}.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "id": sc,
                        "source": item.get("url", f"https://www.instagram.com/reel/{sc}/"),
                        "platform": "instagram",
                        "username": TARGET_USER,
                        "caption": item.get("description") or item.get("caption") or "",
                        "views": item.get("video_view_count") or item.get("views") or 0,
                        "date_posted": item.get("date_posted", ""),
                    },
                    f,
                    indent=2,
                )
            downloaded.append(sc)
            print(f"[BrightData] Downloaded {sc}.mp4", flush=True)

    print(f"[Scraper] Finished! Downloaded {len(downloaded)} new @craftee_films Reels: {downloaded}", flush=True)


if __name__ == "__main__":
    main()
