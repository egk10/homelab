# Ceph reliability implementation — 2026-10-05

## Completed and verified

- Preserved 721 PGs active+clean and 9 OSDs up/in during monitor/SSH/service recovery. Subsequently reintegrated OSD 8 after separate authorization and observed its recovery/backfill to completion: final 721 PGs active+clean, 10 OSDs UP/IN.
- Deployed third monitor `mon.minipcamd4` on `100.90.57.27`, with existing monitors `eliedesk` and `minipcamd` retained. Quorum now contains all three; monmap epoch 12.
- New monitor systemd unit active/running and enabled for boot. Host has approximately 638 GiB free on the root filesystem; no reboot or disk manipulation performed.
- Restored orchestrator backend `cephadm`, initially paused during original-photo extraction, then resumed after extraction and reviewed service specs and empty queues. Final status: backend available, paused false.
- Corrected Ceph SSH port for five mini hosts: port 2222, existing conventional sshd. Cloudvero/eliedesk retain port 22. Cluster root SSH public key appended idempotently on minipcamd2/3, where it was missing. No tailnet ACL, firewall, password-authentication or root-login policy changes.
- `ceph cephadm check-host` successful for all five mini hosts; inventory no longer marks hosts Offline.
- Set `unmanaged: true` on automatic `osd.all-available-devices` and RGW specs, preserving remaining fields. This prevents implicit formatting of available devices or redeployment of the healthy gateway from actual port 7480 to stale spec port 80.
- Installed a separate `homelab-reliability.conf` drop-in on all seven hosts: start after/want tailscaled, unlimited recovery retries (`StartLimitIntervalSec=0`), 30-second restart delay. Verified effective properties on each host. Reloaded systemd only; no healthy daemon restarted. This fixes the observed 5-failures-in-30-minutes trap that left daemons failed indefinitely after quorum loss. Ordering tailscaled does not guarantee the tailnet is connected; continued retries cover delayed network recovery.
- Recovered six previously failed ceph-exporters and the failed eliedesk MDS using targeted systemd starts. All six exporters returned HTTP 200 with Ceph metrics. CephFS has its original active MDS plus a working eliedesk standby.
- Removed exactly three obsolete scheduled actions pointing to nonexistent mgr/RGW daemons, after private cache snapshots. Removed the seven restart requests generated during this intervention after each daemon was proven healthy. All seven host queues were verified empty before resumption.
- Recovered exact existing OSD 8 on minipcamd3 after FSID/device identity validation, initially with a per-OSD `noin` flag protecting against its automatic autoout-to-in transition. Verified UP/OUT, then after root verification explicitly marked OSD 8 IN and cleared only its noin flag. 10 OSDs UP and 10 IN; recovery/backfill started 17:34:03 UTC and completed by 17:54:02 UTC, confirmed again at 17:54:23 UTC. All 721 PGs active+clean, zero degraded/misplaced objects, recovery/backfill rate zero at completion. Disabled only the stale OSD 8 boot symlink on minipcamd2, where no corresponding data directory exists; cleared only its obsolete failed state, leaving it disabled/inactive. Healthy OSD 4 remained active.
- After scheduler resumption, refreshed daemon inventory has no failed daemons. Container IDs of all daemons running before resumption remained unchanged; no healthy daemon restart observed. Final remaining warning is MON_DISK_LOW. No scoped noin flag remains.

## Operational details

Snapshots were written before changes into this directory (mode 0700). No SSH private keys are retained here. Specs snapshots and before/after health evidence are private operational artifacts. `cephctl.py` uses the exact existing Ceph 19.2.3 image and current `/etc/ceph` credentials without printing credentials.

Commands used to pause safely and reload only the orchestrator module:

1. `ceph config-key set mgr/cephadm/pause true`.
2. Update the two stored service specs to unmanaged.
3. `ceph mgr module disable cephadm` and `ceph mgr module enable cephadm`.
4. `ceph orch set backend cephadm`; verify `ceph orch status` reports paused.

