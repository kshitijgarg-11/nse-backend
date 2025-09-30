from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from datetime import datetime
from pathlib import Path
import io
import zipfile
from nse import NSE

app = FastAPI()

# Directory path for temporary downloads
DOWNLOAD_DIR = Path("/tmp/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/api/fno-bhavcopy")
async def get_fno_bhavcopy(date_str: str):
    """
    Download F&O bhavcopy for given date and return it as CSV response.
    Example: /api/fno-bhavcopy?date_str=2025-09-29
    """
    try:
        print(f"Starting download for {date_str}")
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        nse = NSE(download_folder=str(DOWNLOAD_DIR), server=True, timeout=30)
        file_path = nse.fnoBhavcopy(datetime.combine(date_obj, datetime.min.time()))
        print(f"Downloaded to {file_path}")

        if not file_path.exists():
            raise FileNotFoundError(f"Downloaded file not found: {file_path}")

        # ✅ Read into memory first
        csv_bytes = file_path.read_bytes()
        buffer = io.BytesIO(csv_bytes)

        return StreamingResponse(
            buffer,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="fno_bhavcopy_{date_str}.csv"'}
        )

    except zipfile.BadZipFile as e:
        print(f"ZIP error: {e}")
        raise HTTPException(status_code=500, detail=f"Invalid ZIP from NSE: {str(e)}")
    except PermissionError as e:
        print(f"Permission error: {e}")
        raise HTTPException(status_code=500, detail=f"File access error: {str(e)}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Bhavcopy not available for this date.")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"NSE data unavailable: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
    finally:
        # ✅ Always close session and delete temp files
        if 'nse' in locals():
            nse.exit()
        for file in DOWNLOAD_DIR.glob("*"):
            file.unlink(missing_ok=True)
        print("Cleanup complete")


@app.get("/")
def root():
    """Health check endpoint"""
    return {"message": "NSE F&O Bhavcopy Backend is running!"}


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
