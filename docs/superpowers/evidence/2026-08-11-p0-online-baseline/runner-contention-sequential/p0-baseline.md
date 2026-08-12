# P0 Online Baseline Result

- Base URL: `http://127.0.0.1:18812`
- Generated at: `2026-08-11T06:52:22Z`
- Server diagnostic records: `180`
- Validation: `PASS`

## Client Latency

| Endpoint | Status | p50 total | p95 total | p99 total | p50 TTFB |
|---|---:|---:|---:|---:|---:|
| agent_health | 200:30 | 16.314 ms | 196.384 ms | 398.183 ms | 14.594 ms |
| auth_status | 200:30 | 13.458 ms | 91.276 ms | 493.142 ms | 13.333 ms |
| cron_recent | 200:30 | 14.211 ms | 61.309 ms | 122.388 ms | 13.453 ms |
| dashboard_status | 200:30 | 34.767 ms | 544.243 ms | 1049.936 ms | 33.973 ms |
| license_status | 200:30 | 6.345 ms | 26.633 ms | 36.189 ms | 6.228 ms |
| sessions | 200:30 | 100.974 ms | 512.283 ms | 844.87 ms | 89.913 ms |
| sessions_discovery | 200:1 | 6036.554 ms | 6036.554 ms | 6036.554 ms | 6007.529 ms |

## Server Stage Distribution

### `/api/auth/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.4 ms | 13.2 ms | 89.8 ms | 4.17% |
| handler | 0.5 ms | 35.3 ms | 39.7 ms | 5.21% |
| license_middleware | 4.05 ms | 27.0 ms | 27.3 ms | 42.19% |
| request_entry | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| response_serialize | 1.15 ms | 10.8 ms | 305.0 ms | 11.98% |
| response_write | 0.15 ms | 1.2 ms | 12.6 ms | 1.56% |
| start | 0.0 ms | 0.2 ms | 0.8 ms | 0.0% |

### `/api/crons/recent`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.4 ms | 1.5 ms | 1.8 ms | 3.54% |
| handler | 5.4 ms | 32.4 ms | 97.7 ms | 47.79% |
| license_middleware | 3.2 ms | 16.6 ms | 17.0 ms | 28.32% |
| request_entry | 0.0 ms | 0.8 ms | 1.0 ms | 0.0% |
| response_serialize | 1.0 ms | 6.5 ms | 16.1 ms | 8.85% |
| response_write | 0.2 ms | 0.8 ms | 0.8 ms | 1.77% |
| start | 0.1 ms | 0.5 ms | 4.4 ms | 0.88% |

### `/api/dashboard/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.55 ms | 3.8 ms | 21.1 ms | 1.73% |
| handler | 23.55 ms | 352.7 ms | 994.7 ms | 74.17% |
| license_middleware | 4.05 ms | 23.7 ms | 35.5 ms | 12.76% |
| request_entry | 0.0 ms | 0.6 ms | 0.9 ms | 0.0% |
| response_serialize | 2.8 ms | 11.6 ms | 21.3 ms | 8.82% |
| response_write | 0.2 ms | 9.2 ms | 12.9 ms | 0.63% |
| start | 0.1 ms | 0.9 ms | 1.5 ms | 0.31% |

### `/api/health/agent`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.4 ms | 4.6 ms | 9.0 ms | 3.42% |
| handler | 4.4 ms | 39.9 ms | 139.7 ms | 37.61% |
| license_middleware | 2.5 ms | 24.3 ms | 31.6 ms | 21.37% |
| request_entry | 0.0 ms | 0.0 ms | 0.7 ms | 0.0% |
| response_serialize | 0.75 ms | 18.5 ms | 346.2 ms | 6.41% |
| response_write | 0.1 ms | 3.0 ms | 16.1 ms | 0.85% |
| start | 0.0 ms | 0.1 ms | 2.2 ms | 0.0% |

### `/api/license/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.4 ms | 1.5 ms | 1.9 ms | 9.3% |
| handler | 1.8 ms | 20.1 ms | 30.6 ms | 41.86% |
| license_middleware | 0.3 ms | 0.7 ms | 3.0 ms | 6.98% |
| request_entry | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| response_serialize | 0.7 ms | 2.9 ms | 5.1 ms | 16.28% |
| response_write | 0.2 ms | 1.5 ms | 3.6 ms | 4.65% |
| start | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |

### `/api/sessions`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| all_sessions | 0.2 ms | 0.9 ms | 27.9 ms | 0.25% |
| all_sessions.active_streams | 0.0 ms | 0.1 ms | 0.4 ms | 0.0% |
| all_sessions.index_exists | 0.0 ms | 0.6 ms | 0.6 ms | 0.0% |
| all_sessions.lineage_metadata_skipped | 0.0 ms | 0.1 ms | 0.2 ms | 0.0% |
| all_sessions.mark_streaming | 0.0 ms | 0.0 ms | 0.2 ms | 0.0% |
| all_sessions.overlay_lock | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.prune_index | 0.3 ms | 1.2 ms | 6.9 ms | 0.37% |
| all_sessions.read_index | 0.2 ms | 5.2 ms | 10.8 ms | 0.25% |
| all_sessions.refresh_sidecar_metadata | 0.0 ms | 0.6 ms | 0.9 ms | 0.0% |
| all_sessions.sort_filter | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| all_sessions.state_db_overrides | 0.2 ms | 1.6 ms | 1.8 ms | 0.25% |
| auth_middleware | 0.4 ms | 14.0 ms | 19.3 ms | 0.49% |
| cli_cap | 0.9 ms | 5.0 ms | 8.1 ms | 1.11% |
| filter_archived_sessions | 0.0 ms | 0.3 ms | 1.2 ms | 0.0% |
| get_cli_sessions | 33.45 ms | 260.5 ms | 449.3 ms | 41.35% |
| handler | 2.85 ms | 23.2 ms | 43.7 ms | 3.52% |
| license_middleware | 1.85 ms | 25.0 ms | 71.0 ms | 2.29% |
| load_settings | 0.4 ms | 7.8 ms | 11.2 ms | 0.49% |
| merge_cli_sessions | 0.4 ms | 2.5 ms | 13.3 ms | 0.49% |
| messaging_dedupe | 0.65 ms | 2.2 ms | 8.0 ms | 0.8% |
| normalize_cli_rows | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| profile_scope | 0.2 ms | 2.1 ms | 5.4 ms | 0.25% |
| reconcile_stale_stream_state | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| request_entry | 0.0 ms | 0.0 ms | 0.1 ms | 0.0% |
| response_serialize | 1.7 ms | 32.9 ms | 57.3 ms | 2.1% |
| response_write | 0.5 ms | 10.1 ms | 53.1 ms | 0.62% |
| session_list_cache_hit | 0.2 ms | 0.4 ms | 0.4 ms | 0.25% |
| session_list_cache_lookup | 14.05 ms | 277.9 ms | 279.8 ms | 17.37% |
| session_list_cache_rebuild_owner | 0.0 ms | 2.3 ms | 7.2 ms | 0.0% |
| session_list_cache_stored | 0.1 ms | 5.0 ms | 5.1 ms | 0.12% |
| sort_sessions | 0.0 ms | 0.1 ms | 0.2 ms | 0.0% |
| start | 0.1 ms | 1.4 ms | 3.5 ms | 0.12% |
| visible_lineage_metadata | 13.05 ms | 75.4 ms | 111.4 ms | 16.13% |
