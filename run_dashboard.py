#!/usr/bin/env python3
"""Run the MACS+ Automation dashboard and open it in your browser.

- Sets PYTHON32 automatically if you use 64-bit Python (so COM runs via 32-bit).
- Starts the server on http://localhost:8000 and opens that URL in the browser.

Usage (from project root):
    python run_dashboard.py
"""

import os
import sys
import threading
import webbrowser

# Project root = parent of directory containing this script
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

HOST = "localhost"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def _ensure_python32():
    """Set PYTHON32 in this process if we're 64-bit and can find 32-bit Python."""
    if sys.maxsize <= 2**32:
        return  # 32-bit process, no bridge needed
    if os.environ.get("PYTHON32"):
        return
    try:
        from macs_automation.engine import _find_python32
        exe = _find_python32()
        if exe:
            os.environ["PYTHON32"] = exe
            print(f"Using 32-bit Python for COM: {exe}")
        else:
            print(
                "Warning: 64-bit Python detected but no 32-bit Python found. "
                "Set PYTHON32 to your 32-bit python.exe for real calculations."
            )
    except Exception:
        pass


def main():
    os.chdir(PROJECT_ROOT)
    print("Starting MACS+ Automation dashboard...")
    print(f"Server: {URL}")
    print("Press Ctrl+C to stop.\n")
    _ensure_python32()
    threading.Timer(2.0, lambda: webbrowser.open(URL)).start()

    import uvicorn
    uvicorn.run("macs_automation.app:app", host=HOST, port=PORT, reload=True)


if __name__ == "__main__":
    main()
