/* OMNICRAFT — sign in, registration and session state. */
(function (global) {
  'use strict';

  var Auth = {
    user: null,
    capabilities: null,

    init: function () {
      var gate = document.getElementById('gate');
      var tabIn = document.getElementById('tabSignIn');
      var tabUp = document.getElementById('tabCreate');
      var formIn = document.getElementById('formSignIn');
      var formUp = document.getElementById('formCreate');

      function show(which) {
        var signIn = which === 'in';
        tabIn.setAttribute('aria-selected', String(signIn));
        tabUp.setAttribute('aria-selected', String(!signIn));
        formIn.classList.toggle('hidden', !signIn);
        formUp.classList.toggle('hidden', signIn);
      }
      tabIn.onclick = function () { show('in'); };
      tabUp.onclick = function () { show('up'); };

      formIn.onsubmit = async function (e) {
        e.preventDefault();
        var button = formIn.querySelector('button[type=submit]');
        UI.busy(button, true, 'Signing in');
        try {
          var body = {
            identifier: document.getElementById('loginId').value.trim(),
            password: document.getElementById('loginPass').value
          };
          var code = document.getElementById('loginTotp').value.trim();
          if (code) body.totp_code = code;
          var session = await API.post('/api/auth/login', body);
          API.save(session);
          await Auth.afterSignIn();
        } catch (error) {
          if (error.status === 428 || (error.detail && error.detail.code === 'totp_required')) {
            document.getElementById('totpField').classList.remove('hidden');
            document.getElementById('loginTotp').focus();
            UI.info('One more step', 'Enter the code from your authenticator app.');
          } else {
            UI.fail(error, 'Sign in failed.');
          }
        } finally {
          UI.busy(button, false);
        }
      };

      formUp.onsubmit = async function (e) {
        e.preventDefault();
        var button = formUp.querySelector('button[type=submit]');
        UI.busy(button, true, 'Creating');
        try {
          var session = await API.post('/api/auth/register', {
            email: document.getElementById('regEmail').value.trim(),
            username: document.getElementById('regUser').value.trim(),
            password: document.getElementById('regPass').value
          });
          API.save(session);
          await Auth.afterSignIn();
          UI.ok('Account created', 'Five starter credits are already on your balance.');
        } catch (error) {
          UI.fail(error, 'Could not create that account.');
        } finally {
          UI.busy(button, false);
        }
      };

      document.getElementById('btnSignOut').onclick = function () { Auth.signOut(); };

      API.onUnauthorized = function () { Auth.signOut(true); };

      if (API.session) {
        Auth.afterSignIn().catch(function () { Auth.signOut(true); });
      } else {
        /* No session: the public landing page stays visible (it is not
           hidden by default). Landing CTAs reveal the gate. */
        gate.hidden = true;
      }
    },

    afterSignIn: async function () {
      Auth.user = await API.get('/api/auth/me');
      Auth.capabilities = await API.get('/api/capabilities').catch(function () { return null; });
      var landing = document.getElementById('landing');
      if (landing) landing.hidden = true;
      document.getElementById('gate').hidden = true;
      document.getElementById('shell').hidden = false;
      Auth.paint();
      global.App.start();
    },

    refreshUser: async function () {
      try {
        Auth.user = await API.get('/api/auth/me');
        Auth.paint();
      } catch (e) { /* keep the current view */ }
    },

    paint: function () {
      if (!Auth.user) return;
      document.getElementById('meterValue').textContent = Auth.user.credits_balance.toLocaleString();
      document.getElementById('tierChip').textContent = Auth.user.tier;

      var ladder = document.getElementById('meterLadder');
      var lit = Math.min(10, Math.ceil(Math.log10(Math.max(1, Auth.user.credits_balance)) * 3.4));
      var low = Auth.user.credits_balance < 10;
      ladder.innerHTML = '';
      for (var i = 0; i < 10; i++) {
        var tick = document.createElement('span');
        tick.className = 'meter__tick' + (i < lit ? (low ? ' low' : ' on') : '');
        tick.style.height = (5 + i * 1.2) + 'px';
        ladder.appendChild(tick);
      }
    },

    signOut: function (silent) {
      var refresh = API.session && API.session.refresh_token;
      if (refresh) {
        API.post('/api/auth/logout', { refresh_token: refresh }).catch(function () {});
      }
      API.clear();
      Auth.user = null;
      if (global.Sockets) Sockets.close();
      document.getElementById('shell').hidden = true;
      var landing = document.getElementById('landing');
      if (landing) { landing.hidden = false; }
      else { document.getElementById('gate').hidden = false; }
      document.getElementById('totpField').classList.add('hidden');
      if (!silent) UI.info('Signed out', 'Your session was closed on this device.');
    },

    isAdmin: function () { return Auth.user && Auth.user.role === 'admin'; }
  };

  global.Auth = Auth;
})(window);
