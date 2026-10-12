import os
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)

RUN_DIR = ROOT / "run"
if RUN_DIR.exists():
    for f in RUN_DIR.glob("*.pid"):
        try:
            pid = int(f.read_text().strip())
            if sys.platform == "win32":
                import ctypes
                try:
                    handle = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, pid)
                    ctypes.windll.ntdll.NtResumeProcess(handle)
                    ctypes.windll.kernel32.CloseHandle(handle)
                except Exception:
                    pass
                os.kill(pid, 15)
            else:
                import signal
                try:
                    os.kill(pid, signal.SIGCONT)
                except Exception:
                    pass
                os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
        f.unlink(missing_ok=True)
print("all stopped")
