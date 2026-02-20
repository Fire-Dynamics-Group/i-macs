"""MACS+ Launcher — thin entry point that starts the web UI and opens a browser.

This script is compiled into MACS+.exe via PyInstaller.  The exe bundles
Python and all third-party dependencies, but imports `macs_automation/`
from the adjacent folder at runtime so the scripts can be updated
independently of the exe.
"""

import os
import sys
import socket
import threading
import time
import webbrowser


def get_app_dir():
    """Directory containing the exe (or this script when running from source)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def main():
    app_dir = get_app_dir()

    # Import macs_automation from the adjacent folder, not from a bundle
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    os.chdir(app_dir)

    port = 8000
    if port_in_use(port):
        print(f"\n  Port {port} is already in use.")
        print(f"  The dashboard may already be running — check your browser.")
        print(f"  Opening http://localhost:{port} ...\n")
        webbrowser.open(f"http://localhost:{port}")
        input("  Press Enter to close this window.")
        return

    url = f"http://localhost:{port}"

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║         iMACS+ Automation v0.1             ║")
    print("  ║                                          ║")
    print("  ║  Starting server...                      ║")
    print(f"  ║  Dashboard: {url:<28s} ║")
    print("  ║                                          ║")
    print("  ║  Close this window to stop the server.   ║")
    print("  ╚══════════════════════════════════════════╝")
    print()

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    import uvicorn

    uvicorn.run("macs_automation.app:app", host="localhost", port=port)


if __name__ == "__main__":
    main()
