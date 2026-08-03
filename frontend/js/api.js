/* OMNICRAFT — API client with automatic token refresh. */
(function (global) {
  'use strict';

  var STORE = 'omnicraft.session';

  function resolveBase() {
    var meta = document.querySelector('meta[name="omnicraft-api"]');
    if (meta && meta.content) return meta.content.replace(/\/$/, '');
    var saved = localStorage.getItem('omnicraft.api');
    if (saved) return saved.replace(/\/$/, '');
    var host = location.hostname;
    if (host === 'localhost' || host === '127.0.0.1') return 'http://localhost:8000';
    return location.origin;
  }

  var API = {
    base: resolveBase(),
    session: null,
    onUnauthorized: null,

    load: function () {
      try { this.session = JSON.parse(localStorage.getItem(STORE) || 'null'); }
      catch (e) { this.session = null; }
      return this.session;
    },

    save: function (session) {
      this.session = session;
      localStorage.setItem(STORE, JSON.stringify(session));
    },

    clear: function () {
      this.session = null;
      localStorage.removeItem(STORE);
    },

    setBase: function (url) {
      this.base = url.replace(/\/$/, '');
      localStorage.setItem('omnicraft.api', this.base);
    },

    headers: function (extra) {
      var h = Object.assign({ 'Content-Type': 'application/json' }, extra || {});
      if (this.session && this.session.access_token) {
        h.Authorization = 'Bearer ' + this.session.access_token;
      }
      return h;
    },

    refresh: async function () {
      if (!this.session || !this.session.refresh_token) return false;
      try {
        var res = await fetch(this.base + '/api/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: this.session.refresh_token })
        });
        if (!res.ok) return false;
        this.save(await res.json());
        return true;
      } catch (e) { return false; }
    },

    request: async function (path, options, retried) {
      options = options || {};
      var init = {
        method: options.method || 'GET',
        headers: this.headers(options.headers)
      };
      if (options.body !== undefined) {
        if (options.body instanceof FormData) {
          delete init.headers['Content-Type'];
          init.body = options.body;
        } else {
          init.body = JSON.stringify(options.body);
        }
      }

      var res;
      try {
        res = await fetch(this.base + path, init);
      } catch (e) {
        throw { status: 0, message: 'Can\'t reach the API at ' + this.base + '. Check that the backend is running.' };
      }

      if (res.status === 401 && !retried && this.session) {
        if (await this.refresh()) return this.request(path, options, true);
        this.clear();
        if (this.onUnauthorized) this.onUnauthorized();
        throw { status: 401, message: 'Your session expired. Sign in again.' };
      }

      if (res.status === 204) return null;

      var payload = null;
      var type = res.headers.get('content-type') || '';
      if (type.indexOf('application/json') !== -1) {
        payload = await res.json().catch(function () { return null; });
      } else {
        payload = await res.text().catch(function () { return ''; });
      }

      if (!res.ok) {
        var detail = payload && payload.detail !== undefined ? payload.detail : payload;
        var message = 'Request failed (' + res.status + ')';
        var code = null;
        if (typeof detail === 'string') message = detail;
        else if (detail && typeof detail === 'object') {
          message = detail.message || message;
          code = detail.code || null;
        }
        throw { status: res.status, message: message, code: code, detail: detail };
      }

      return payload;
    },

    get: function (p) { return this.request(p); },
    post: function (p, body) { return this.request(p, { method: 'POST', body: body }); },
    del: function (p) { return this.request(p, { method: 'DELETE' }); },

    upload: function (file, onProgress) {
      var self = this;
      return new Promise(function (resolve, reject) {
        var form = new FormData();
        form.append('file', file);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', self.base + '/api/storage/upload');
        if (self.session) xhr.setRequestHeader('Authorization', 'Bearer ' + self.session.access_token);
        xhr.upload.onprogress = function (e) {
          if (e.lengthComputable && onProgress) onProgress(Math.round(e.loaded / e.total * 100));
        };
        xhr.onload = function () {
          var body = null;
          try { body = JSON.parse(xhr.responseText); } catch (e) { /* ignore */ }
          if (xhr.status >= 200 && xhr.status < 300) resolve(body);
          else {
            var d = body && body.detail;
            reject({ status: xhr.status, message: (typeof d === 'string' ? d : (d && d.message)) || 'Upload failed.' });
          }
        };
        xhr.onerror = function () { reject({ status: 0, message: 'The upload connection dropped.' }); };
        xhr.send(form);
      });
    },

    fileUrl: function (fileId) {
      return this.base + '/api/storage/files/' + fileId + '/download';
    },

    fetchBlobUrl: async function (fileId) {
      var res = await fetch(this.fileUrl(fileId), { headers: this.headers() });
      if (!res.ok) throw { status: res.status, message: 'Could not load that file.' };
      return URL.createObjectURL(await res.blob());
    },

    download: async function (fileId, filename) {
      var url = await this.fetchBlobUrl(fileId);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename || 'omnicraft-file';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    }
  };

  API.load();
  global.API = API;
})(window);
