/*
  Nuova Norma — favicon con segnale di novità
  Nessuna dipendenza, nessuna richiesta di rete: la favicon è un SVG generato qui.

  Uso:
    NNFavicon.init();              // all'avvio: disegna il delta (rinforzato per le misure piccole)
    NNFavicon.mark();              // una norma seguita è cambiata: aggiunge il puntino
    NNFavicon.mark(3);             // con un numero da 1 a 9 lo scrive nel puntino
    NNFavicon.clear();             // l'utente ha visto le novità: torna al delta semplice

  Opzioni di init (tutte facoltative):
    NNFavicon.init({
      clearOnFocus: true,          // il puntino sparisce da solo quando la scheda torna in primo piano
      color: '#1a1d1c',            // colore del delta in tema chiaro
      colorDark: '#e9edee',        // colore del delta in tema scuro (segue prefers-color-scheme)
      dot: '#1f6f5c',              // colore del puntino
      bg: ''                       // se c'e: icona di prodotto, delta bianco sul quadrato di questo colore
    });

  Il delta nella favicon ha un contorno aggiunto dello stesso colore: a 16 px il lato
  sottile del logo altrimenti scompare. È la "versione rinforzata" per le misure piccole.
*/
(function (global) {
  'use strict';

  var PATH = 'M121.85,0L0,248.78h243.7L121.85,0ZM121.85,37.81l64.88,196.29H25.71L121.85,37.81Z';
  var opts = { clearOnFocus: true, color: '#1a1d1c', colorDark: '#e9edee', dot: '#1f6f5c', bg: '' };
  var pending = 0;
  var link = null;
  var mql = null;

  function isDark() {
    return !!(mql && mql.matches);
  }

  function svg(withDot, count) {
    var ink = isDark() ? opts.colorDark : opts.color;
    var s;
    if (opts.bg) {
      // icona di prodotto (tavola Logo): il solo delta, bianco, sul quadrato nel colore del prodotto
      s = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 312 312">';
      s += '<rect x="0" y="0" width="312" height="312" rx="72" fill="' + opts.bg + '"/>';
      s += '<g transform="translate(64 60) scale(.756)"><path d="' + PATH + '" fill="#ffffff" fill-rule="evenodd" stroke="#ffffff" stroke-width="22" stroke-linejoin="round"/></g>';
      if (withDot) s += '<circle cx="262" cy="50" r="50" fill="' + opts.dot + '" stroke="#ffffff" stroke-width="14"/>';
      return 'data:image/svg+xml,' + encodeURIComponent(s + '</svg>');
    }
    // viewBox allargato a destra e in alto per lasciare spazio al puntino
    s = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-24 -40 312 312">';
    s += '<path d="' + PATH + '" fill="' + ink + '" fill-rule="evenodd" stroke="' + ink + '" stroke-width="18" stroke-linejoin="round"/>';
    if (withDot) {
      s += '<circle cx="226" cy="22" r="58" fill="' + opts.dot + '"/>';
      if (count >= 1 && count <= 9) {
        s += '<text x="226" y="22" fill="#ffffff" font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif" font-size="88" font-weight="700" text-anchor="middle" dominant-baseline="central">' + count + '</text>';
      }
    }
    s += '</svg>';
    return 'data:image/svg+xml,' + encodeURIComponent(s);
  }

  function ensureLink() {
    if (link && link.isConnected) return link;
    link = document.querySelector('link[rel~="icon"]');
    if (!link) {
      link = document.createElement('link');
      link.rel = 'icon';
      document.head.appendChild(link);
    }
    link.type = 'image/svg+xml';
    return link;
  }

  function render() {
    ensureLink().href = svg(pending > 0, pending);
  }

  var api = {
    init: function (o) {
      if (o) for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) opts[k] = o[k];
      if (global.matchMedia) {
        mql = global.matchMedia('(prefers-color-scheme: dark)');
        var onScheme = function () { render(); };
        if (mql.addEventListener) mql.addEventListener('change', onScheme); else if (mql.addListener) mql.addListener(onScheme);
      }
      if (opts.clearOnFocus) {
        document.addEventListener('visibilitychange', function () {
          if (document.visibilityState === 'visible' && pending > 0) api.clear();
        });
      }
      render();
      return api;
    },
    mark: function (count) {
      pending = (typeof count === 'number' && count > 0) ? Math.min(9, Math.floor(count)) : (pending > 0 ? pending : 1);
      render();
      return api;
    },
    clear: function () {
      pending = 0;
      render();
      return api;
    },
    pending: function () { return pending; }
  };

  global.NNFavicon = api;
})(window);
