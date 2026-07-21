import subprocess
import sys
import os

if __name__ == "__main__":
    api = subprocess.Popen([
        sys.executable, "-m", "uvicorn",
        "api.server:app",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--reload"
    ])
    print("API running at http://localhost:8000")
    print("Open http://localhost:8000 in your browser")
    try:
        api.wait()
    except KeyboardInterrupt:
        api.terminate()
