/* OMNICRAFT — shared UI helpers: toasts, formatting, small builders. */
(function (global) {
  'use strict';

  var UI = {
    toast: function (title, text, kind, ttl) {
      var host = document.getElementById('toasts');
      if (!host) return;
      var el = document.createElement('div');
      el.className = 'toast toast--' + (kind || 'info');
      el.innerHTML =
        '<div class="toast__body"><div class="toast__title"></div>' +
        (text ? '<div class="toast__text"></div>' : '') + '</div>' +
        '<button class="toast__close" aria-label="Dismiss">&times;</button>';
      el.querySelector('.toast__title').textContent = title;
      if (text) el.querySelector('.toast__text').textContent = text;
      el.querySelector('.toast__close').onclick = function () { el.remove(); };
      host.appendChild(el);
      setTimeout(function () { el.remove(); }, ttl || (kind === 'error' ? 9000 : 5200));
    },

    ok: function (t, m) { UI.toast(t, m, 'ok'); },
    err: function (t, m) { UI.toast(t, m, 'error'); },
    warn: function (t, m) { UI.toast(t, m, 'warn'); },
    info: function (t, m) { UI.toast(t, m, 'info'); },

    fail: function (error, fallback) {
      var msg = (error && error.message) || fallback || 'Something went wrong.';
      if (error && error.code === 'insufficient_credits') {
        UI.toast('Not enough credits', msg, 'warn');
      } else if (error && error.code === 'provider_not_configured') {
        UI.toast('Module not connected', msg, 'warn', 10000);
      } else {
        UI.toast('That didn\'t work', msg, 'error');
      }
    },

    bytes: function (n) {
      if (!n) return '0 B';
      var units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
      var i = Math.floor(Math.log(n) / Math.log(1024));
      i = Math.min(i, units.length - 1);
      return (n / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
    },

    duration: function (seconds) {
      if (!seconds && seconds !== 0) return '—';
      var s = Math.round(seconds);
      var h = Math.floor(s / 3600);
      var m = Math.floor((s % 3600) / 60);
      var r = s % 60;
      var pad = function (v) { return String(v).padStart(2, '0'); };
      return h ? h + ':' + pad(m) + ':' + pad(r) : m + ':' + pad(r);
    },

    date: function (value) {
      if (!value) return '—';
      var d = new Date(value);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' +
             d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    },

    money: function (n) {
      return '$' + Number(n).toFixed(2).replace(/\.00$/, '');
    },

    escape: function (str) {
      var d = document.createElement('div');
      d.textContent = str == null ? '' : String(str);
      return d.innerHTML;
    },

    el: function (tag, className, html) {
      var node = document.createElement(tag);
      if (className) node.className = className;
      if (html !== undefined) node.innerHTML = html;
      return node;
    },

    empty: function (title, hint) {
      return '<div class="empty"><div class="empty__title">' + UI.escape(title) +
             '</div><div class="empty__hint">' + UI.escape(hint || '') + '</div></div>';
    },

    notice: function (text, kind) {
      return '<div class="notice notice--' + (kind || 'warn') + '">' +
             '<span class="notice__mark">!</span><div>' + UI.escape(text) + '</div></div>';
    },

    busy: function (button, on, label) {
      if (!button) return;
      if (on) {
        button.dataset.label = button.innerHTML;
        button.disabled = true;
        button.innerHTML = '<span class="spinner"></span>' + (label || 'Working');
      } else {
        button.disabled = false;
        if (button.dataset.label) button.innerHTML = button.dataset.label;
      }
    },

    /* Renders a file picker <select> from the library, filtered by kind. */
    fileOptions: function (files, kinds) {
      var list = kinds ? files.filter(function (f) { return kinds.indexOf(f.kind) !== -1; }) : files;
      if (!list.length) return '<option value="">Nothing in your library yet</option>';
      return '<option value="">Choose a file…</option>' + list.map(function (f) {
        return '<option value="' + f.id + '">' + UI.escape(f.filename) +
               ' · ' + UI.bytes(f.file_size) + '</option>';
      }).join('');
    },

    dropzone: function (container, onFiles) {
      container.addEventListener('dragover', function (e) {
        e.preventDefault();
        container.classList.add('over');
      });
      container.addEventListener('dragleave', function () { container.classList.remove('over'); });
      container.addEventListener('drop', function (e) {
        e.preventDefault();
        container.classList.remove('over');
        if (e.dataTransfer.files.length) onFiles(Array.from(e.dataTransfer.files));
      });
    }
  };

  global.UI = UI;
})(window);
