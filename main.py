from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime
from pathlib import Path
import os, zipfile
import httpx
from nse import NSE

app = FastAPI()

# Env var from Vercel
BLOB_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN")

# Blob private base
BLOB_ACCOUNT_URL = "https://blob.vercel-storage.com"

# Temp dir
DOWNLOAD_DIR = Path("/tmp/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def get_blob_meta_url(key: str) -> str:
    """Get metadata (including correct public URL) for a blob key."""
    meta_url = f"{BLOB_ACCOUNT_URL}/{key}?meta"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(meta_url, headers={"Authorization": f"Bearer {BLOB_TOKEN}"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        meta = r.json()
        return meta["url"]  # The real usable public URL


async def blob_exists(key: str) -> str:
    """Check if blob exists and return public URL if yes."""
    return await get_blob_meta_url(key)


async def blob_upload(key: str, data: bytes, content_type="text/csv") -> str:
    """Upload to Blob, set public flag, return correct CDN URL."""
    url = f"{BLOB_ACCOUNT_URL}/{key}"
    async with httpx.AsyncClient(timeout=60) as client:
        # Upload file
        r = await client.put(
            url,
            headers={
                "Authorization": f"Bearer {BLOB_TOKEN}",
                "Content-Type": content_type,
                "x-vercel-blob-public": "true",  # 👈 make public
            },
            content=data,
        )
        r.raise_for_status()

    # Get metadata right after upload
    meta_url = await get_blob_meta_url(key)
    if not meta_url:
        raise RuntimeError("Upload succeeded, but could not resolve Blob public URL")
    return meta_url


@app.get("/api/fno-bhavcopy")
async def get_fno_bhavcopy(date_str: str):
    """
    Bhavcopy API:
    1. If cached in Blob → redirect to its correct public URL
    2. If not cached → download NSE → upload to Blob → redirect
    """
    filename = f"fno_bhavcopy_{date_str}.csv"
    blob_key = f"bhavcopies/{filename}"

    try:
        # 1. Cache check
        cached_url = await blob_exists(blob_key)
        if cached_url:
            print(f"✅ Cache hit: {blob_key}")
            return RedirectResponse(cached_url, status_code=302)

        # 2. Cache miss → download from NSE
        print(f"❌ Cache miss for {date_str} → downloading from NSE")
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        nse = NSE(download_folder=str(DOWNLOAD_DIR), server=True, timeout=60)
        local_file = nse.fnoBhavcopy(datetime.combine(date_obj, datetime.min.time()))

        if not local_file.exists():
            raise FileNotFoundError(f"NSE did not provide file for {date_str}")

        # 3. Upload to Blob
        data = local_file.read_bytes()
        public_url = await blob_upload(blob_key, data)
        print(f"⬆ Uploaded {blob_key} → {public_url}")

        # 4. Redirect user to public CDN
        return RedirectResponse(public_url, status_code=302)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No Bhavcopy for {date_str}")
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=500, detail=f"Invalid ZIP from NSE: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__} → {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if "nse" in locals():
            nse.exit()
        for f in DOWNLOAD_DIR.glob("*"):
            f.unlink(missing_ok=True)


@app.get("/")
def root():
    return {"message": "NSE F&O Bhavcopy Backend with Blob cache (meta URLs)", "downloader": "/downloader"}


@app.get("/downloader", response_class=HTMLResponse)
def serve_downloader():
    html_path = Path(__file__).parent / "BHAVCOPY_DOWNLOADER.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Downloader not found")
    return html_path.read_text(encoding="utf-8")
