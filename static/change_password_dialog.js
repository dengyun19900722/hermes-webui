// ── Self-service "change password" dialog (RBAC plan §7) ────────────────────
// Wired into the profile dropdown rendered by static/panels.js
// (renderProfileDropdown emits an item with data-action="change-password").
// The dialog POSTs to /api/auth/change-password which is implemented in
// api/rbac_routes.py::handle_auth_change_password. The backend returns
// i18n-key error strings ("password_old_wrong", "password_too_short",
// "password_needs_classes", "missing_field", "auth_required") that map
// directly to keys already present in static/i18n.js (Task 6 added them
// under "RBAC: 用户自助修改密码").
//
// Relies on globals from earlier-loaded scripts:
//   - esc(), t(), showToast()  from static/ui.js
//   - api()                    from static/workspace.js
//   - closeProfileDropdown()   from static/panels.js
//
// Loaded via <script src="change_password_dialog.js" defer> in static/index.html
// AFTER users_panel.js (which itself is loaded after ui.js + panels.js).

(function () {
  'use strict';

  // ── Module state ────────────────────────────────────────────────────────
  let _modal = null; // the active .change-password-modal-overlay node, or null

  // ── Helpers ─────────────────────────────────────────────────────────────

  // Close any open instance. Idempotent.
  function closeChangePasswordDialog() {
    if (_modal && _modal.parentNode) _modal.parentNode.removeChild(_modal);
    _modal = null;
  }

  // Client-side complexity check mirrors _validate_password_complexity in
  // api/rbac_routes.py. Duplicated here so the user gets instant feedback
  // before the network round-trip; the backend is still the source of truth.
  function _validateComplexity(newPw) {
    if (!newPw || newPw.length < 8) return 'password_too_short';
    // Require at least one letter AND at least one digit (no symbolic
    // shortcut — same as the backend).
    if (!/[A-Za-z]/.test(newPw) || !/\d/.test(newPw)) return 'password_needs_classes';
    return null;
  }

  function _showError(errEl, msgKey) {
    if (!errEl) return;
    if (!msgKey) {
      errEl.textContent = '';
      errEl.style.display = 'none';
      return;
    }
    // Server errors are sent as raw i18n keys (e.g. "password_old_wrong")
    // OR as already-translated English messages depending on the route.
    // Run through t() so translated keys render; if t() returns the same
    // string, the input was already a user-facing message and is fine to
    // display as-is.
    const translated = t(msgKey);
    errEl.textContent = translated || msgKey;
    errEl.style.display = '';
  }

  function _setBusy(card, busy) {
    const submit = card.querySelector('[data-action="submit"]');
    const cancel = card.querySelector('[data-action="cancel"]');
    if (submit) {
      submit.disabled = !!busy;
      submit.classList.toggle('is-busy', !!busy);
    }
    if (cancel) cancel.disabled = !!busy;
    const inputs = card.querySelectorAll('input');
    inputs.forEach((i) => { i.readOnly = !!busy; });
  }

  // ── Build + open ────────────────────────────────────────────────────────
  function openChangePasswordDialog() {
    // Only one instance at a time.
    closeChangePasswordDialog();
    // Close the profile dropdown if it happens to be open (safety — the
    // calling site already closes it, but if this function is invoked
    // from somewhere else, we still want a clean backdrop).
    try { if (typeof closeProfileDropdown === 'function') closeProfileDropdown(); } catch (_) {}

    const overlay = document.createElement('div');
    overlay.className = 'change-password-modal-overlay';

    const card = document.createElement('div');
    card.className = 'change-password-modal';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'true');
    card.setAttribute('aria-labelledby', 'cpDialogTitle');
    // Build the inner form via template strings (rather than DOM APIs) so
    // it stays close to the spec and is easy to translate. esc() guards
    // against any future interpolation of untrusted text.
    card.innerHTML = ''
      + '<h3 id="cpDialogTitle">' + esc(t('change_password_title')) + '</h3>'
      + '<div class="form-row">'
      +   '<label for="cpOldPassword">' + esc(t('change_password_old')) + '</label>'
      +   '<input id="cpOldPassword" type="password" autocomplete="current-password" spellcheck="false" />'
      + '</div>'
      + '<div class="form-row">'
      +   '<label for="cpNewPassword">' + esc(t('change_password_new')) + '</label>'
      +   '<input id="cpNewPassword" type="password" autocomplete="new-password" spellcheck="false" />'
      + '</div>'
      + '<div class="form-row">'
      +   '<label for="cpConfirmPassword">' + esc(t('change_password_confirm')) + '</label>'
      +   '<input id="cpConfirmPassword" type="password" autocomplete="new-password" spellcheck="false" />'
      + '</div>'
      + '<div class="error-banner" id="cpErrorBanner" style="display:none" role="alert" aria-live="polite"></div>'
      + '<div class="actions">'
      +   '<button type="button" class="btn-ghost" data-action="cancel">' + esc(t('change_password_cancel')) + '</button>'
      +   '<button type="button" class="btn-primary" data-action="submit">' + esc(t('change_password_submit')) + '</button>'
      + '</div>';
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    _modal = overlay;

    const oldInput = card.querySelector('#cpOldPassword');
    const newInput = card.querySelector('#cpNewPassword');
    const confirmInput = card.querySelector('#cpConfirmPassword');
    const errEl = card.querySelector('#cpErrorBanner');

    // Focus the first field on the next tick so the autofocus is observable.
    setTimeout(() => { try { oldInput.focus(); } catch (_) {} }, 0);

    // ── Action button clicks (cancel / submit) ────────────────────────────
    card.addEventListener('click', async (ev) => {
      const action = ev.target.getAttribute && ev.target.getAttribute('data-action');
      if (!action) return;
      if (action === 'cancel') {
        ev.preventDefault();
        closeChangePasswordDialog();
        return;
      }
      if (action === 'submit') {
        ev.preventDefault();
        await _submit(card, oldInput.value, newInput.value, confirmInput.value, errEl);
      }
    });

    // ── Enter submits from any field; Escape closes ──────────────────────
    [oldInput, newInput, confirmInput].forEach((inp) => {
      inp.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') {
          ev.preventDefault();
          card.querySelector('[data-action="submit"]').click();
        } else if (ev.key === 'Escape') {
          ev.preventDefault();
          closeChangePasswordDialog();
        }
      });
    });

    // ── Click on dimmed overlay (outside the card) closes ────────────────
    overlay.addEventListener('click', (ev) => {
      if (ev.target === overlay) closeChangePasswordDialog();
    });
  }

  // ── Submit pipeline ─────────────────────────────────────────────────────
  async function _submit(card, oldPw, newPw, confirmPw, errEl) {
    _showError(errEl, '');

    // Empty old/new → use existing i18n keys (no "missing_field" key in
    // i18n.js). Treat an empty old password as "wrong" (we can't tell the
    // difference from a user perspective anyway — they need to type it).
    if (!oldPw) {
      _showError(errEl, 'password_old_wrong');
      return;
    }
    if (!newPw) {
      _showError(errEl, 'password_too_short');
      return;
    }

    const complexityErr = _validateComplexity(newPw);
    if (complexityErr) {
      _showError(errEl, complexityErr);
      return;
    }

    if (newPw !== confirmPw) {
      _showError(errEl, 'password_mismatch');
      return;
    }

    _setBusy(card, true);
    try {
      // api() throws an Error on non-2xx with err.message = the parsed
      // `error` field from the response JSON (see api/workspace.js::api).
      // Backend already uses i18n keys for that field, so t() will translate.
      await api('/api/auth/change-password', {
        method: 'POST',
        body: { old_password: oldPw, new_password: newPw },
      });
      // Success: close + toast. The backend invalidated other sessions
      // (this one is kept via the keep_token cookie), so the user is
      // still logged in.
      closeChangePasswordDialog();
      if (typeof showToast === 'function') showToast(t('password_changed_ok'));
    } catch (e) {
      // Surface the server's i18n key directly. The backend returns short
      // i18n keys (password_old_wrong, password_too_short, etc.) as the
      // `error` field in the response body; api() extracts it into
      // e.message. If the error is a network/timeout error with no
      // usable body, fall back to its .message string verbatim.
      const msg = e && e.message ? String(e.message) : '';
      _showError(errEl, msg || (t('sign_out_failed') || 'Operation failed'));
    } finally {
      _setBusy(card, false);
    }
  }

  // ── Global click delegation ─────────────────────────────────────────────
  // Wires the menu item rendered by renderProfileDropdown
  // (data-action="change-password") so users can click the dropdown entry
  // even though its onclick handler also calls openChangePasswordDialog.
  // We use capture-phase + stopPropagation to win the race against the
  // generic dropdown close listener (#profileChipWrap) and prevent the
  // menu item click from being swallowed before the modal opens.
  if (typeof document !== 'undefined' && !window._changePasswordListenerInstalled) {
    document.addEventListener('click', (e) => {
      try {
        const cp = e.target && e.target.closest && e.target.closest('[data-action="change-password"]');
        if (cp) {
          e.preventDefault();
          e.stopPropagation();
          openChangePasswordDialog();
          return;
        }
        const so = e.target && e.target.closest && e.target.closest('[data-action="sign-out-from-dropdown"]');
        if (so) {
          e.preventDefault();
          e.stopPropagation();
          try { if (typeof closeProfileDropdown === 'function') closeProfileDropdown(); } catch (_) {}
          if (typeof signOut === 'function') signOut();
          return;
        }
      } catch (_) { /* swallow — never let a menu click crash the UI */ }
    }, true);
    window._changePasswordListenerInstalled = true;
  }

  // ── Expose the public entry point ───────────────────────────────────────
  // The panels.js menu item's onclick also calls openChangePasswordDialog
  // directly, but the document-level delegation is the primary path so the
  // modal opens even if the menu item was rendered without an onclick hook.
  window.openChangePasswordDialog = openChangePasswordDialog;
  window.closeChangePasswordDialog = closeChangePasswordDialog;
})();
