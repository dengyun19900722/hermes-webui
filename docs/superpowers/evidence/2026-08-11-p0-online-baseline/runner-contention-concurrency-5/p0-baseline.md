# P0 Online Baseline Result

- Base URL: `http://127.0.0.1:18812`
- Generated at: `2026-08-11T06:56:00Z`
- Server diagnostic records: `180`
- Validation: `PASS`

## Client Latency

| Endpoint | Status | p50 total | p95 total | p99 total | p50 TTFB |
|---|---:|---:|---:|---:|---:|
| agent_health | 200:30 | 25.675 ms | 33.147 ms | 37.056 ms | 25.48 ms |
| auth_status | 200:30 | 23.14 ms | 88.528 ms | 89.443 ms | 22.265 ms |
| cron_recent | 200:30 | 24.947 ms | 36.646 ms | 37.623 ms | 24.163 ms |
| dashboard_status | 200:30 | 37.563 ms | 75.657 ms | 81.495 ms | 37.427 ms |
| license_status | 200:30 | 12.991 ms | 31.802 ms | 32.069 ms | 12.308 ms |
| sessions | 200:30 | 103.733 ms | 225.59 ms | 227.252 ms | 102.35 ms |
| sessions_discovery | 200:1 | 410.668 ms | 410.668 ms | 410.668 ms | 398.093 ms |

## Server Stage Distribution

### `/api/auth/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.9 ms | 3.6 ms | 6.1 ms | 4.35% |
| handler | 1.5 ms | 11.4 ms | 13.2 ms | 7.25% |
| license_middleware | 12.15 ms | 79.3 ms | 83.6 ms | 58.7% |
| request_entry | 0.0 ms | 0.0 ms | 0.1 ms | 0.0% |
| response_serialize | 0.9 ms | 4.4 ms | 70.5 ms | 4.35% |
| response_write | 0.8 ms | 3.6 ms | 4.5 ms | 3.86% |
| start | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |

### `/api/crons/recent`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.5 ms | 2.4 ms | 3.0 ms | 2.11% |
| handler | 14.85 ms | 23.9 ms | 25.8 ms | 62.79% |
| license_middleware | 6.25 ms | 14.2 ms | 18.5 ms | 26.43% |
| request_entry | 0.0 ms | 0.0 ms | 0.1 ms | 0.0% |
| response_serialize | 0.45 ms | 1.3 ms | 1.3 ms | 1.9% |
| response_write | 0.5 ms | 2.0 ms | 2.2 ms | 2.11% |
| start | 0.0 ms | 0.1 ms | 0.2 ms | 0.0% |

### `/api/dashboard/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.7 ms | 2.4 ms | 2.9 ms | 1.95% |
| handler | 24.25 ms | 52.8 ms | 60.5 ms | 67.64% |
| license_middleware | 8.55 ms | 20.4 ms | 20.7 ms | 23.85% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.7 ms | 3.6 ms | 8.3 ms | 1.95% |
| response_write | 0.5 ms | 2.5 ms | 3.0 ms | 1.39% |
| start | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |

### `/api/health/agent`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.55 ms | 1.8 ms | 1.9 ms | 2.24% |
| handler | 14.15 ms | 21.3 ms | 23.0 ms | 57.76% |
| license_middleware | 7.85 ms | 11.6 ms | 12.8 ms | 32.04% |
| request_entry | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| response_serialize | 0.45 ms | 1.6 ms | 3.0 ms | 1.84% |
| response_write | 0.6 ms | 1.9 ms | 2.4 ms | 2.45% |
| start | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |

### `/api/license/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.55 ms | 3.5 ms | 3.7 ms | 5.02% |
| handler | 7.2 ms | 24.3 ms | 28.5 ms | 65.75% |
| license_middleware | 0.4 ms | 3.6 ms | 3.8 ms | 3.65% |
| request_entry | 0.0 ms | 0.0 ms | 0.1 ms | 0.0% |
| response_serialize | 0.5 ms | 2.0 ms | 3.6 ms | 4.57% |
| response_write | 0.6 ms | 3.6 ms | 3.7 ms | 5.48% |
| start | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |

### `/api/sessions`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| all_sessions | 0.1 ms | 0.3 ms | 0.3 ms | 0.1% |
| all_sessions.active_streams | 0.0 ms | 0.2 ms | 0.2 ms | 0.0% |
| all_sessions.index_exists | 0.1 ms | 1.1 ms | 1.1 ms | 0.1% |
| all_sessions.lineage_metadata_skipped | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| all_sessions.mark_streaming | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.overlay_lock | 0.0 ms | 0.2 ms | 0.2 ms | 0.0% |
| all_sessions.prune_index | 1.4 ms | 5.9 ms | 5.9 ms | 1.47% |
| all_sessions.read_index | 0.6 ms | 5.0 ms | 5.0 ms | 0.63% |
| all_sessions.refresh_sidecar_metadata | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.sort_filter | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.state_db_overrides | 0.7 ms | 2.2 ms | 2.2 ms | 0.73% |
| auth_middleware | 0.85 ms | 4.2 ms | 6.8 ms | 0.89% |
| cli_cap | 1.0 ms | 2.3 ms | 2.3 ms | 1.05% |
| filter_archived_sessions | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| get_cli_sessions | 46.1 ms | 80.5 ms | 80.5 ms | 48.25% |
| handler | 13.4 ms | 28.9 ms | 43.3 ms | 14.02% |
| license_middleware | 7.5 ms | 21.1 ms | 21.2 ms | 7.85% |
| load_settings | 0.6 ms | 2.2 ms | 5.8 ms | 0.63% |
| merge_cli_sessions | 0.3 ms | 0.7 ms | 0.7 ms | 0.31% |
| messaging_dedupe | 1.9 ms | 11.8 ms | 11.8 ms | 1.99% |
| normalize_cli_rows | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| profile_scope | 0.4 ms | 2.8 ms | 2.8 ms | 0.42% |
| reconcile_stale_stream_state | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| request_entry | 0.0 ms | 0.1 ms | 0.2 ms | 0.0% |
| response_serialize | 0.8 ms | 6.4 ms | 7.4 ms | 0.84% |
| response_write | 1.2 ms | 5.1 ms | 12.2 ms | 1.26% |
| session_list_cache_fallback_rebuild | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| session_list_cache_hit | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| session_list_cache_lookup | 9.55 ms | 18.5 ms | 19.8 ms | 9.99% |
| session_list_cache_rebuild_owner | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| session_list_cache_stored | 0.1 ms | 0.4 ms | 0.4 ms | 0.1% |
| session_list_cache_wait | 39.25 ms | 80.3 ms | 80.3 ms | 41.08% |
| session_list_cache_wait_stale | 30.2 ms | 68.2 ms | 68.2 ms | 31.61% |
| session_list_cache_wait_stale_fallback | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| sort_sessions | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| start | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| visible_lineage_metadata | 13.5 ms | 35.6 ms | 35.6 ms | 14.13% |
