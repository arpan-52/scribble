import sys
from .plot_gui import plot_gui

def main():
    ms_path = sys.argv[1] if len(sys.argv) > 1 else None
    plot_gui(ms_path)
    import time
    # Block main process as server runs in background thread
    try:
        while True:
            time.sleep(100)
    except KeyboardInterrupt:
        print("\nExiting scribble.")