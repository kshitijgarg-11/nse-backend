from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from datetime import datetime
import io
import zipfile
from nse import NSE

app = FastAPI()

@app.get("/api/fno-bhavcopy")
async def get_fno_bhavcopy(date_str: str):
    try:
        print(f"Starting download for {date_str}")
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        nse = NSE(download_folder="/tmp", server=True, timeout=30)

        # Force download into /tmp (NSE API behavior), then read into memory
        file_path = nse.fnoBhavcopy(datetime.combine(date_obj, datetime.min.time()))
        print(f"Downloaded to {file_path}")

        if not file_path.exists():
            raise FileNotFoundError(f"Downloaded file not found: {file_path}")

        # Read CSV into memory
        csv_bytes = file_path.read_bytes()
        buffer = io.BytesIO(csv_bytes)

        return StreamingResponse(
            buffer,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="fno_bhavcopy_{date_str}.csv"'
            }
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
        if 'nse' in locals():
            nse.exit()

@app.get("/")
def root():
    return {"message": "NSE F&O Bhavcopy Backend is running!"}
