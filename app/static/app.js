/* Utilidades compartidas: CSRF, llamadas a la API, avisos y selectores de contexto. */
(function () {
  'use strict';

  var meta = document.querySelector('meta[name="csrf-token"]');
  var CSRF = meta ? meta.content : '';

  function toast(mensaje, tipo) {
    var el = document.getElementById('toast');
    if (!el) return;
    el.textContent = mensaje;
    el.className = 'fixed bottom-6 right-6 z-[60] max-w-sm rounded-xl px-4 py-3 shadow-lg font-label-md text-label-md ' +
      (tipo === 'error' ? 'bg-error text-on-error' : 'bg-inverse-surface text-inverse-on-surface');
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.classList.add('hidden'); }, tipo === 'error' ? 7000 : 3500);
  }

  function api(metodo, url, cuerpo) {
    var opciones = {
      method: metodo,
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json', 'X-CSRF-Token': CSRF }
    };
    if (cuerpo !== undefined) {
      opciones.headers['Content-Type'] = 'application/json';
      opciones.body = JSON.stringify(cuerpo);
    }
    return fetch(url, opciones).then(function (resp) {
      if (resp.status === 401) {
        window.location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
        return Promise.reject(new Error('Sesión expirada'));
      }
      return resp.json().catch(function () { return {}; }).then(function (datos) {
        if (!resp.ok) {
          var e = new Error(datos.error || 'Error ' + resp.status);
          e.status = resp.status; e.datos = datos;
          throw e;
        }
        return datos;
      });
    });
  }

  // Selectores de año lectivo y período de la barra superior
  document.querySelectorAll('select[data-contexto]').forEach(function (sel) {
    sel.addEventListener('change', function () {
      var q = new URLSearchParams();
      q.set(sel.dataset.contexto, sel.value);
      q.set('next', location.pathname);
      window.location.href = '/contexto?' + q.toString();
    });
  });

  window.App = { api: api, toast: toast, csrf: CSRF };
})();
