/* Setup page — first-time admin creation.
 * Loaded by /setup when users.json is empty.
 */
document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('setup-form');
  var errorEl = document.getElementById('setup-error');
  var submitBtn = document.getElementById('setup-submit');
  var passwordEl = document.getElementById('setup-password');
  var strengthBar = document.getElementById('password-strength');
  var strengthLabel = document.getElementById('password-strength-label');
  if (!form) return;

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.hidden = false;
  }

  function passwordStrength(password) {
    var score = 0;
    if (password.length >= 8) score++;
    if (password.length >= 12) score++;
    if (/[A-Za-z]/.test(password) && /\d/.test(password)) score++;
    if (/[^A-Za-z0-9]/.test(password)) score++;
    return score;
  }

  function updateStrength() {
    var score = passwordStrength(passwordEl.value);
    var levels = ['', 'weak', 'fair', 'good', 'strong'];
    var labels = ['', '较弱', '一般', '良好', '较强'];
    strengthBar.className = 'login-strength-bar' + (score ? ' ' + levels[score] : '');
    strengthLabel.textContent = score ? labels[score] : '';
  }

  function clientValidate(username, password, confirm) {
    if (!/^[A-Za-z0-9_.\-]{3,32}$/.test(username)) {
      return '用户名必须是 3-32 个字母/数字/_-. 字符';
    }
    if (password.length < 8) {
      return '密码至少 8 个字符';
    }
    if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      return '密码必须同时包含字母和数字';
    }
    if (password !== confirm) {
      return '两次输入的密码不一致';
    }
    return null;
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    errorEl.hidden = true;
    var username = document.getElementById('setup-username').value.trim();
    var password = document.getElementById('setup-password').value;
    var confirm = document.getElementById('setup-password-confirm').value;

    var clientErr = clientValidate(username, password, confirm);
    if (clientErr) { showError(clientErr); return; }

    submitBtn.disabled = true;
    try {
      var resp = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ username: username, password: password }),
      });
      if (resp.ok) {
        window.location.href = '/login';
        return;
      }
      var data = {};
      try { data = await resp.json(); } catch (_) {}
      if (resp.status === 403) {
        showError('系统已经初始化过, 请直接登录');
      } else if (resp.status === 400) {
        showError(data.error || '输入有误');
      } else {
        showError(data.error || '创建失败 (HTTP ' + resp.status + ')');
      }
    } catch (err) {
      showError('网络连接失败');
    } finally {
      submitBtn.disabled = false;
    }
  });

  passwordEl.addEventListener('input', updateStrength);
  Array.prototype.forEach.call(document.querySelectorAll('.login-password-toggle'), function (button) {
    button.addEventListener('click', function () {
      var target = document.getElementById(button.getAttribute('data-target'));
      var visible = target.type === 'password';
      target.type = visible ? 'text' : 'password';
      button.textContent = visible ? '隐藏' : '显示';
      button.setAttribute('aria-label', visible ? '隐藏密码' : '显示密码');
    });
  });
});
