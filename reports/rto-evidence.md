# RTO/RPO Evidence - Lab 23

Moi con so o day deu duoc do luong tu log that voi day du path:line theo dung tieu chuan kiem thu.

## 1. Drill 1 - Baseline khong co DR

| Chi so | Gia tri | Cach do | Evidence |
|---|---|---|---|
| t_outage | `2026-10-12T06:52:56` | chaos kill | `chaos/chaos-events.jsonl:1` |
| Request fail dau tien | `+0.1s` | dong `ok:false` dau tien sau t_outage | `reports/drill-1-nodr.jsonl:9` |
| Request thanh cong sau do | khong co | khong co dong `ok:true` nao sau t_outage | `reports/measure-drill-1.json:13` |
| RTO | `NO_RECOVERY` | `tools/measure_rto.py` | `reports/measure-drill-1.json:25` |

## 2. Drill 2 - Co DR

| Moc | +giay tu t_outage | Cach do | Evidence |
|---|---|---|---|
| t_outage (moc 0) | 0s | `action:kill` | `chaos/chaos-events.jsonl:3` |
| User thay loi dau tien | 0.0s | dong `ok:false` dau | `reports/drill-2-withdr.jsonl:11` |
| Health check phat hien | 16.9s | `to:UNHEALTHY, region:a` | `reports/health-events.jsonl:2` |
| Snapshot restore xong | 18.6s | `step:2_restore_snapshot` | `reports/failover-events.jsonl:2` |
| Region phu ready | 25.3s | `step:4_wait_ready` | `reports/failover-events.jsonl:4` |
| DNS cutover | 25.4s | `step:5_dns_cutover` | `reports/failover-events.jsonl:5` |
| **RTO do duoc** | 26.9s | dong `ok:true` dau sau loi | `reports/drill-2-withdr.jsonl:23` |

| Chi so | Do duoc | Muc tieu (slide 1) | Verdict |
|---|---|---|---|
| RTO - Inference API | `26.9s` | 300s (5 phut) | PASS |
| RPO - Vector DB | `4.46s` / `6` doc | 300s (5 phut) | PASS |

## 3. RTO cua toi gom nhung gi (Phan tich 4 thanh phan)

| Thanh phan | Giay | No den tu dau | Giam duoc bang cach nao |
|---|---|---|---|
| Health-check detect floor | 15.0s | `interval_s x threshold` trong `reports/health-events.jsonl:2` | Ha interval xuong 2s hoac threshold xuong 2 (nhung tang rui ro flapping) |
| Snapshot restore | 1.7s | 2_restore den 3_scale trong `reports/failover-events.jsonl:2` | Tang toc do copy snapshot hoac su dung pre-warmed replica streaming |
| GPU pool warm-up | 6.72s | `waited_s` o `4_wait_ready` trong `reports/failover-events.jsonl:4` | Giu san pool o trang thai warm hoac preload model weights vao VRAM |
| DNS/LB TTL cache | 1.5s | t_recovered tru t_cutover trong `reports/drill-2-withdr.jsonl:23` | Ha TTL cua Route53 / LB xuong 1s-2s hoac dung Anycast proxy |
