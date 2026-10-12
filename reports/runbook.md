# Runbook 1 trang - Region chinh Down

Huong dan van hanh ung pho su co (Incident Response Runbook) danh cho On-call Engineer luc 3h sang.

| # | Buoc | Lenh copy-paste | Biet la xong khi | Ai lam |
|---|---|---|---|---|
| 1 | Xac nhan outage | `python chaos/kill_region.py status` | Endpoint /readyz va /healthz cua region-a tra ve false hoac timeout 3 lan lien tiep | On-call SRE |
| 2 | Mo incident + bam gio RTO | `python dr/runbook.py --primary a --target b --backend fs` | Dong log `thong_bao_incident` duoc ghi vao `reports/runbook-run.jsonl`, Slack/PagerDuty co alert | Incident Commander |
| 3 | Restore state o region phu | `python state/snapshot.py get --region b --backend fs` | `state/region-b/vectors.sqlite` co data (>0 docs), manifest version khop | Data Engineer / SRE |
| 4 | Scale pool warm->full | `echo full > state/region-b/pool_state` | `curl -s localhost:8002/readyz` tra ve HTTP 200 `ready:true` sau WARMUP_SECONDS | SRE |
| 5 | DNS/LB cutover | `echo b > edge/active_region` | `curl -s localhost:8080/edge/state` tra ve `active_region:b` | SRE |
| 6 | Verify golden signals | `python -c "import httpx; print([httpx.get('http://localhost:8080/v1/infer').status_code for _ in range(10)])"` | 10 request deu tra 200, p95 latency < 300ms, error rate = 0% | QA / SRE |
| 7 | Do RTO + postmortem | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | Log `measure_rto.py` tra ve `rto_verdict: PASS` va RTO < 300s | SRE Lead |

## Dieu kien Rollback (Failover nguoc ve Region A)
1. **Dieu kien tien quyet:** Region A phai on dinh tro lai, pass `/readyz` lien tuc trong it nhat 15 phut khong flap. Du lieu phat sinh tai Region B trong thoi gian outage phai duoc replicate nguoc ve Region A (sync reverse) de tranh split-brain hoac mat du lieu moi.
2. **Tham quyen quyet dinh:** Chi co Incident Commander (IC) hoac Tech Lead he thong moi co quyen ra lenh rollback sau khi co bien ban xac nhan dong bo state hoan tat.
3. **Chong Flapping (Circuit Breaker):** Tuyet doi khong tu dong rollback bang script. Bat buoc xac nhan thu cong (manual approval) de tranh hien tuong 2 region lien tuc gianh giat traffic.
