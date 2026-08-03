/* OMNICRAFT — live job feed over WebSocket, with backoff and heartbeat. */
(function (global) {
  'use strict';

  var Sockets = {
    socket: null,
    heartbeat: null,
    attempts: 0,
    closing: false,
    handlers: {},

    on: function (type, fn) {
      (this.handlers[type] = this.handlers[type] || []).push(fn);
    },

    emit: function (type, payload) {
      (this.handlers[type] || []).forEach(function (fn) {
        try { fn(payload); } catch (e) { console.error(e); }
      });
    },

    connect: function () {
      if (!API.session || !API.session.access_token) return;
      this.closing = false;

      var url = API.base.replace(/^http/, 'ws') + '/ws?token=' +
                encodeURIComponent(API.session.access_token);
      var self = this;

      try { this.socket = new WebSocket(url); }
      catch (e) { this.retry(); return; }

      this.socket.onopen = function () {
        self.attempts = 0;
        self.heartbeat = setInterval(function () {
          if (self.socket && self.socket.readyState === 1) self.socket.send('ping');
        }, 25000);
      };

      this.socket.onmessage = function (event) {
        var message;
        try { message = JSON.parse(event.data); } catch (e) { return; }
        if (message.type === 'pong' || message.type === 'connected') return;
        self.emit(message.type, message);
        self.emit('*', message);
      };

      this.socket.onclose = function () {
        clearInterval(self.heartbeat);
        if (!self.closing) self.retry();
      };

      this.socket.onerror = function () { /* onclose handles recovery */ };
    },

    retry: function () {
      var self = this;
      this.attempts += 1;
      if (this.attempts > 8) {
        UI.warn('Live updates paused', 'Reload the page to reconnect the job feed.');
        return;
      }
      var wait = Math.min(30000, 1000 * Math.pow(1.8, this.attempts));
      setTimeout(function () { self.connect(); }, wait);
    },

    close: function () {
      this.closing = true;
      clearInterval(this.heartbeat);
      if (this.socket) { this.socket.close(); this.socket = null; }
    }
  };

  global.Sockets = Sockets;
})(window);
