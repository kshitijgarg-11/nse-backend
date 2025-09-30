from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
from datetime import datetime
from pathlib import Path
import io, zipfile, os
import httpx
from nse import NSE

app = FastAPI()

# Environment variables from Vercel
BLOB_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN")
BLOB_BASE_URL = "https://nse-bhavcopy-cache.public.blob.vercel-storage.com"

# Local temporary directory (/tmp is ephemeral but writable in Vercel serverless functions)
DOWNLOAD_DIR = Path("/tmp/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def blob_exists(key: str) -> bool:
    """Check if a blob exists in Vercel Blob store"""
    url = f"{BLOB_BASE_URL}/{key}"
    async with httpx.AsyncClient() as client:
        r = await client.head(url, headers={"Authorization": f"Bearer {BLOB_TOKEN}"})
        return r.status_code == 200


async def blob_upload(key: str, data: bytes, content_type="text/csv") -> str:
    """Upload data to Blob store and return its URL"""
    url = f"{BLOB_BASE_URL}/{key}"
    async with httpx.AsyncClient() as client:
        r = await client.put(
            url,
            headers={
                "Authorization": f"Bearer {BLOB_TOKEN}",
                "Content-Type": content_type,
            },
            content=data,
        )
        r.raise_for_status()
        return url  # Public URL to the blob


@app.get("/api/fno-bhavcopy")
async def get_fno_bhavcopy(date_str: str):
    """
    Download F&O bhavcopy for a given date.
    - If exists in Blob → redirect.
    - Else fetch from NSE → upload to Blob → return to user.
    Example: /api/fno-bhavcopy?date_str=2025-09-29
    """
    filename = f"fno_bhavcopy_{date_str}.csv"
    blob_key = f"bhavcopies/{filename}"

    try:
        # 1. Cache check
        if await blob_exists(blob_key):
            print(f"✅ Cache hit: {blob_key}")
            url = f"{BLOB_BASE_URL}/{blob_key}"
            return RedirectResponse(url, status_code=302)

        print(f"❌ Cache miss for {date_str} → downloading from NSE...")
        # 2. Download from NSE
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        nse = NSE(download_folder=str(DOWNLOAD_DIR), server=True, timeout=30)
        local_file = nse.fnoBhavcopy(datetime.combine(date_obj, datetime.min.time()))

        if not local_file.exists():
            raise FileNotFoundError(f"NSE did not return file for {date_str}")

        # Read file
        data = local_file.read_bytes()

        # 3. Upload to Blob for reuse
        await blob_upload(blob_key, data)
        print(f"⬆️ Uploaded {blob_key} to Blob storage")

        # 4. Respond to user now
        buffer = io.BytesIO(data)
        return StreamingResponse(
            buffer,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No Bhavcopy available for {date_str}")
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=500, detail=f"Invalid ZIP from NSE: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__} - {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if "nse" in locals():
            nse.exit()
        for f in DOWNLOAD_DIR.glob("*"):
            f.unlink(missing_ok=True)


@app.get("/")
def root():
    return {
        "message": "NSE F&O Bhavcopy Backend with Blob Cache is running!",
        "downloader_url": "/downloader",
    }


@app.get("/downloader", response_class=HTMLResponse)
def serve_downloader():
    html_path = Path(__file__).parent / "BHAVCOPY_DOWNLOADER.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Downloader page not found")
    return html_path.read_text(encoding="utf-8")
