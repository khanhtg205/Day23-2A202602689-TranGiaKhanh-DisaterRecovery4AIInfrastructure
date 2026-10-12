"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n, name, **kw):
    """Ghi 1 dòng {ts, iso, step, name, ...} vào LOG."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "step": n,
        "name": name,
        **kw,
    }
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"RUNBOOK step {n} ({name}): {json.dumps(rec)}")
    return rec


def confirm(auto: bool, msg: str) -> bool:
    """auto=True -> True; ngược lại hỏi y/N. Đừng bỏ hàm này đi."""
    if auto:
        return True
    try:
        ans = input(msg).strip().lower()
        return ans in ("y", "yes")
    except EOFError:
        return True


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    """7 bước trên slide:
    1 xac_nhan_outage
    2 thong_bao_incident
    3 scale_gpu_pool (gọi failover.failover 1 lần duy nhất)
    4 verify_state_replica
    5 dns_cutover
    6 verify_golden_signals
    7 post_incident
    """
    t_start_runbook = time.time()
    from dr.health_checker import probe

    # Bước 1: Xác nhận outage
    prim_ok, prim_reason = probe(primary, timeout=1.5)
    tgt_ok, tgt_reason = probe(target, timeout=1.5)
    step(1, "xac_nhan_outage", primary=primary, target=target,
         primary_ready=prim_ok, primary_reason=prim_reason,
         target_ready=tgt_ok, target_reason=tgt_reason)

    # Bước 2: Thông báo incident
    chaos_file = pathlib.Path("chaos/chaos-events.jsonl")
    t_outage = None
    if chaos_file.exists():
        kills = [
            json.loads(l) for l in chaos_file.read_text().splitlines()
            if l.strip() and '"action": "kill"' in l or '"action":"kill"' in l
        ]
        if kills:
            t_outage = kills[-1].get("ts")

    ts_operator_knows = time.time()
    delay_s = round(ts_operator_knows - t_outage, 2) if t_outage else 0.0

    if not confirm(auto, f"Xác nhận kích hoạt failover từ region-{primary} sang region-{target}? (y/N): "):
        step(2, "thong_bao_incident", confirmed=False, reason="operator_rejected")
        return {"ok": False, "aborted": True, "reason": "Operator rejected failover"}

    step(2, "thong_bao_incident", confirmed=True, t_outage=t_outage,
         ts_operator_knows=ts_operator_knows, notification_delay_s=delay_s)

    # Bước 3: Scale GPU pool (gọi failover.failover(...) DUY NHẤT 1 LẦN)
    fo_res = fo.failover(target=target, backend=backend, wait=60.0)
    step(3, "scale_gpu_pool", ok=fo_res.get("ok"), target=target, result=fo_res)
    if not fo_res.get("ok"):
        return {"ok": False, "failed_step": 3, "failover_result": fo_res}

    # Bước 4: Verify state replica (đọc kết quả, không gọi lại failover)
    tgt_state = fo.state_of(target)
    step(4, "verify_state_replica",
         target=target,
         vector_count=tgt_state.get("count"),
         weights=tgt_state.get("weights"),
         rpo_seconds=fo_res.get("rpo_seconds"),
         docs_lost=fo_res.get("docs_lost"))

    # Bước 5: DNS cutover (kiểm tra active_region)
    active_path = pathlib.Path("edge/active_region")
    active_reg = active_path.read_text().strip() if active_path.exists() else None
    cutover_ok = (active_reg == target)
    step(5, "dns_cutover", active_region=active_reg, cutover_ok=cutover_ok)

    # Bước 6: Verify golden signals (10 request thật vào region phụ)
    latencies = []
    errors = 0
    for _ in range(10):
        t0 = time.time()
        try:
            r = httpx.get(f"{URL[target]}/v1/infer", timeout=5.0)
            latencies.append(round((time.time() - t0) * 1000, 2))
            if r.status_code != 200:
                errors += 1
        except Exception:
            errors += 1
        time.sleep(0.05)

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else None
    error_rate = round(errors / 10.0, 2)
    step(6, "verify_golden_signals", p95_latency_ms=p95, error_rate=error_rate, total_requests=10)

    # Bước 7: Post incident
    elapsed_s = round(time.time() - t_start_runbook, 2)
    measure_cmd = "python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300"
    step(7, "post_incident", elapsed_s=elapsed_s, measure_cmd=measure_cmd)

    return {
        "ok": True,
        "primary": primary,
        "target": target,
        "elapsed_s": elapsed_s,
        "failover_result": fo_res,
        "p95_latency_ms": p95,
        "error_rate": error_rate,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
