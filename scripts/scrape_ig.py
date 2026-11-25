import json
import os
import time
import urllib.error
import urllib.request

TARGET_USER = os.environ.get("IG_TARGET_USER", "craftee_films").strip().lstrip("@")
MAX_REELS = int(os.environ.get("MAX_REELS_PER_RUN", "25"))
RAW_DIR = os.path.abspath("vault/raw")
META_DIR = os.path.abspath("vault/raw_meta")
REELS_DATASET_ID = "gd_lyclm20il4r5helnj"


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


def fetch_via_sdk(token: str, profile_url: str, max_reels: int) -> list[dict]:
    from brightdata import SyncBrightDataClient

    with SyncBrightDataClient(api_token=token, auto_create_zones=False) as client:
        result = client.search.instagram.reels_all(
            profile_url,
            num_of_posts=max_reels,
            timeout=420,
        )
    data = getattr(result, "data", None)
    if isinstance(data, list):
        return data
    if isinstance(result, list):
        return result
    return []


def fetch_via_rest_api(token: str, profile_url: str, max_reels: int) -> list[dict]:
    """Direct Bright Data Web Scraper REST API fallback."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    trigger_url = (
        f"https://api.brightdata.com/datasets/v3/trigger"
        f"?dataset_id={REELS_DATASET_ID}&include_errors=true&type=discover_new&discover_by=url"
    )
    payload = json.dumps([{"url": profile_url, "num_of_posts": max_reels}]).encode("utf-8")
    req = urllib.request.Request(trigger_url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        snap = json.loads(resp.read().decode("utf-8"))

    snapshot_id = snap.get("snapshot_id")
    if not snapshot_id:
        raise RuntimeError(f"No snapshot_id returned: {snap}")

    print(f"[BrightData REST] Triggered snapshot {snapshot_id}, polling for results...", flush=True)
    progress_url = f"https://api.brightdata.com/datasets/v3/progress/{snapshot_id}"
    for _ in range(60):
        time.sleep(6)
        preq = urllib.request.Request(progress_url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(preq, timeout=30) as presp:
            pinfo = json.loads(presp.read().decode("utf-8"))
        status = pinfo.get("status", "")
        if status == "ready":
            break
        if status == "failed":
            raise RuntimeError(f"Bright Data snapshot failed: {pinfo}")

    dl_url = f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}?format=json"
    dreq = urllib.request.Request(dl_url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(dreq, timeout=60) as dresp:
        items = json.loads(dresp.read().decode("utf-8"))
    return items if isinstance(items, list) else []


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(META_DIR, exist_ok=True)

    token = os.environ.get("BRIGHTDATA_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing BRIGHTDATA_API_TOKEN in GitHub Secrets!")

    profile_url = f"https://www.instagram.com/{TARGET_USER}/"
    print(f"[BrightData] Fetching up to {MAX_REELS} Reels from {profile_url}...", flush=True)

    reels = []
    try:
        reels = fetch_via_sdk(token, profile_url, MAX_REELS)
    except Exception as sdk_err:
        print(f"[BrightData SDK] Falling back to REST API ({sdk_err})...", flush=True)
        reels = fetch_via_rest_api(token, profile_url, MAX_REELS)

    print(f"[BrightData] Received {len(reels)} Reel records from Instagram.", flush=True)
    downloaded = []

    for item in reels:
        if not isinstance(item, dict):
            continue
        sc = str(item.get("shortcode") or item.get("id") or item.get("post_id") or "").strip()
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
