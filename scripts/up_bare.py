import os
import sys
import time
import pathlib
import subprocess
import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)

RUN_DIR = ROOT / "run"
REPORTS_DIR = ROOT / "reports"
RUN_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Stop existing if any
for pid_file in RUN_DIR.glob("*.pid"):
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 9 if sys.platform != "win32" else 15)
    except Exception:
        pass
    pid_file.unlink(missing_ok=True)

creation_flags = 0
if sys.platform == "win32":
    creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

def start_region(region: str, port: int):
    env = os.environ.copy()
    env["REGION"] = region
    env["STATE_DIR"] = f"state/region-{region}"
    env["WARMUP_SECONDS"] = env.get("WARMUP_SECONDS", "6")
    log_file = open(RUN_DIR / f"region-{region}.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags
    )
    (RUN_DIR / f"region-{region}.pid").write_text(str(proc.pid))
    print(f"region-{region} pid={proc.pid} port={port}")

start_region("a", 8001)
start_region("b", 8002)

env_edge = os.environ.copy()
env_edge["EDGE_TTL_SECONDS"] = env_edge.get("EDGE_TTL_SECONDS", "5")
edge_log = open(RUN_DIR / "edge.log", "w", encoding="utf-8")
proc_edge = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "edge.proxy:app", "--host", "127.0.0.1", "--port", "8080", "--log-level", "warning"],
    env=env_edge,
    stdout=edge_log,
    stderr=subprocess.STDOUT,
    creationflags=creation_flags
)
(RUN_DIR / "edge.pid").write_text(str(proc_edge.pid))
print(f"edge pid={proc_edge.pid} port=8080")

print("cho service len (toi da 10s)...")
ok = True
for name, port in [("region-a", 8001), ("region-b", 8002), ("edge", 8080)]:
    up = False
    endpoint = "/healthz" if "region" in name else "/edge/state"
    for _ in range(10):
        try:
            r = httpx.get(f"http://127.0.0.1:{port}{endpoint}", timeout=1.0)
            if r.status_code == 200:
                up = True
                break
        except Exception:
            pass
        time.sleep(1)
    if up:
        print(f"  {name} (port {port}): UP")
    else:
        print(f"  {name} (port {port}): KHONG PHAN HOI -- xem run/{name}.log")
        ok = False

if not ok:
    print("MOT SO SERVICE CHUA LEN -- doc log truoc khi chay drill")
    sys.exit(1)

try:
    r = httpx.get("http://127.0.0.1:8080/edge/state", timeout=2.0)
    print(r.json())
except Exception as e:
    print(f"Error checking edge/state: {e}")