Monitor placement dry run added only minipcamd4 and removed no monitors. Applied explicit three-host placement, then directly deployed `ceph orch daemon add mon minipcamd4:100.90.57.27` while scheduler remained paused. No live OSD, MDS, existing monitor or RGW daemon was restarted.

## Remaining operational decisions

- Scheduler is resumed. OSD-allavailable and RGW should remain unmanaged until separately reviewed specs replace them. Systemd restart/boot activation is also active.
- `MON_DISK_LOW` still flags eliedesk (approximately 21% available, warning threshold 30%); monitor database is only 88 MiB. `/var/log/ceph` occupies 8 GiB and system journal approximately 4 GiB. No logs or unrelated files were removed.
- OSD 8 was recovered UP/OUT after extraction, then reintegrated UP/IN after separate authorization; recovery/backfill completed. Temporary PG_DEGRADED during recovery was kept visible and cleared naturally. No disk formatting, orphan data deletion, bucket repair, or recovery tuning performed.

### Follow-up read-only OSD 8 audit

- Correct host minipcamd3 has whoami `8`, cluster FSID matching this cluster, and OSD FSID `06021b69-1ab7-4ac6-91f7-424866166c3d`, consistent across monitor map, daemon directory and LVM tags. Existing block device `/dev/ceph-vg/osd-lv` is approximately 852.8 GiB. No formatting is required to start its existing daemon.
- minipcamd2 had a stale enabled/failed OSD 8 systemd instance but no `osd.8` data directory. Its existing Ceph LV belongs to healthy OSD 4, UUID `ca74367f-7fa1-4e6a-a625-fc80a3c9186f`; do not start OSD 8 there. Its stale OSD 8 boot symlink was disabled after authorization.
- OSD 8 has state `autoout`, and `mon_osd_auto_mark_auto_out_in=true`. Starting it without precautions would automatically mark it in and potentially cause backfill, even without an explicit `ceph osd in` command. A separately authorized UP/OUT recovery can first apply a per-OSD `noin` flag (`ceph osd set-group noin osd.8`), start only minipcamd3's exact existing unit, verify UP/OUT and clean PGs, then clear only that scoped flag. The OSD remains OUT after startup while noin was active; future startup without noin may mark it in again if autoout remains.
- Scheduler resumption review: all host scheduled-action queues are empty, all placement sizes match current running counts except crash daemons (3/7). Both generic OSD and OSD-allavailable service specs are unmanaged; Ceph 19.2.3 source explicitly skips reconciliation of unmanaged services. RGW remains unmanaged. Resumption may propagate new monmap configuration and recover crash daemons, but no healthy restart request is queued.

[Monitor auto-IN configuration reference](https://docs.ceph.com/en/squid/rados/configuration/mon-osd-interaction/); [scoped OSD flags](https://docs.ceph.com/en/reef/rados/operations/health-checks/).

## RGW logging inspection

Read-only configuration inspection: `debug_rgw=1/5`, operation log disabled, usage log disabled, nonexistent-bucket log disabled. Historical missing-object investigations may therefore lack detailed request records. No verbose logging or `radosgw-admin` repair mutations were performed. Operation logs can contain private object paths and should be planned with retention/access controls if enabled later.

## Final evidence

- `status.after.json`, `quorum.after.json`, `orchestrator.final.json`, `osd-dump.final-reintegration.json` — final live status.
- `osd8-reintegration-observation.jsonl` — timestamped recovery/backfill observations.
- `status.final-osd8-reintegration.json` — second consecutive all-clean observation at 17:54:23 UTC.
- `daemon-inventory.after.json`, `services.after.yaml`, `hosts.after.json` — final managed service/host state.
- No failover fault injection performed while photo extraction depends on stable storage. Three healthy monitor members provide quorum tolerance to one monitor failure, but tailnet/site/power dependencies remain.

## Official references

- [MON placement and manual additions](https://docs.ceph.com/en/squid/cephadm/services/mon/)
- [Ceph SSH configuration](https://docs.ceph.com/en/squid/cephadm/host-management/)
- [Cephadm pause/recovery](https://docs.ceph.com/en/squid/cephadm/troubleshooting/)
