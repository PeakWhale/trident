import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from server import app
import uvicorn

def main():
    print("🔱 Starting Trident Medical Triage System...")
    print("🌐 Server will be available at http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
