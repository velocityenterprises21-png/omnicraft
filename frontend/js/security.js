/* Channel 09 — account security. */
(function (global) {
  'use strict';

  var Security = {
    mount: function (host) {
      var user = Auth.user || {};
      host.innerHTML =
        '<div class="grid cols-3 mb">' +
          '<div class="stat"><div class="stat__label">Account</div><div class="stat__value" style="font-size:16px">' +
            UI.escape(user.username || '') + '</div></div>' +
          '<div class="stat"><div class="stat__label">Role</div><div class="stat__value" style="font-size:16px">' +
            UI.escape(user.role || 'user') + '</div></div>' +
          '<div class="stat"><div class="stat__label">Member since</div><div class="stat__value" style="font-size:16px">' +
            UI.date(user.created_at) + '</div></div>' +
        '</div>' +
        '<div class="card">' +
          '<h2 class="card__title">Two-factor authentication</h2>' +
          '<p class="card__hint">' + (user.twofa_enabled
            ? 'Two-factor is on. You\'ll be asked for a code every time you sign in.'
            : 'Add a second step at sign in using any authenticator app.') + '</p>' +
          '<div id="twofaBody"></div>' +
        '</div>' +
        '<div class="card">' +
          '<h2 class="card__title">API access</h2>' +
          '<p class="card__hint">Business tier and above. Send the key as an X-API-Key header.</p>' +
          '<div class="btn-row">' +
            '<button class="btn btn--ghost" id="secApiKey">Generate a new key</button>' +
            '<span class="muted small">Generating a new key immediately retires the old one.</span>' +
          '</div>' +
          '<div id="secApiOut"></div>' +
        '</div>' +
        '<div class="card">' +
          '<h2 class="card__title">Privacy</h2>' +
          '<p class="card__hint">What this platform does and does not do with your data.</p>' +
          '<div class="source"><div class="source__title">No advertising, no trackers</div>' +
            '<div class="small muted">No third-party scripts run in this interface. Every asset is served from your own origin.</div></div>' +
          '<div class="source"><div class="source__title">Temporary files clear themselves</div>' +
            '<div class="small muted">Intermediate renders are swept on a schedule. Anything you keep stays in your library until you delete it.</div></div>' +
          '<div class="source"><div class="source__title">Sessions rotate</div>' +
            '<div class="small muted">Refresh tokens are single use. Signing out revokes the token on this device.</div></div>' +
        '</div>';

      Security.paintTwofa();
      document.getElementById('secApiKey').onclick = Security.rotateKey;
    },

    paintTwofa: function () {
      var body = document.getElementById('twofaBody');
      if (!body) return;
      if (Auth.user && Auth.user.twofa_enabled) {
        body.innerHTML =
          '<div class="notice notice--ok"><span class="notice__mark">✓</span><div>Two-factor is active on this account.</div></div>' +
          '<div class="field" style="max-width:240px">' +
            '<label class="field__label" for="twofaOff">Current code</label>' +
            '<input class="input mono" id="twofaOff" inputmode="numeric" maxlength="6" placeholder="000000">' +
          '</div>' +
          '<button class="btn btn--danger" id="twofaDisable">Turn two-factor off</button>';
        document.getElementById('twofaDisable').onclick = Security.disable;
      } else {
        body.innerHTML = '<button class="btn" id="twofaSetup">Set up two-factor</button>';
        document.getElementById('twofaSetup').onclick = Security.setup;
      }
    },

    setup: async function () {
      var button = document.getElementById('twofaSetup');
      UI.busy(button, true, 'Preparing');
      try {
        var data = await API.post('/api/auth/2fa/setup', {});
        document.getElementById('twofaBody').innerHTML =
          '<p class="small mb">Add this secret to your authenticator app, then confirm with the code it shows.</p>' +
          '<div class="output mono mb">' + UI.escape(data.secret) + '</div>' +
          '<p class="small muted mb">Or paste this URI into the app:</p>' +
          '<div class="output mono mb" style="font-size:11px">' + UI.escape(data.otpauth_uri) + '</div>' +
          '<div class="notice notice--warn"><span class="notice__mark">!</span><div>' +
            'Save these recovery codes somewhere safe. Each one works once if you lose your device.</div></div>' +
          '<div class="output mono mb">' + data.recovery_codes.map(UI.escape).join('\n') + '</div>' +
          '<div class="field" style="max-width:240px">' +
            '<label class="field__label" for="twofaCode">Code from your app</label>' +
            '<input class="input mono" id="twofaCode" inputmode="numeric" maxlength="6" placeholder="000000">' +
          '</div>' +
          '<button class="btn" id="twofaConfirm">Turn two-factor on</button>';
        document.getElementById('twofaConfirm').onclick = Security.enable;
      } catch (error) {
        UI.fail(error, 'Could not start two-factor setup.');
      } finally {
        UI.busy(button, false);
      }
    },

    enable: async function () {
      var code = document.getElementById('twofaCode').value.trim();
      if (code.length !== 6) { UI.warn('Six digits', 'Enter the full code your app is showing.'); return; }
      try {
        await API.post('/api/auth/2fa/enable', { code: code });
        await Auth.refreshUser();
        Security.paintTwofa();
        UI.ok('Two-factor on', 'You\'ll be asked for a code at every sign in.');
      } catch (error) {
        UI.fail(error, 'That code did not match.');
      }
    },

    disable: async function () {
      var code = document.getElementById('twofaOff').value.trim();
      if (code.length !== 6) { UI.warn('Six digits', 'Enter the current code to confirm.'); return; }
      try {
        await API.post('/api/auth/2fa/disable', { code: code });
        await Auth.refreshUser();
        Security.paintTwofa();
        UI.info('Two-factor off', 'Your account now signs in with a password only.');
      } catch (error) {
        UI.fail(error, 'That code did not match.');
      }
    },

    rotateKey: async function () {
      var button = document.getElementById('secApiKey');
      UI.busy(button, true, 'Generating');
      try {
        var data = await API.post('/api/auth/api-key', {});
        document.getElementById('secApiOut').innerHTML =
          '<div class="notice notice--warn mt"><span class="notice__mark">!</span><div>' +
          'Copy this now. It won\'t be shown again.</div></div>' +
          '<div class="output mono">' + UI.escape(data.api_key) + '</div>';
      } catch (error) {
        UI.fail(error, 'Could not generate a key.');
      } finally {
        UI.busy(button, false);
      }
    }
  };

  global.Security = Security;
})(window);
