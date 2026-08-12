# P0 Online Baseline Result

- Base URL: `http://127.0.0.1:18812`
- Generated at: `2026-08-11T06:47:32Z`
- Server diagnostic records: `181`
- Validation: `PASS`

## Client Latency

| Endpoint | Status | p50 total | p95 total | p99 total | p50 TTFB |
|---|---:|---:|---:|---:|---:|
| agent_health | 200:30 | 10.481 ms | 13.472 ms | 14.039 ms | 10.33 ms |
| auth_status | 200:30 | 5.408 ms | 10.578 ms | 12.169 ms | 5.243 ms |
| cron_recent | 200:30 | 10.888 ms | 14.81 ms | 16.168 ms | 10.667 ms |
| dashboard_status | 200:30 | 12.075 ms | 16.844 ms | 17.562 ms | 11.838 ms |
| license_status | 200:30 | 3.956 ms | 6.811 ms | 6.957 ms | 3.879 ms |
| sessions | 200:30 | 30.891 ms | 53.857 ms | 54.349 ms | 30.356 ms |
| sessions_discovery | 200:1 | 34.182 ms | 34.182 ms | 34.182 ms | 31.327 ms |

## Server Stage Distribution

### `/api/auth/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.3 ms | 0.9 ms | 1.9 ms | 6.52% |
| handler | 0.7 ms | 2.1 ms | 3.1 ms | 15.22% |
| license_middleware | 2.8 ms | 7.0 ms | 7.3 ms | 60.87% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.2 ms | 0.5 ms | 0.5 ms | 4.35% |
| response_write | 0.35 ms | 1.1 ms | 1.9 ms | 7.61% |
| start | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |

### `/api/crons/recent`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.2 ms | 0.5 ms | 0.7 ms | 1.94% |
| handler | 6.95 ms | 10.6 ms | 10.9 ms | 67.48% |
| license_middleware | 2.65 ms | 4.6 ms | 5.8 ms | 25.73% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.2 ms | 0.5 ms | 0.9 ms | 1.94% |
| response_write | 0.2 ms | 0.4 ms | 0.6 ms | 1.94% |
| start | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |

### `/api/dashboard/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.2 ms | 0.5 ms | 0.8 ms | 1.8% |
| handler | 7.6 ms | 12.5 ms | 13.1 ms | 68.47% |
| license_middleware | 3.0 ms | 4.3 ms | 5.8 ms | 27.03% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.2 ms | 1.5 ms | 2.8 ms | 1.8% |
| response_write | 0.3 ms | 0.6 ms | 0.6 ms | 2.7% |
| start | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |

### `/api/health/agent`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.1 ms | 0.4 ms | 0.5 ms | 1.02% |
| handler | 5.55 ms | 8.7 ms | 10.2 ms | 56.35% |
| license_middleware | 2.9 ms | 6.6 ms | 7.4 ms | 29.44% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.2 ms | 1.9 ms | 2.5 ms | 2.03% |
| response_write | 0.2 ms | 1.1 ms | 1.6 ms | 2.03% |
| start | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |

### `/api/license/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.2 ms | 0.6 ms | 1.0 ms | 5.8% |
| handler | 2.65 ms | 4.0 ms | 4.2 ms | 76.81% |
| license_middleware | 0.15 ms | 0.6 ms | 0.7 ms | 4.35% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.1 ms | 1.4 ms | 1.8 ms | 2.9% |
| response_write | 0.2 ms | 0.6 ms | 0.8 ms | 5.8% |
| start | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |

### `/api/sessions`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| all_sessions | 0.0 ms | 0.7 ms | 0.7 ms | 0.0% |
| all_sessions.active_streams | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.index_exists | 0.1 ms | 0.4 ms | 0.4 ms | 0.33% |
| all_sessions.lineage_metadata_skipped | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.mark_streaming | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.overlay_lock | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.prune_index | 0.4 ms | 1.2 ms | 1.2 ms | 1.33% |
| all_sessions.read_index | 0.3 ms | 1.7 ms | 1.7 ms | 1.0% |
| all_sessions.refresh_sidecar_metadata | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.sort_filter | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.state_db_overrides | 0.2 ms | 0.6 ms | 0.6 ms | 0.67% |
| auth_middleware | 0.3 ms | 1.0 ms | 1.1 ms | 1.0% |
| cli_cap | 0.4 ms | 0.4 ms | 0.4 ms | 1.33% |
| filter_archived_sessions | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| get_cli_sessions | 8.4 ms | 17.8 ms | 17.8 ms | 28.0% |
| handler | 4.6 ms | 10.7 ms | 11.3 ms | 15.33% |
| license_middleware | 2.9 ms | 7.5 ms | 10.6 ms | 9.67% |
| load_settings | 0.3 ms | 0.9 ms | 1.5 ms | 1.0% |
| merge_cli_sessions | 0.1 ms | 0.5 ms | 0.5 ms | 0.33% |
| messaging_dedupe | 0.6 ms | 2.8 ms | 2.8 ms | 2.0% |
| normalize_cli_rows | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| profile_scope | 0.2 ms | 2.7 ms | 2.7 ms | 0.67% |
| reconcile_stale_stream_state | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.6 ms | 2.2 ms | 2.4 ms | 2.0% |
| response_write | 0.5 ms | 1.1 ms | 2.0 ms | 1.67% |
| session_list_cache_fallback_rebuild | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| session_list_cache_lookup | 4.0 ms | 9.0 ms | 9.5 ms | 13.33% |
| session_list_cache_rebuild_owner | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| session_list_cache_stored | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| session_list_cache_wait | 10.0 ms | 13.5 ms | 13.5 ms | 33.33% |
| session_list_cache_wait_stale | 11.35 ms | 14.4 ms | 14.4 ms | 37.83% |
| session_list_cache_wait_stale_fallback | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| sort_sessions | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| start | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| visible_lineage_metadata | 4.2 ms | 8.5 ms | 8.5 ms | 14.0% |
