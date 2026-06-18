#!/usr/bin/env bash
set -euo pipefail

: "${LOGCTX_HOST:?LOGCTX_HOST is required}"
: "${LOGCTX_PORT:?LOGCTX_PORT is required}"
: "${LOGCTX_USER:?LOGCTX_USER is required}"
: "${LOGCTX_PASSWORD:?LOGCTX_PASSWORD is required}"
: "${LOGCTX_REMOTE_COMMAND:?LOGCTX_REMOTE_COMMAND is required}"
: "${LOGCTX_TIMEOUT:=8}"

exec expect <<'EXPECT_EOF'
set timeout $env(LOGCTX_TIMEOUT)
log_user 1

spawn ssh \
  -p $env(LOGCTX_PORT) \
  -o BatchMode=no \
  -o NumberOfPasswordPrompts=1 \
  -o StrictHostKeyChecking=accept-new \
  -- "$env(LOGCTX_USER)@$env(LOGCTX_HOST)" "$env(LOGCTX_REMOTE_COMMAND)"

expect {
  -re "(?i)password:" {
    send -- "$env(LOGCTX_PASSWORD)\r"
    exp_continue
  }
  -re "(?i)permission denied|authentication failed" {
    exit 10
  }
  timeout {
    exit 124
  }
  eof {}
}

set status 0
catch wait result
if {[llength $result] >= 4} {
  set status [lindex $result 3]
}
exit $status
EXPECT_EOF
