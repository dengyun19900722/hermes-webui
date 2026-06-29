# Log Context API

WebUI can render `hermes-log://context` links in chat answers and resolve them
through a controlled backend API. The browser never receives SSH credentials and
never sends shell commands. WebUI validates the configured source, log path,
line number, context window, and path allowlist, then runs a fixed expect-based
SSH connector that executes a fixed remote `awk` reader.

The API can resolve the SSH target in two ways:

- `source=...`: use a fully configured source from `log_context_sources`.
- `host_ip=...&account=...`: look up the SSH host/account/password from a
  **Neo4j graph** (the only supported lookup backend). If `source` is also
  present, WebUI uses that source as the log-policy template (`roots`, suffixes,
  context limits) and only gets the target host credentials from Neo4j.

## Configuration

Add sources to the active Hermes `config.yaml`:

```yaml
log_context_sources:
  zk-app-01:
    mode: expect_ssh
    host: 10.10.20.11
    port: 22
    user: logreader
    password_env: ZK_APP_01_LOG_PASSWORD
    roots:
      - /data/app/logs
      - /var/log/zk
    timeout_seconds: 8
    max_context_lines: 500
    max_response_bytes: 1048576
    allowed_suffixes:
      - .log
      - .txt
      - .out
```

Set the password outside the YAML file:

```bash
export ZK_APP_01_LOG_PASSWORD='...'
```

Notes:

- `source` must match a configured key; clients cannot provide an arbitrary
  host.
- When `host_ip` is used, it must be a valid IPv4 or IPv6 address. `account`
  is optional only when the Neo4j node already names one.
- `path` must be absolute and must normalize under one of the configured
  `roots`.
- Inline `password` values in YAML are rejected. Use `password_env`; the API
  response and audit log never include password values.
- `allowed_suffixes` defaults to `.log`, `.txt`, and `.out`. Set it to an empty
  list only if the source account and roots are already tightly constrained.
- The WebUI host must have `expect` and `ssh` installed.

For a Neo4j asset graph/CMDB/图库, set these environment variables in the same
environment that starts WebUI:

```bash
export NEO4J_URI='bolt://127.0.0.1:7687'
export NEO4J_USER='neo4j'
export NEO4J_PASSWORD='...'
```

The graph lookup expects `Host` nodes with these properties:

```cypher
(:Host {
  ip: "10.10.20.11",
  hostname: "zk-app-01",
  os: "linux",
  ssh_user: "logreader",
  ssh_password: "...",
  ssh_port: 22
})
```

WebUI queries by IP only:

```cypher
MATCH (h:Host {ip: $host_ip})
RETURN h.ssh_user, h.ssh_password, h.ssh_port
```

Neo4j is the exclusive host lookup backend. If the driver is missing, the env
vars are not set, the connection fails, or no host is found, WebUI returns
`host_not_found`. There is no fallback to a static host inventory or external
lookup script. Neo4j may return the SSH password value directly; it is held
only in the in-process request object and passed to the expect connector
through `LOGCTX_PASSWORD`. It is not returned to the browser and is not written
to audit entries.

Without a `source` template, Neo4j host lookup defaults `roots` to `/` because
the host and credentials came from the trusted private graph. For tighter
control, include `source` in the request/link so the configured source's roots,
suffixes, and context limits still apply.

## Chat Link Format

A skill can emit:

```markdown
[zk-app-01 app.log:12345](hermes-log://context?source=zk-app-01&path=/data/app/logs/app.log&line=12345)
```

Or target a host by IP and account while using `zk-app-01` as the log-policy
template:

```markdown
[10.10.20.11 app.log:12345](hermes-log://context?source=zk-app-01&host_ip=10.10.20.11&account=logreader&path=/data/app/logs/app.log&line=12345)
```

The WebUI renderer turns this into a log-context reference. Clicking it opens a
dialog that calls `/api/log-context`.

## API

```http
GET /api/log-context?source=zk-app-01&path=/data/app/logs/app.log&line=12345&before=50&after=50&session_id=abc123
```

Host lookup form:

```http
GET /api/log-context?source=zk-app-01&host_ip=10.10.20.11&account=logreader&path=/data/app/logs/app.log&line=12345&before=50&after=50&session_id=abc123
```

Successful response:

```json
{
  "ok": true,
  "source": "zk-app-01",
  "host_ip": "10.10.20.11",
  "account": "logreader",
  "path": "/data/app/logs/app.log",
  "line": 12345,
  "start_line": 12295,
  "end_line": 12395,
  "before": 50,
  "after": 50,
  "requested_before": 50,
  "requested_after": 50,
  "lines": [
    {"no": 12345, "text": "ERROR connection timeout", "match": true}
  ],
  "truncated": false
}
```

Failure response:

```json
{
  "ok": false,
  "error": "log path is not allowed",
  "code": "path_not_allowed"
}
```

Each lookup writes an audit entry with category `log_context`, including
`source`, `host_ip`, `account`, `path`, `line`, `before`, `after`,
`client_ip`, `session_id`, and success/failure outcome.

## Manual API Test

1. Confirm the WebUI host can run the connector prerequisites:

   ```bash
   command -v expect
   command -v ssh
   ```

2. On the target server, prepare a readable file for the configured account:

   ```bash
   seq 1 200 | awk '{print "2026-06-10T10:00:" $1 "Z INFO sample line " $1}' > /data/app/logs/api-test.log
   ```

3. Export the password env var in the same environment that starts WebUI, then
   restart WebUI:

   ```bash
   export ZK_APP_01_LOG_PASSWORD='...'
   ./ctl.sh restart
   ```

4. Call the API:

   ```bash
   curl -sS 'http://127.0.0.1:8787/api/log-context?source=zk-gateway&host_ip=8.130.174.85&account=root&path=/opt/zk-ops/gateway/logs/app.log&line=100&before=3&after=2'
   ```

5. Expected result:

   - HTTP 200.
   - `ok` is `true`.
   - `start_line` is `97`; `end_line` is `102`.
   - `lines` contains line numbers 97 through 102.
   - The entry with `no: 100` has `match: true`.

6. Failure checks:

   ```bash
   curl -sS 'http://127.0.0.1:8787/api/log-context?source=missing&path=/data/app/logs/api-test.log&line=100'
   curl -sS 'http://127.0.0.1:8787/api/log-context?source=zk-app-01&path=/etc/passwd&line=1'
   curl -sS 'http://127.0.0.1:8787/api/log-context?source=zk-app-01&path=/data/app/logs/not-found.log&line=1'
   ```

   Expected codes in the JSON body are `source_not_found`, `path_not_allowed`,
   and `file_not_found`.
