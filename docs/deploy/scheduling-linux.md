# Scheduling on Linux

`rag install` auto-schedules the nightly backup and maintenance jobs only on
macOS (via launchd). On Linux, run the jobs from cron or a systemd timer.

## cron

```cron
30 3 * * *  /path/to/.venv/bin/rag backup      >> ~/.agentic-rag/log/backup.log 2>&1
0  4 * * *  /path/to/.venv/bin/rag maintenance  >> ~/.agentic-rag/log/maintenance.log 2>&1
```

## systemd (user timers)

`~/.config/systemd/user/agentic-rag-backup.service`

```ini
[Unit]
Description=agentic-rag nightly backup
[Service]
Type=oneshot
ExecStart=%h/.venv/bin/rag backup
```

`~/.config/systemd/user/agentic-rag-backup.timer`

```ini
[Unit]
Description=Run agentic-rag backup at 03:30
[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
[Install]
WantedBy=timers.target
```

Enable: `systemctl --user enable --now agentic-rag-backup.timer`. Mirror the
same pair for `maintenance` at 04:00.
