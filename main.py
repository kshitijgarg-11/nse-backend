from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from datetime import datetime
from pathlib import Path
import os
from nse import NSE

app = FastAPI()

DOWNLOAD_DIR = Path("/tmp/downloads")  # Use /tmp for writable directory in serverless
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.get("/api/fno-bhavcopy")
async def get_fno_bhavcopy(date_str: str):
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        nse = NSE(download_folder=str(DOWNLOAD_DIR), server=True, timeout=30)
        file_path = nse.fnoBhavcopy(datetime.combine(date_obj, datetime.min.time()))
        return FileResponse(
            path=file_path,
            media_type="text/csv",
            filename=f"fno_bhavcopy_{date_str}.csv"
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Bhavcopy not available for this date.")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"NSE data unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if 'nse' in locals():
            nse.exit()
        for file in DOWNLOAD_DIR.glob("*"):
            file.unlink(missing_ok=True)

@app.get("/")
def root():
    return {"message": "NSE F&O Bhavcopy Backend is running!"}
