# P0 Online Baseline Result

- Base URL: `http://127.0.0.1:18812`
- Generated at: `2026-08-11T06:46:41Z`
- Server diagnostic records: `181`
- Validation: `PASS`

## Client Latency

| Endpoint | Status | p50 total | p95 total | p99 total | p50 TTFB |
|---|---:|---:|---:|---:|---:|
| agent_health | 200:30 | 1.684 ms | 3.756 ms | 5.137 ms | 1.635 ms |
| auth_status | 200:30 | 0.926 ms | 4.825 ms | 5.525 ms | 0.888 ms |
| cron_recent | 200:30 | 1.818 ms | 4.042 ms | 5.139 ms | 1.774 ms |
| dashboard_status | 200:30 | 3.179 ms | 6.015 ms | 14.072 ms | 3.116 ms |
| license_status | 200:30 | 1.038 ms | 2.648 ms | 3.98 ms | 0.99 ms |
| sessions | 200:30 | 11.59 ms | 25.351 ms | 33.791 ms | 11.512 ms |
| sessions_discovery | 200:1 | 60.282 ms | 60.282 ms | 60.282 ms | 55.528 ms |

## Server Stage Distribution

### `/api/auth/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.1 ms | 0.1 ms | 0.2 ms | 14.29% |
| handler | 0.1 ms | 0.2 ms | 3.5 ms | 14.29% |
| license_middleware | 0.3 ms | 0.4 ms | 3.9 ms | 42.86% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.1 ms | 1.1 ms | 1.3 ms | 14.29% |
| response_write | 0.0 ms | 0.1 ms | 1.1 ms | 0.0% |
| start | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |

### `/api/crons/recent`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.1 ms | 0.3 ms | 0.8 ms | 6.67% |
| handler | 0.7 ms | 1.9 ms | 2.3 ms | 46.67% |
| license_middleware | 0.4 ms | 1.1 ms | 2.5 ms | 26.67% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.2 ms | 0.5 ms | 0.5 ms | 13.33% |
| response_write | 0.0 ms | 0.1 ms | 0.2 ms | 0.0% |
| start | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |

### `/api/dashboard/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.1 ms | 0.2 ms | 0.2 ms | 3.7% |
| handler | 1.8 ms | 3.4 ms | 12.2 ms | 66.67% |
| license_middleware | 0.45 ms | 1.3 ms | 1.7 ms | 16.67% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.2 ms | 0.7 ms | 0.7 ms | 7.41% |
| response_write | 0.0 ms | 0.0 ms | 0.1 ms | 0.0% |
| start | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |

### `/api/health/agent`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.1 ms | 0.2 ms | 0.2 ms | 7.14% |
| handler | 0.7 ms | 1.7 ms | 1.7 ms | 50.0% |
| license_middleware | 0.3 ms | 0.6 ms | 0.7 ms | 21.43% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.2 ms | 0.8 ms | 2.7 ms | 14.29% |
| response_write | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| start | 0.0 ms | 0.0 ms | 0.1 ms | 0.0% |

### `/api/license/status`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| auth_middleware | 0.1 ms | 0.2 ms | 0.3 ms | 14.29% |
| handler | 0.3 ms | 1.2 ms | 3.3 ms | 42.86% |
| license_middleware | 0.1 ms | 0.2 ms | 0.3 ms | 14.29% |
| request_entry | 0.0 ms | 0.0 ms | 0.1 ms | 0.0% |
| response_serialize | 0.1 ms | 0.8 ms | 1.1 ms | 14.29% |
| response_write | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |
| start | 0.0 ms | 0.1 ms | 0.1 ms | 0.0% |

### `/api/sessions`

| Stage | p50 | p95 | p99 | p50 share |
|---|---:|---:|---:|---:|
| all_sessions | 0.0 ms | 0.1 ms | 4.2 ms | 0.0% |
| all_sessions.active_streams | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.index_exists | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.lineage_metadata_skipped | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.mark_streaming | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.overlay_lock | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.prune_index | 0.1 ms | 0.3 ms | 0.8 ms | 0.88% |
| all_sessions.read_index | 0.0 ms | 0.2 ms | 0.3 ms | 0.0% |
| all_sessions.refresh_sidecar_metadata | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| all_sessions.sort_filter | 0.0 ms | 0.0 ms | 0.4 ms | 0.0% |
| all_sessions.state_db_overrides | 0.1 ms | 0.1 ms | 0.3 ms | 0.88% |
| auth_middleware | 0.1 ms | 0.3 ms | 0.8 ms | 0.88% |
| cli_cap | 0.4 ms | 0.4 ms | 0.6 ms | 3.54% |
| filter_archived_sessions | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| get_cli_sessions | 4.4 ms | 18.0 ms | 19.1 ms | 38.94% |
| handler | 0.6 ms | 0.8 ms | 1.6 ms | 5.31% |
| license_middleware | 0.5 ms | 1.0 ms | 7.5 ms | 4.42% |
| load_settings | 0.1 ms | 0.4 ms | 1.3 ms | 0.88% |
| merge_cli_sessions | 0.1 ms | 0.2 ms | 0.3 ms | 0.88% |
| messaging_dedupe | 0.2 ms | 0.4 ms | 0.6 ms | 1.77% |
| normalize_cli_rows | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| profile_scope | 0.1 ms | 0.1 ms | 0.2 ms | 0.88% |
| reconcile_stale_stream_state | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| request_entry | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| response_serialize | 0.3 ms | 1.7 ms | 4.4 ms | 2.65% |
| response_write | 0.2 ms | 0.6 ms | 1.1 ms | 1.77% |
| session_list_cache_lookup | 1.6 ms | 7.1 ms | 8.8 ms | 14.16% |
| session_list_cache_rebuild_owner | 0.0 ms | 0.0 ms | 0.6 ms | 0.0% |
| session_list_cache_stored | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| sort_sessions | 0.0 ms | 0.0 ms | 0.0 ms | 0.0% |
| start | 0.0 ms | 0.0 ms | 0.1 ms | 0.0% |
| visible_lineage_metadata | 1.7 ms | 3.2 ms | 7.9 ms | 15.04% |
