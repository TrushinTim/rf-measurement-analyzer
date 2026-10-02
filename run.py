from pathlib import Path
import os
import uvicorn

if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8003)
