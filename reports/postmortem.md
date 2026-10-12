# Postmortem - DR Drill Lab 23

Bao cao phan tich su co theo chuan Blameless Postmortem (SRE).

## 1. Timeline

| ISO time | Su kien | Evidence |
|---|---|---|
| 2026-10-12T06:54:35 | Outage bat dau (Region A bi netblock) | `chaos/chaos-events.jsonl:3` |
| 2026-10-12T06:54:35 | User dau tien gap loi (ReadTimeout 503) | `reports/drill-2-withdr.jsonl:11` |
| 2026-10-12T06:54:52 | Health check alert (chuyen UNHEALTHY sau 3 lan fail) | `reports/health-events.jsonl:2` |
| 2026-10-12T06:54:53 | Operator confirm va kich hoat cutover | `reports/runbook-run.jsonl:2` |
| 2026-10-12T06:55:00 | GPU Pool warm-up xong tren Region B | `reports/failover-events.jsonl:4` |
| 2026-10-12T06:55:00 | DNS/LB cutover sang Region B | `reports/failover-events.jsonl:5` |
| 2026-10-12T06:55:02 | Resolved (Request thanh cong dau tien tu Region B) | `reports/drill-2-withdr.jsonl:23` |

## 2. RTO/RPO do duoc vs muc tieu - Gap o buoc nao?

- RTO muc tieu: 300s | do duoc: `26.9s` | gap: -273.1s (dat vuot muc tieu)
- RPO muc tieu: 300s | do duoc: `4.46s` (`6` doc bi mat) | gap: -295.54s
- **Buoc ton nhieu giay nhat:** `Health-check detection floor` (ton 15.0s, chiem 55.8% tong RTO) - vi he thong phai cho du 3 lan poll lien tiep x 5s de dam bao khong bi false alarm do mang rung lac. Buoc thu hai la GPU warm-up (6.72s).

## 3. Root cause (5 Whys)

1. *Tai sao he thong ngung phuc vu?* Do Region A bi network partition khong tra loi HTTP request.
2. *Tai sao Region B khong serve ngay lap tuc?* Do he thong thiet ke theo mo hinh Active-Passive Warm Standby de tiet kiem chi phi GPU, Region B can warm-up GPU pool va restore snapshot state.
3. *Tai sao can phai cho den 15s moi bat dau failover?* Do co che anti-flapping threshold yeu cau 3 failures lien tiep.
4. *Neu day la outage that ngoai production, buoc nao trong runbook co the that bai?* Buoc restore snapshot co the that bai neu snapshot replication bi cham hoac storage replica bi nghẽn bang thong.
5. *Tai sao can con nguoi confirm?* Tranh hien tuong split-brain va flapping hai chieu khi ha tang mang bi lag tam thoi.

## 4. Action items (co owner + deadline)

| # | Action item | Owner | Deadline | Giam RTO/RPO bao nhieu giay |
|---|---|---|---|---|
| 1 | Cai dat streaming replication realtime cho Vector DB thay vi snapshot batch | Data Platform | 2026-11-01 | Giam RPO tu 4.5s xuong < 1s |
| 2 | Toi uu thoi gian warmup GPU pool bang cach preload weights vao host RAM | AI Serving Team | 2026-11-15 | Giam RTO ~3s |
| 3 | Tich hop PagerDuty auto-trigger webhooks cho incident commander | SRE Team | 2026-11-20 | Giam notification delay ~5s |

## 5. Ba cau hoi bat buoc tra loi

1. **`interval x threshold` cua ban la bao nhieu giay? No chiem bao nhieu % RTO?**
   - `interval x threshold` = 5.0s x 3 = 15.0s.
   - No chiem 15.0s / 26.9s = **55.8%** tong thoi gian RTO.
2. **Neu ha interval xuong 1s, RTO giam may giay - va ban tra gia gi (§4 flapping)?**
   - Neu ha interval xuong 1s voi threshold 3, detection floor giam tu 15s xuong 3s, giup RTO giam 12s.
   - Cai gia phai tra la nguy co **Flapping**: bat ky dot sut giam mang ngan (micro-outage hoac packet loss trong 3s) se kich hoat failover sai lam sang Region B, lam gian doan request dang xu ly va tieu ton tai nguyen scale pool khong can thiet.
3. **Neu outage keo dai 6 gio va region chinh mat du lieu vinh vien, `docs_lost` cua ban co nghia gi voi khach hang?**
   - `docs_lost = 6 documents` la so luong ban ghi duoc ingest vao Region A trong 4.46 giay cuoi cung truoc khi outage xay ra ma chua kip sao chep sang snapshot.
   - Voi khach hang, 6 tai lieu nay se khong the truy van duoc trong Vector DB sau khi failover sang Region B. He thong can replay lai log tu Message Queue (Kafka/RabbitMQ) hoac yeu cau nguoi dung tai lai cac tai lieu da upload trong cua so 4.5s nay de tai lap tinh toan ven du lieu 100%.
