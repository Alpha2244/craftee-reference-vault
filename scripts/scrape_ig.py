import glob
import json
import os
import subprocess
import sys

TARGET_USER = os.environ.get("IG_TARGET_USER", "craftee_films").strip().lstrip("@")
MAX_REELS = int(os.environ.get("MAX_REELS_PER_RUN", "5"))
RAW_DIR = os.path.abspath("vault/raw")
META_DIR = os.path.abspath("vault/raw_meta")


def scrape_with_instaloader(username: str, max_count: int) -> list[str]:
    import instaloader

    L = instaloader.Instaloader(
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        dirname_pattern=RAW_DIR,
        filename_pattern="{shortcode}",
    )

    session_id = os.environ.get("IG_SESSIONID", "").strip()
    if session_id:
        L.context._session.cookies.set("sessionid", session_id, domain=".instagram.com")
        print("[IG] Loaded IG_SESSIONID cookie.", flush=True)

    profile = instaloader.Profile.from_username(L.context, username)
    downloaded = []

    for post in profile.get_posts():
        if not post.is_video:
            continue
        sc = post.shortcode
        mp4_path = os.path.join(RAW_DIR, f"{sc}.mp4")
        meta_path = os.path.join(META_DIR, f"{sc}.json")

        if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 10_000:
            print(f"[Skip] Already in vault: {sc}", flush=True)
            continue

        print(f"[Download] Fetching Reel {sc} (views={post.video_view_count})...", flush=True)
        L.download_post(post, target=RAW_DIR)

        # Clean extra txt files if created
        for extra in glob.glob(os.path.join(RAW_DIR, f"{sc}*.txt")):
            os.remove(extra)

        if os.path.exists(mp4_path):
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "id": sc,
                        "source": f"https://www.instagram.com/reel/{sc}/",
                        "username": username,
                        "caption": post.caption or "",
                        "views": post.video_view_count or 0,
                        "likes": post.likes or 0,
                        "duration": post.video_duration or 0,
                    },
                    f,
                    indent=2,
                )
            downloaded.append(sc)
            if len(downloaded) >= max_count:
                break

    return downloaded


def scrape_with_ytdlp_fallback(username: str, max_count: int) -> list[str]:
    """Fallback using yt-dlp if Instaloader hits an anonymous rate limit."""
    url = f"https://www.instagram.com/{username}/reels/"
    archive_file = os.path.join(RAW_DIR, "downloaded_ids.txt")
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--ignore-errors",
        "--download-archive", archive_file,
        "--playlist-end", str(max_count * 2),
        "--max-downloads", str(max_count),
        "-f", "mp4",
        "-o", os.path.join(RAW_DIR, "%(id)s.%(ext)s"),
        "--write-info-json",
        url,
    ]
    subprocess.run(cmd, check=False)
    downloaded = []
    for info_file in glob.glob(os.path.join(RAW_DIR, "*.info.json")):
        info = json.load(open(info_file, encoding="utf-8"))
        vid = info.get("id")
        if vid and os.path.exists(os.path.join(RAW_DIR, f"{vid}.mp4")):
            meta_path = os.path.join(META_DIR, f"{vid}.json")
            if not os.path.exists(meta_path):
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "id": vid,
                            "source": info.get("webpage_url", url),
                            "username": username,
                            "caption": info.get("description") or info.get("title") or "",
                            "views": info.get("view_count") or 0,
                            "likes": info.get("like_count") or 0,
                            "duration": info.get("duration") or 0,
                        },
                        f,
                        indent=2,
                    )
                downloaded.append(vid)
        os.remove(info_file)
    return downloaded


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(META_DIR, exist_ok=True)
    print(f"[Scraper] Scraping up to {MAX_REELS} new Reels from @{TARGET_USER}...", flush=True)

    try:
        ids = scrape_with_instaloader(TARGET_USER, MAX_REELS)
    except Exception as e:
        print(f"[WARN] Instaloader error ({e}); trying yt-dlp fallback...", flush=True)
        ids = scrape_with_ytdlp_fallback(TARGET_USER, MAX_REELS)

    print(f"[Scraper] Done. Newly downloaded Reels: {ids}", flush=True)


if __name__ == "__main__":
    main()
