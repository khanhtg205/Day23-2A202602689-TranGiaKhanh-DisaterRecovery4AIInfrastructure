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

# Kill any existing PIDs
for pid_file in RUN_DIR.glob("*.pid"):
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 15)
    except Exception:
        pass
    pid_file.unlink(missing_ok=True)

def spawn(cmd, env_vars, log_name):
    env = os.environ.copy()
    env.update(env_vars)
    f = open(RUN_DIR / log_name, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, env=env, stdout=f, stderr=subprocess.STDOUT)
    return proc

p_a = spawn([sys.executable, "-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "8001", "--log-level", "warning"],
            {"REGION": "a", "STATE_DIR": "state/region-a", "WARMUP_SECONDS": "6"}, "region-a.log")
(RUN_DIR / "region-a.pid").write_text(str(p_a.pid))
print(f"region-a pid={p_a.pid} port=8001", flush=True)

p_b = spawn([sys.executable, "-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "8002", "--log-level", "warning"],
            {"REGION": "b", "STATE_DIR": "state/region-b", "WARMUP_SECONDS": "6"}, "region-b.log")
(RUN_DIR / "region-b.pid").write_text(str(p_b.pid))
print(f"region-b pid={p_b.pid} port=8002", flush=True)

p_edge = spawn([sys.executable, "-m", "uvicorn", "edge.proxy:app", "--host", "127.0.0.1", "--port", "8080", "--log-level", "warning"],
               {"EDGE_TTL_SECONDS": "5"}, "edge.log")
(RUN_DIR / "edge.pid").write_text(str(p_edge.pid))
print(f"edge pid={p_edge.pid} port=8080", flush=True)

# Wait until up
for name, port in [("region-a", 8001), ("region-b", 8002), ("edge", 8080)]:
    endpoint = "/healthz" if "region" in name else "/edge/state"
    for _ in range(15):
        try:
            r = httpx.get(f"http://127.0.0.1:{port}{endpoint}", timeout=1.0)
            if r.status_code == 200:
                print(f"  {name} UP", flush=True)
                break
        except Exception:
            pass
        time.sleep(1)

print("ALL_SERVICES_READY", flush=True)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    p_a.terminate()
    p_b.terminate()
    p_edge.terminate()
