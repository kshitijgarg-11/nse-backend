from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from datetime import datetime
from pathlib import Path
import os
import zipfile  # Added for explicit ZIP handling
from nse import NSE

app = FastAPI()

DOWNLOAD_DIR = Path("/tmp/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.get("/api/fno-bhavcopy")
async def get_fno_bhavcopy(date_str: str):
    try:
        print(f"Starting download for {date_str}")  # Log start
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        nse = NSE(download_folder=str(DOWNLOAD_DIR), server=True, timeout=30)
        file_path = nse.fnoBhavcopy(datetime.combine(date_obj, datetime.min.time()))
        print(f"Downloaded to {file_path}")  # Log success

        # Verify file exists and is CSV
        if not file_path.exists():
            raise FileNotFoundError(f"Downloaded file not found: {file_path}")

        return FileResponse(
            path=file_path,
            media_type="text/csv",
            filename=f"fno_bhavcopy_{date_str}.csv"
        )
    except zipfile.BadZipFile as e:
        print(f"ZIP error: {e}")  # Log ZIP issue
        raise HTTPException(status_code=500, detail=f"Invalid ZIP from NSE: {str(e)}")
    except PermissionError as e:
        print(f"Permission error: {e}")  # Log file access issue
        raise HTTPException(status_code=500, detail=f"File access error: {str(e)}")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Bhavcopy not available for this date.")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"NSE data unavailable: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__}: {str(e)}")  # Log full error
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
    finally:
        if 'nse' in locals():
            nse.exit()
        for file in DOWNLOAD_DIR.glob("*"):
            file.unlink(missing_ok=True)
        print("Cleanup complete")  # Log cleanup

@app.get("/")
def root():
    return {"message": "NSE F&O Bhavcopy Backend is running!"}
