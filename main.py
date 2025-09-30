from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from datetime import datetime
from pathlib import Path
import os
from nse import NSE  # Corrected import: lowercase 'nse'

app = FastAPI()

# Create a downloads folder if it doesn't exist
DOWNLOAD_DIR = Path("./downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

@app.get("/api/fno-bhavcopy")
async def get_fno_bhavcopy(date_str: str):
    try:
        # Parse the date (format: YYYY-MM-DD)
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        
        # Initialize NSE (use server=True for Vercel)
        nse = NSE(download_folder=str(DOWNLOAD_DIR), server=True)
        
        # Download the bhavcopy
        file_path = nse.fnoBhavcopy(datetime.combine(date_obj, datetime.min.time()))
        
        # Return the file
        return FileResponse(
            path=file_path,
            media_type="text/csv",
            filename=f"fno_bhavcopy_{date_str}.csv"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        # Clean up NSE session
        if 'nse' in locals():
            nse.exit()

# Health check endpoint (optional, for testing)
@app.get("/")
def root():
    return {"message": "NSE F&O Bhavcopy Backend is running!"}