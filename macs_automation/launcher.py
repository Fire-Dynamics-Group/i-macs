"""MACS+ Automation — Desktop launcher.

Opens the browser and starts the FastAPI server.
Usage: python -m macs_automation.launcher
"""

import threading
import webbrowser

import uvicorn

URL = "http://localhost:8000"


def main():
    print("Starting MACS+ Automation...")
    print(f"Opening {URL} in your browser...")
    threading.Timer(2.0, lambda: webbrowser.open(URL)).start()
    uvicorn.run("macs_automation.app:app", host="localhost", port=8000)


if __name__ == "__main__":
    main()
