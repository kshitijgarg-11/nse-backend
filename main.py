from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime
from pathlib import Path
import os, zipfile
import httpx
from nse import NSE

app = FastAPI()

# Env variable from Vercel
BLOB_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN")

# Blob endpoints
BLOB_ACCOUNT_URL = "https://blob.vercel-storage.com"  # private API (with auth)
BLOB_PUBLIC_URL = "https://nse-bhavcopy-cache.public.blob.vercel-storage.com"  # public CDN

# Temp dir in serverless
DOWNLOAD_DIR = Path("/tmp/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def blob_exists(key: str) -> bool:
    """Check if blob exists (HEAD on private API)."""
    url = f"{BLOB_ACCOUNT_URL}/{key}"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.head(url, headers={"Authorization": f"Bearer {BLOB_TOKEN}"})
        return r.status_code == 200


async def blob_upload(key: str, data: bytes, content_type="text/csv") -> str:
    """Upload to Blob. Mark object as public. Return the public CDN URL."""
    url = f"{BLOB_ACCOUNT_URL}/{key}"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.put(
            url,
            headers={
                "Authorization": f"Bearer {BLOB_TOKEN}",
                "Content-Type": content_type,
                "x-vercel-blob-public": "true",  # 👈 ensure it’s public
            },
            content=data,
        )
        r.raise_for_status()
    return f"{BLOB_PUBLIC_URL}/{key}"


@app.get("/api/fno-bhavcopy")
async def get_fno_bhavcopy(date_str: str):
    """
    Bhavcopy endpoint:
    - If cached in Blob → redirect to CDN
    - If not cached → fetch from NSE → upload to Blob → redirect to CDN
    """
    filename = f"fno_bhavcopy_{date_str}.csv"
    blob_key = f"bhavcopies/{filename}"

    try:
        # 1. Cache check
        if await blob_exists(blob_key):
            print(f"✅ Cache hit: {blob_key}")
            return RedirectResponse(f"{BLOB_PUBLIC_URL}/{blob_key}", status_code=302)

        # 2. Download from NSE
        print(f"❌ Cache miss for {date_str} → downloading from NSE...")
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        nse = NSE(download_folder=str(DOWNLOAD_DIR), server=True, timeout=60)
        local_file = nse.fnoBhavcopy(datetime.combine(date_obj, datetime.min.time()))

        if not local_file.exists():
            raise FileNotFoundError(f"NSE did not provide file for {date_str}")

        # 3. Read + upload to Blob
        data = local_file.read_bytes()
        public_url = await blob_upload(blob_key, data)
        print(f"⬆ Uploaded {blob_key} to Blob store (public)")

        # 4. Redirect user to CDN
        return RedirectResponse(public_url, status_code=302)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No Bhavcopy available for {date_str}")
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
    return {
        "message": "NSE F&O Bhavcopy Backend with Blob cache",
        "downloader_url": "/downloader",
    }


@app.get("/downloader", response_class=HTMLResponse)
def downloader():
    html_path = Path(__file__).parent / "BHAVCOPY_DOWNLOADER.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Downloader not found")
    return html_path.read_text(encoding="utf-8")
