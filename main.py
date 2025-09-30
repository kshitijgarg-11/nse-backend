from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime
from pathlib import Path
import os, zipfile
import httpx
from nse import NSE

app = FastAPI()

# Env var (from Vercel project settings when you connected the Blob store)
BLOB_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN")

# Private API endpoint
BLOB_ACCOUNT_URL = "https://blob.vercel-storage.com"

# ✅ Public base URL from your dashboard (store_UZpK3bfdP24xejlb)
BLOB_PUBLIC_BASE = "https://uzpk3bfdp24xejlb.public.blob.vercel-storage.com"

# Temp dir for serverless
DOWNLOAD_DIR = Path("/tmp/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def get_blob_meta_url(key: str) -> str | None:
    """Get metadata (including correct public URL) for a blob key."""
    meta_url = f"{BLOB_ACCOUNT_URL}/{key}?meta"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(meta_url, headers={"Authorization": f"Bearer {BLOB_TOKEN}"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        meta = r.json()
    # Prefer official meta url, else build from base
    return meta.get("url") or f"{BLOB_PUBLIC_BASE}{meta['pathname']}"


async def blob_exists(key: str) -> str | None:
    """Return public URL if blob exists, else None."""
    return await get_blob_meta_url(key)


async def blob_upload(key: str, data: bytes, content_type="text/csv") -> str:
    """Upload new file to Blob, mark it public, return its public CDN URL."""
    url = f"{BLOB_ACCOUNT_URL}/{key}"
    async with httpx.AsyncClient(timeout=60) as client:
        # Upload call
        r = await client.put(
            url,
            headers={
                "Authorization": f"Bearer {BLOB_TOKEN}",
                "Content-Type": content_type,
                "x-vercel-blob-public": "true",   # mark uploaded file public
            },
            content=data,
        )
        r.raise_for_status()

    # Resolve final public URL
    public_url = await get_blob_meta_url(key)
    if not public_url:
        raise RuntimeError("Upload succeeded but could not get public URL")
    return public_url


@app.get("/api/fno-bhavcopy")
async def get_fno_bhavcopy(date_str: str):
    """Main endpoint for bhavcopy, with caching in Vercel Blob."""
    filename = f"fno_bhavcopy_{date_str}.csv"
    blob_key = f"/bhavcopies/{filename}"

    try:
        # 1. Try cache
        cached_url = await blob_exists(blob_key)
        if cached_url:
            print(f"✅ Cache hit: {blob_key}")
            return RedirectResponse(cached_url, status_code=302)

        # 2. Download from NSE if not cached
        print(f"❌ Cache miss for {date_str} → fetching from NSE...")
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        nse = NSE(download_folder=str(DOWNLOAD_DIR), server=True, timeout=60)
        local_file = nse.fnoBhavcopy(datetime.combine(date_obj, datetime.min.time()))
        if not local_file.exists():
            raise FileNotFoundError(f"No file from NSE for {date_str}")

        # 3. Upload to Blob
        data = local_file.read_bytes()
        public_url = await blob_upload(blob_key, data)
        print(f"⬆ Uploaded {blob_key} → {public_url}")

        # 4. Redirect browser
        return RedirectResponse(public_url, status_code=302)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No Bhavcopy for {date_str}")
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=500, detail=f"Bad NSE ZIP: {e}")
    except Exception as e:
        print(f"Unexpected {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {e}")
    finally:
        if "nse" in locals():
            nse.exit()
        for f in DOWNLOAD_DIR.glob("*"):
            f.unlink(missing_ok=True)


@app.get("/")
def index():
    return {"message": "NSE F&O Bhavcopy with Blob caching", "downloader": "/downloader"}


@app.get("/downloader", response_class=HTMLResponse)
def serve_downloader():
    html_path = Path(__file__).parent / "BHAVCOPY_DOWNLOADER.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Downloader not found")
    return html_path.read_text(encoding="utf-8")
