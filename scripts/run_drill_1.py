import os
import sys
import time
import json
import signal
import pathlib
import subprocess
import httpx

# Ignore SIGINT on Windows so background jobs are not interrupted by console events
if hasattr(signal, "SIGINT"):
    signal.signal(signal.SIGINT, signal.SIG_IGN)

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)

RUN_DIR = ROOT / "run"
REPORTS_DIR = ROOT / "reports"
RUN_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# 1. Don dep PID cu
for pid_file in RUN_DIR.glob("*.pid"):
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 15)
    except Exception:
        pass
    pid_file.unlink(missing_ok=True)

# 2. Seed data cho Drill 1
print("1. Seeding data cho Drill 1...")
subprocess.run([sys.executable, "state/seed_vectors.py", "--region", "a", "--docs", "200"], check=True)
subprocess.run([sys.executable, "state/seed_vectors.py", "--region", "b", "--docs", "0", "--weights-mb", "0"], check=True)
pathlib.Path("edge/active_region").write_text("a")
pathlib.Path("chaos/chaos-events.jsonl").unlink(missing_ok=True)
pathlib.Path("reports/drill-1-nodr.jsonl").unlink(missing_ok=True)

# 3. Khoi dong 3 dich vu
print("2. Khoi dong 3 dich vu...")
flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

def spawn(cmd, env_vars, log_name):
    env = os.environ.copy()
    env.update(env_vars)
    f = open(RUN_DIR / log_name, "w", encoding="utf-8")
    return subprocess.Popen(cmd, env=env, stdout=f, stderr=subprocess.STDOUT, creationflags=flags)

p_a = spawn([sys.executable, "-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "8001", "--log-level", "warning"],
            {"REGION": "a", "STATE_DIR": "state/region-a", "WARMUP_SECONDS": "6"}, "region-a.log")
(RUN_DIR / "region-a.pid").write_text(str(p_a.pid))

p_b = spawn([sys.executable, "-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", "8002", "--log-level", "warning"],
            {"REGION": "b", "STATE_DIR": "state/region-b", "WARMUP_SECONDS": "6"}, "region-b.log")
(RUN_DIR / "region-b.pid").write_text(str(p_b.pid))

p_edge = spawn([sys.executable, "-m", "uvicorn", "edge.proxy:app", "--host", "127.0.0.1", "--port", "8080", "--log-level", "warning"],
               {"EDGE_TTL_SECONDS": "5"}, "edge.log")
(RUN_DIR / "edge.pid").write_text(str(p_edge.pid))

for name, port in [("region-a", 8001), ("region-b", 8002), ("edge", 8080)]:
    endpoint = "/healthz" if "region" in name else "/edge/state"
    for _ in range(15):
        try:
            r = httpx.get(f"http://127.0.0.1:{port}{endpoint}", timeout=1.0)
            if r.status_code == 200:
                print(f"  {name} UP")
                break
        except Exception:
            pass
        time.sleep(1)

# 4. Sinh tai: 16s tai 2 RPS
print("3. Bat dau sinh tai (loadgen)...")
p_load = subprocess.Popen([sys.executable, "loadgen/traffic.py", "--duration", "16", "--rps", "2", "--out", "reports/drill-1-nodr.jsonl"],
                          creationflags=flags)

# Cho 4s roi kill Region A
print("4. Cho 4s roi kill Region A...")
time.sleep(4)

print("5. Danh sap Region A...")
subprocess.run([sys.executable, "chaos/kill_region.py", "--region", "a", "--mode", "netblock", "--mock"], check=True)

# Cho loadgen xong
print("6. Cho loadgen ket thuc...")
p_load.wait()

# 5. Do RTO Drill 1
print("7. Do RTO Drill 1...")
res = subprocess.run([sys.executable, "tools/measure_rto.py", "--loadgen", "reports/drill-1-nodr.jsonl", "--target-rto", "300"],
                     capture_output=True, text=True, check=True)
print(res.stdout)
pathlib.Path("reports/measure-drill-1.json").write_text(res.stdout)

# 6. Restore va dung services
print("8. Khoi phuc va don dep...")
subprocess.run([sys.executable, "chaos/kill_region.py", "restore", "--region", "a", "--backend", "bare"], check=True)
p_a.terminate()
p_b.terminate()
p_edge.terminate()
print("DRILL_1_HOAN_THANH_THANH_CONG")
