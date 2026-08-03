/* OMNICRAFT — job registry and progress rendering. */
(function (global) {
  'use strict';

  var Jobs = {
    map: {},
    watchers: {},

    init: function () {
      Sockets.on('*', function (message) {
        if (!message.job) return;
        Jobs.put(message.job);
      });
    },

    put: function (job) {
      this.map[job.id] = Object.assign(this.map[job.id] || {}, job);
      this.render();
      var list = this.watchers[job.id] || [];
      if (job.status === 'completed' || job.status === 'failed') {
        delete this.watchers[job.id];
        Auth.refreshUser();
      }
      list.forEach(function (fn) { fn(job); });
    },

    watch: function (jobId, onUpdate) {
      (this.watchers[jobId] = this.watchers[jobId] || []).push(onUpdate);
      this.poll(jobId);
    },

    /* Socket is primary; this is the safety net if it drops. */
    poll: function (jobId) {
      var tries = 0;
      var timer = setInterval(async function () {
        tries += 1;
        var current = Jobs.map[jobId];
        if (!Jobs.watchers[jobId] || tries > 400) { clearInterval(timer); return; }
        if (current && (current.status === 'completed' || current.status === 'failed')) {
          clearInterval(timer);
          return;
        }
        if (Sockets.socket && Sockets.socket.readyState === 1 && tries % 6 !== 0) return;
        try { Jobs.put(await API.get('/api/jobs/' + jobId)); }
        catch (e) { /* transient */ }
      }, 2500);
    },

    load: async function () {
      try {
        var data = await API.get('/api/jobs?limit=40');
        data.jobs.forEach(function (j) { Jobs.map[j.id] = j; });
        this.render();
      } catch (e) { /* not fatal */ }
    },

    sorted: function () {
      return Object.values(this.map).sort(function (a, b) {
        var rank = { running: 0, queued: 1, completed: 2, failed: 3, cancelled: 4 };
        var d = (rank[a.status] || 9) - (rank[b.status] || 9);
        if (d !== 0) return d;
        return String(b.created_at || '').localeCompare(String(a.created_at || ''));
      });
    },

    card: function (job) {
      var fillClass = job.status === 'completed' ? ' done' : (job.status === 'failed' ? ' failed' : '');
      var output = job.output_data || {};
      var actions = '';
      if (job.status === 'completed' && output.file_id) {
        actions = '<button class="btn btn--ghost btn--sm" data-download="' + output.file_id +
                  '" data-name="' + UI.escape(output.filename || 'output') + '">Download</button>';
      }
      return '<div class="job" data-job="' + job.id + '">' +
        '<div class="job__head">' +
          '<span class="job__type">' + UI.escape(job.job_type) + '</span>' +
          '<span class="badge badge--' + job.status + '">' + job.status + '</span>' +
          '<span class="job__spacer"></span>' +
          '<span class="job__pct">' + (job.progress || 0) + '%</span>' +
          actions +
        '</div>' +
        '<div class="bar"><div class="bar__fill' + fillClass + '" style="width:' + (job.progress || 0) + '%"></div></div>' +
        '<div class="job__stage">' + UI.escape(job.error_message || job.stage || '') + '</div>' +
      '</div>';
    },

    render: function () {
      var all = this.sorted();
      var full = document.getElementById('jobsPanel');
      if (full) {
        full.innerHTML = all.length
          ? '<div class="card">' + all.map(Jobs.card).join('') + '</div>'
          : UI.empty('No jobs yet', 'Start something from any channel and it will show up here.');
      }
      var recent = document.getElementById('overviewJobs');
      if (recent) {
        recent.innerHTML = all.length
          ? all.slice(0, 5).map(Jobs.card).join('')
          : '<p class="muted small">Nothing has run yet.</p>';
      }
    },

    /* Attaches a compact progress card inside a feature panel. */
    attach: function (container, jobId) {
      var host = document.createElement('div');
      host.className = 'mt';
      container.appendChild(host);
      var paint = function (job) { host.innerHTML = Jobs.card(job); };
      paint(Jobs.map[jobId] || { id: jobId, job_type: 'starting', status: 'queued', progress: 0, stage: 'Queued' });
      Jobs.watch(jobId, function (job) {
        paint(job);
        if (job.status === 'completed') {
          UI.ok('Finished', (job.output_data && job.output_data.filename) || job.job_type);
        } else if (job.status === 'failed') {
          UI.err('Job failed', job.error_message || 'Credits were refunded.');
        }
      });
      return host;
    }
  };

  document.addEventListener('click', function (e) {
    var button = e.target.closest('[data-download]');
    if (!button) return;
    API.download(button.getAttribute('data-download'), button.getAttribute('data-name'))
      .catch(function (error) { UI.fail(error, 'Download failed.'); });
  });

  global.Jobs = Jobs;
})(window);
