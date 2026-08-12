/* Login page — external script, no inline handlers.
 * Loaded by the /login route. Reads data attributes from the form for
 * i18n strings so the server does not need to inject JS literals.
 */
document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('login-form');
  var input = document.getElementById('pw');
  var passkeyBtn = document.getElementById('passkey-login');

  if (!form || !input) return;

  // RBAC bootstrap: check init_status to decide whether to redirect to /setup
  fetch('/api/auth/init_status', { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (s) {
      if (s && s.initialized === false) {
        window.location.href = '/setup';
      }
    })
    .catch(function () { /* fail open — show login form */ });

  var invalidPw = form.getAttribute('data-invalid-pw') || 'Invalid password';
  var connFailed = form.getAttribute('data-conn-failed') || 'Connection failed';

  // Map English error strings returned by the server into the localized
  // strings already injected into the form via data-* attributes. Keeps the
  // client-facing message in the user's UI language even when the /api/auth
  // /login endpoint returns a hard-coded English body (e.g. rbac_routes.py
  // returns {"error":"Invalid credentials"} on 401). Keys we don't recognize
  // fall through and display as-is so the user always sees some signal.
  function _translateAuthError(err) {
    if (!err) return invalidPw;
    var key = String(err).toLowerCase();
    if (key === 'invalid credentials' || key === 'invalid password' || key === 'invalid_pw') return invalidPw;
    if (key === 'connection failed' || key === 'network error' || key === 'conn_failed') return connFailed;
    return err;
  }

  function showErr(msg) {
    var err = document.getElementById('err');
    if (err) { err.textContent = msg; err.style.display = 'block'; }
  }

  function hideErr() {
    var err = document.getElementById('err');
    if (err) { err.style.display = 'none'; }
  }

  // Return the ?next= redirect path if present and safe, otherwise '/'.
  // Guards against open-redirect: rejects protocol-relative (//evil.com),
  // absolute URLs, backslash variants, and control characters.
  function _safeNextPath() {
    try {
      var raw = new URL(window.location.href).searchParams.get('next');
      if (!raw) return '/';
      if (raw.charAt(0) !== '/') return '/';             // must be path-absolute
      if (raw.charAt(1) === '/' || raw.charAt(1) === '\\') return '/'; // reject // and \\
      if (/[\x00-\x1f\x7f\s]/.test(raw)) return '/';  // reject control chars / whitespace
      // #5578: never redirect back to the login page — that self-referential
      // chain is what grows the URL exponentially on repeated expired-auth
      // bounces. Detect the login route even through nested percent-encoding
      // (a nested chain looks like `/session/login%3Fnext%3D...`, where the `?`
      // is encoded so a plain split('?') wouldn't isolate the path). Decode a
      // few levels and check the leading PATH. Only collapse login-route chains
      // — a legitimate non-login path that merely carries its own `next=` query
      // key must still round-trip.
      if (raw.length > 2048) return '/';
      var probe = raw;
      var stabilized = false;
      for (var i = 0; i < 8; i++) {
        var pathOnly = probe.split('?')[0].split('#')[0].split('&')[0].replace(/\/+$/, '');
        if (pathOnly === '/login' || /\/login$/.test(pathOnly)) return '/';
        var decoded;
        try { decoded = decodeURIComponent(probe); } catch (_) { stabilized = true; break; }
        if (decoded === probe) { stabilized = true; break; }
        probe = decoded;
      }
      // If still decoding at the cap (pathologically deep encoding), fail closed.
      if (!stabilized) return '/';
      return raw;
    } catch (_) { return '/'; }
  }

  var AUTH_SCOPE_STORAGE_KEY = 'hermes-webui-auth-user-id';
  var AUTH_ROLE_STORAGE_KEY = 'hermes-webui-auth-role';

  function _authIdentityFromUser(user) {
    if (!user) return '';
    if (user.id) return String(user.id);
    if (user.username) return 'user:' + String(user.username);
    return '';
  }

  function _rememberLoggedInUser(user) {
    var identity = _authIdentityFromUser(user);
    try {
      var previous = localStorage.getItem(AUTH_SCOPE_STORAGE_KEY) || '';
      if (identity && previous && previous !== identity) {
        localStorage.removeItem('hermes-webui-session');
      }
      if (identity) localStorage.setItem(AUTH_SCOPE_STORAGE_KEY, identity);
      if (user && user.role) localStorage.setItem(AUTH_ROLE_STORAGE_KEY, String(user.role));
    } catch (_) {}
  }

  function _installLicenseActivationMachineInfoFallback() {
    var bodyText = '';
    try { bodyText = document.body ? document.body.textContent || '' : ''; } catch (_) {}
    if (bodyText.indexOf('License 激活') === -1 && bodyText.indexOf('License') === -1) return;

    function _licenseText(v) {
      if (v === null || v === undefined || v === '') return '';
      return String(v);
    }

    function _licenseRead(obj, keys) {
      if (!obj || typeof obj !== 'object') return '';
      for (var i = 0; i < keys.length; i += 1) {
        var key = keys[i];
        if (Object.prototype.hasOwnProperty.call(obj, key)) {
          var value = _licenseText(obj[key]);
          if (value) return value;
        }
      }
      return '';
    }

    function _licenseNormalize(payload) {
      var data = payload && typeof payload === 'object'
        ? (payload.license || payload.machine || payload.data || payload.status || payload)
        : {};
      return {
        platformId: _licenseRead(data, ['platform_id', 'platformId', 'platform', 'machine_id', 'machineId', 'fingerprint'])
          || _licenseRead(payload, ['platform_id', 'platformId', 'platform', 'machine_id', 'machineId', 'fingerprint']),
        macAddress: _licenseRead(data, ['mac_address', 'macAddress', 'mac', 'machine_mac', 'machineMac', 'primary_mac'])
          || _licenseRead(payload, ['mac_address', 'macAddress', 'mac', 'machine_mac', 'machineMac', 'primary_mac'])
      };
    }

    function _findLicenseValue(labelText) {
      var wanted = String(labelText || '').replace(/[:：]\s*$/, '');
      var nodes = Array.prototype.slice.call(document.querySelectorAll('div,span,dt,dd,td,th,label,p'));
      for (var i = 0; i < nodes.length; i += 1) {
        var el = nodes[i];
        var text = String(el.textContent || '').trim().replace(/[:：]\s*$/, '');
        if (text !== wanted) continue;
        var parent = el.parentElement;
        if (!parent) continue;
        var children = Array.prototype.slice.call(parent.children || []);
        for (var j = 0; j < children.length; j += 1) {
          var child = children[j];
          if (child !== el && String(child.textContent || '').trim()) return child;
        }
        if (el.nextElementSibling) return el.nextElementSibling;
      }
      return null;
    }

    function _setLicenseValue(label, value) {
      if (!value || value === 'N/A') return false;
      var node = _findLicenseValue(label);
      if (!node) return false;
      node.textContent = String(value);
      return true;
    }

    function _showLicenseMachineInfoError() {
      var card = document.querySelector('form') || document.querySelector('[role="main"]') || document.body;
      if (!card || document.getElementById('license-machine-info-error')) return;
      var note = document.createElement('div');
      note.id = 'license-machine-info-error';
      note.style.cssText = 'margin-top:12px;color:#fca5a5;font-size:13px;line-height:1.5;text-align:center;';
      note.textContent = '未能读取平台 ID / MAC 地址，请确认服务端机器标识接口可用后刷新页面。';
      card.appendChild(note);
    }

    async function _hydrateLicenseMachineInfo() {
      var platformNode = _findLicenseValue('平台 ID');
      var macNode = _findLicenseValue('MAC 地址');
      var platformEmpty = !platformNode || ['N/A', '-', ''].indexOf(String(platformNode.textContent || '').trim()) !== -1;
      var macEmpty = !macNode || ['N/A', '-', ''].indexOf(String(macNode.textContent || '').trim()) !== -1;
      if (!platformEmpty && !macEmpty) return;
      var endpoints = [
        '/api/license/machine',
        '/api/license/status',
        '/api/admin/license/status',
        '/api/license'
      ];
      for (var i = 0; i < endpoints.length; i += 1) {
        try {
          var res = await fetch(endpoints[i], {credentials: 'include'});
          if (!res.ok) continue;
          var data = await res.json();
          var info = _licenseNormalize(data);
          var ok = false;
          ok = _setLicenseValue('平台 ID', info.platformId) || ok;
          ok = _setLicenseValue('MAC 地址', info.macAddress) || ok;
          if (ok) return;
        } catch (_) {}
      }
      _showLicenseMachineInfoError();
    }

    setTimeout(_hydrateLicenseMachineInfo, 0);
  }
  _installLicenseActivationMachineInfoFallback();

  async function doLogin(e) {
    e.preventDefault();
    var pw = input.value;
    var usernameEl = document.getElementById('username');
    var username = usernameEl ? usernameEl.value.trim() : '';
    hideErr();
    try {
      var res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username, password: pw }),
        credentials: 'include',
      });
      var data = {};
      try { data = await res.json(); } catch (_) {}
      if (res.ok && data.user) {
        _rememberLoggedInUser(data.user);
        window.location.href = _safeNextPath();
      } else {
        showErr(_translateAuthError(data.error) || invalidPw);
      }
    } catch (ex) {
      showErr(connFailed);
    }
  }

  form.addEventListener('submit', doLogin);

  function b64uToBytes(s) {
    s = String(s || '').replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var bin = atob(s);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function bytesToB64u(buf) {
    var bytes = new Uint8Array(buf);
    var bin = '';
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  async function doPasskeyLogin() {
    if (!window.PublicKeyCredential || !navigator.credentials) return;
    hideErr();
    try {
      passkeyBtn.disabled = true;
      var optRes = await fetch('/api/auth/passkey/options', { method: 'POST', body: '{}', credentials: 'include' });
      var optData = await optRes.json();
      if (!optRes.ok || !optData.publicKey) throw new Error(optData.error || 'Passkey unavailable');
      var pk = optData.publicKey;
      pk.challenge = b64uToBytes(pk.challenge);
      if (Array.isArray(pk.allowCredentials)) {
        pk.allowCredentials = pk.allowCredentials.map(function (c) { return Object.assign({}, c, { id: b64uToBytes(c.id) }); });
      }
      var cred = await navigator.credentials.get({ publicKey: pk });
      if (!cred) throw new Error('Passkey sign-in cancelled');
      var payload = {
        id: cred.id,
        rawId: bytesToB64u(cred.rawId),
        type: cred.type,
        response: {
          authenticatorData: bytesToB64u(cred.response.authenticatorData),
          clientDataJSON: bytesToB64u(cred.response.clientDataJSON),
          signature: bytesToB64u(cred.response.signature),
          userHandle: cred.response.userHandle ? bytesToB64u(cred.response.userHandle) : null,
        },
      };
      var res = await fetch('/api/auth/passkey/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload), credentials: 'include',
      });
      var data = {};
      try { data = await res.json(); } catch (_) {}
      if (res.ok && data.ok) {
        _rememberLoggedInUser(data.user);
        window.location.href = _safeNextPath();
      }
      else showErr(_translateAuthError(data.error) || invalidPw);
    } catch (ex) {
      showErr(ex && ex.message ? ex.message : connFailed);
    } finally {
      passkeyBtn.disabled = false;
    }
  }

  if (passkeyBtn && window.PublicKeyCredential && navigator.credentials) {
    fetch('/api/auth/status', { credentials: 'include' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s && s.passkeys_enabled) passkeyBtn.style.display = 'block'; })
      .catch(function () {});
    passkeyBtn.addEventListener('click', doPasskeyLogin);
  }

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      doLogin(e);
    }
  });

  // On page load, probe the server so we can distinguish "can't reach server"
  // (Tailscale off, wrong network) from "session expired / need to log in".
  // Uses /health — public for WebUI auth, but deployment access proxies may
  // require same-origin cookies before the request reaches WebUI.
  // If unreachable, retries every 3 s and auto-reloads once the server is back.
  (function checkConnectivity() {
    var retryTimer = null;

    function setFormDisabled(disabled) {
      if (input) input.disabled = disabled;
      var btn = form.querySelector('button');
      if (btn) btn.disabled = disabled;
    }

    function probe() {
      fetch('/health', { method: 'GET', credentials: 'same-origin' })
        .then(function (r) {
          if (r.ok) {
            // Server is reachable — if we were in retry mode, reload so the
            // page reflects the correct auth state (expired session, etc.).
            if (retryTimer !== null) {
              clearTimeout(retryTimer);
              retryTimer = null;
              window.location.reload();
            }
          } else {
            showErr(connFailed + ' (server error ' + r.status + ')');
          }
        })
        .catch(function () {
          showErr('Cannot reach server — check your VPN / Tailscale connection.');
          setFormDisabled(true);
          // Keep retrying so the page auto-recovers once the network is back.
          if (retryTimer === null) {
            retryTimer = setInterval(probe, 3000);
          }
        });
    }

    probe();
  })();
});
