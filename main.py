from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
from datetime import datetime
from pathlib import Path
import io, zipfile
from nse import NSE
from vercel_blob import VercelBlob

app = FastAPI()

# Blob client (takes token from env var: BLOB_READ_WRITE_TOKEN)
blob = VercelBlob()

# Local temporary directory inside serverless root (/tmp is ephemeral but fine for staging downloads)
DOWNLOAD_DIR = Path("/tmp/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/api/fno-bhavcopy")
async def get_fno_bhavcopy(date_str: str):
    """
    Download F&O bhavcopy for given date.
    - If cached in Vercel Blob → return instantly.
    - Else fetch from NSE → upload → return.
    Example: /api/fno-bhavcopy?date_str=2025-09-29
    """
    filename = f"fno_bhavcopy_{date_str}.csv"
    blob_key = f"bhavcopies/{filename}"

    try:
        # 1. Check cache in Vercel Blob
        file_info = await blob.head(blob_key)
        if file_info:
            print(f"✅ Cache hit: {blob_key}")
            url = await blob.get_url(blob_key)
            # Redirect so browser downloads directly from Vercel Blob CDN
            return RedirectResponse(url, status_code=302)

        print(f"❌ Cache miss for {date_str} → downloading from NSE...")
        # 2. Download from NSE
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        nse = NSE(download_folder=str(DOWNLOAD_DIR), server=True, timeout=30)
        local_file = nse.fnoBhavcopy(datetime.combine(date_obj, datetime.min.time()))

        if not local_file.exists():
            raise FileNotFoundError(f"NSE did not return file for {date_str}")

        # Read into memory
        data = local_file.read_bytes()

        # 3. Upload file to Vercel Blob for future requests
        await blob.put(blob_key, data, content_type="text/csv")
        print(f"⬆️ Uploaded {blob_key} to Blob storage")

        # 4. Stream response to current user
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
        print(f"Unexpected error: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if 'nse' in locals():
            nse.exit()
        # Clean up /tmp (Vercel ephemeral anyway)
        for f in DOWNLOAD_DIR.glob("*"):
            f.unlink(missing_ok=True)


@app.get("/")
def root():
    """Health check + small landing page"""
    return {
        "message": "NSE F&O Bhavcopy Backend with Vercel Blob Cache is running!",
        "downloader_url": "/downloader"
    }


@app.get("/downloader", response_class=HTMLResponse)
def serve_downloader():
    """
    Serve the HTML downloader frontend.
    Ensure BHAVCOPY_DOWNLOADER.html is placed in project root.
    """
    html_path = Path(__file__).parent / "BHAVCOPY_DOWNLOADER.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Downloader page not found")
    return html_path.read_text(encoding="utf-8")
