# TelTest Stage 10 — Scheduler and Watch

## Principle

The extraction scheduler is intentionally not a permanently-running
Python daemon.

A systemd timer wakes a short-lived worker once per minute.

The worker first checks SQLite using only the Python standard library.

If no extraction job is due, it exits immediately without importing
Flask, Telethon or the full TelTest application.

This reduces idle RAM and CPU usage.

## Job Watch

Each extraction job supports:

- watch_enabled
- poll_interval_minutes
- cursor_external_id
- next_run_at
- scheduler_failures
- scheduler_backoff_until
- scheduler_last_tick

## Incremental mode

Once a watched Telegram job has a Cursor, all scheduled runs request
only messages newer than that Cursor.

Old messages are not scanned again.

## Backlog

If a scheduled run reaches the configured max_items limit, TelTest
assumes more messages may still be waiting.

The next run is scheduled one minute later to drain the backlog.

After the backlog is drained, the normal polling interval is restored.

## Failure backoff

Repeated failures use exponential backoff capped at 60 minutes.

Example with a 5 minute base interval:

- failure 1 → 5 min
- failure 2 → 10 min
- failure 3 → 20 min
- failure 4 → 40 min
- failure 5+ → 60 min

A successful run resets the failure counter.

## Concurrency

`flock` prevents overlapping scheduler workers.

A scheduler tick processes at most three due jobs sequentially.

This is intentional to keep CPU, RAM and disk load predictable.

## systemd

- teltest-scheduler.service
- teltest-scheduler.timer

The timer itself consumes effectively no application RAM between runs.
