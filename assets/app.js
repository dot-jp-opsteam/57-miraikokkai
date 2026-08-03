/* 未来国会2026 テキストブック — フロントエンド
   依存ライブラリなし。 */
(function () {
  'use strict';

  var doc = document;
  var root = doc.documentElement;
  var $ = function (sel, ctx) { return (ctx || doc).querySelector(sel); };
  var $$ = function (sel, ctx) {
    return Array.prototype.slice.call((ctx || doc).querySelectorAll(sel));
  };

  function store(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
  }

  /* ------------------------------------------------------------------ */
  /* テーマ切り替え                                                      */
  /* ------------------------------------------------------------------ */
  var themeBtn = $('#theme-btn');
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      var current = root.dataset.theme || (prefersDark ? 'dark' : 'light');
      var next = current === 'dark' ? 'light' : 'dark';
      root.dataset.theme = next;
      try { localStorage.setItem('mk-theme', next); } catch (e) {}
    });
  }

  /* ------------------------------------------------------------------ */
  /* モバイル用サイドバー                                                */
  /* ------------------------------------------------------------------ */
  var sidebar = $('#sidebar');
  var menuBtn = $('#menu-btn');
  var scrim = $('#scrim');

  function setDrawer(open) {
    if (!sidebar) return;
    sidebar.classList.toggle('is-open', open);
    if (scrim) scrim.hidden = !open;
    if (menuBtn) menuBtn.setAttribute('aria-expanded', String(open));
    doc.body.style.overflow = open ? 'hidden' : '';
  }
  if (menuBtn) {
    menuBtn.addEventListener('click', function () {
      setDrawer(!sidebar.classList.contains('is-open'));
    });
  }
  if (scrim) scrim.addEventListener('click', function () { setDrawer(false); });
  $$('.nav a').forEach(function (a) {
    a.addEventListener('click', function () {
      if (window.matchMedia('(max-width: 900px)').matches) setDrawer(false);
    });
  });

  /* ------------------------------------------------------------------ */
  /* 目次は狭い画面では畳んでおく                                        */
  /* ------------------------------------------------------------------ */
  var tocBox = $('#toc');
  if (tocBox && window.innerWidth < 1180) tocBox.removeAttribute('open');
  if (tocBox) {
    $$('a', tocBox).forEach(function (a) {
      a.addEventListener('click', function () {
        if (window.innerWidth < 1180) tocBox.removeAttribute('open');
      });
    });
  }

  /* ------------------------------------------------------------------ */
  /* 読み進みバー / トップへ戻る                                         */
  /* ------------------------------------------------------------------ */
  var bar = $('#progress-bar');
  var toTop = $('#totop');

  function onScroll() {
    var scrolled = window.scrollY;
    var height = doc.documentElement.scrollHeight - window.innerHeight;
    if (bar) bar.style.width = (height > 0 ? (scrolled / height) * 100 : 0) + '%';
    if (toTop) toTop.hidden = scrolled < 600;
    spy();
  }
  if (toTop) {
    toTop.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  /* ------------------------------------------------------------------ */
  /* 見出しの追従ハイライト                                              */
  /* ------------------------------------------------------------------ */
  var headings = $$('.doc-body [id]').filter(function (el) {
    return /^H[23]$/.test(el.tagName);
  });
  var tocLinks = {};
  $$('.toc-list a, .nav-sublink').forEach(function (a) {
    var id = a.getAttribute('href').split('#')[1];
    if (!id) return;
    (tocLinks[id] = tocLinks[id] || []).push(a);
  });

  var spyTicking = false;
  function spy() {
    if (spyTicking || !headings.length) return;
    spyTicking = true;
    window.requestAnimationFrame(function () {
      spyTicking = false;
      var offset = 110;  // html の scroll-padding-top (約80px) より少し大きく
      var currentId = headings[0].id;
      for (var i = 0; i < headings.length; i++) {
        if (headings[i].getBoundingClientRect().top <= offset) currentId = headings[i].id;
        else break;
      }
      Object.keys(tocLinks).forEach(function (id) {
        tocLinks[id].forEach(function (a) {
          a.classList.toggle('is-current', id === currentId);
        });
      });
    });
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  onScroll();

  /* ------------------------------------------------------------------ */
  /* 表のモバイル対応（列が多い表だけカード表示に）                      */
  /* ------------------------------------------------------------------ */
  $$('.table-wrap').forEach(function (wrap) {
    var cols = parseInt(wrap.dataset.cols || '0', 10) || $$('thead th', wrap).length;
    if (cols >= 4) wrap.classList.add('stacked-wide');
    else if (cols === 3) wrap.classList.add('stacked');
  });

  /* ------------------------------------------------------------------ */
  /* ワークのチェック状態                                                */
  /* ------------------------------------------------------------------ */
  var DONE_KEY = 'mk-works-done';
  var done = store(DONE_KEY, []);
  if (!Array.isArray(done)) done = [];

  var doneEl = $('#work-done');
  var totalEl = $('#work-total');
  var fillEl = $('#work-fill');
  var grandTotal = parseInt(doc.body.dataset.worktotal || '0', 10) || 0;

  function paint(id, checked) {
    $$('.work-toggle[data-work="' + id + '"]').forEach(function (input) {
      input.checked = checked;
      var card = input.closest('.work');
      if (card) card.classList.toggle('is-done', checked);
      var row = input.closest('.wl-item');
      if (row) row.classList.toggle('is-done', checked);
      var step = input.closest('.ps-step');
      if (step) step.classList.toggle('is-done', checked);
    });
  }

  function refreshCounter() {
    if (totalEl) totalEl.textContent = String(grandTotal);
    if (doneEl) doneEl.textContent = String(done.length);
    if (fillEl) {
      fillEl.style.width = (grandTotal ? (done.length / grandTotal) * 100 : 0) + '%';
    }
    // サイドバーの章ごとの進捗
    var byPage = window.MK_WORKS || {};
    $$('.nav-count').forEach(function (el) {
      var ids = byPage[el.dataset.page] || [];
      var total = ids.length;
      var n = countDone(ids);
      el.textContent = n + '/' + total;
      el.classList.toggle('is-complete', total > 0 && n === total);
    });

    // ドーナツ（章の扉・進捗ボード）
    $$('.donut').forEach(function (el) {
      var page = el.dataset.page;
      var ids = page === '__all__' ? allIds() : (byPage[page] || []);
      var total = ids.length;
      var n = countDone(ids);
      var pct = total ? Math.round((n / total) * 100) : 0;
      el.style.setProperty('--p', String(pct));
      var pctEl = $('.donut-pct', el);
      if (pctEl) pctEl.childNodes[0].nodeValue = String(pct);
      var doneNode = $('.donut-done', el);
      var totalNode = $('.donut-total', el);
      if (doneNode) doneNode.textContent = String(n);
      if (totalNode) totalNode.textContent = String(total);
      el.classList.toggle('is-complete', total > 0 && n === total);
    });
  }

  function countDone(ids) {
    var n = 0;
    for (var i = 0; i < ids.length; i++) if (done.indexOf(ids[i]) !== -1) n++;
    return n;
  }

  function allIds() {
    var byPage = window.MK_WORKS || {};
    var out = [];
    Object.keys(byPage).forEach(function (k) { out = out.concat(byPage[k]); });
    return out;
  }

  $$('.work-toggle').forEach(function (input) {
    var id = input.dataset.work;
    if (done.indexOf(id) !== -1) paint(id, true);
    input.addEventListener('change', function () {
      var idx = done.indexOf(id);
      if (input.checked && idx === -1) done.push(id);
      else if (!input.checked && idx !== -1) done.splice(idx, 1);
      save(DONE_KEY, done);
      paint(id, input.checked);
      refreshCounter();
    });
  });
  refreshCounter();

  /* ------------------------------------------------------------------ */
  /* スクロールに合わせて要素を立ち上げる                                */
  /* ------------------------------------------------------------------ */
  var wantsMotion = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (wantsMotion && 'IntersectionObserver' in window) {
    var targets = $$('.doc-body > h2, .doc-body > .work, .doc-body > .note,'
      + '.doc-body > .grid, .doc-body > .steps, .doc-body > .timeline,'
      + '.doc-body > .table-wrap, .doc-body > .figure, .doc-body > .pullquote,'
      + '.doc-body > .stats, .doc-body > .flow, .doc-body > .tree,'
      + '.doc-body > .linkcards, .doc-body > .chcards, .doc-body > .wl-chapter,'
      + '.doc-body > .roadmap, .doc-body > .htree, .doc-body > .recap,'
      + '.doc-body > .progress-board, .doc-body > .ps-steps');

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        io.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.02 });

    targets.forEach(function (el, i) {
      // 初期表示で見えている範囲は動かさない（読み始めを妨げないため）
      if (el.getBoundingClientRect().top < window.innerHeight * 0.9) return;
      el.classList.add('reveal');
      el.style.transitionDelay = (Math.min(i % 3, 2) * 45) + 'ms';
      io.observe(el);
    });
  }

  /* ------------------------------------------------------------------ */
  /* サイト内検索                                                        */
  /* ------------------------------------------------------------------ */
  var modal = $('#search-modal');
  var input = $('#search-input');
  var results = $('#search-results');
  var openBtn = $('#search-btn');
  var closeBtn = $('#search-close');
  var index = null;
  var loading = false;
  var activeIdx = -1;

  function normalize(s) {
    var out = String(s);
    if (out.normalize) out = out.normalize('NFKC');
    return out.toLowerCase();
  }

  function loadIndex() {
    if (index || loading) return Promise.resolve();
    loading = true;
    return fetch('search.json')
      .then(function (r) { return r.json(); })
      .then(function (data) { index = data; loading = false; })
      .catch(function () {
        loading = false;
        index = [];
        if (results) {
          results.innerHTML =
            '<p class="search-empty">検索インデックスを読み込めませんでした。' +
            'ファイルを直接開いている場合は、公開サイトからご利用ください。</p>';
        }
      });
  }

  function openSearch() {
    if (!modal) return;
    modal.hidden = false;
    doc.body.style.overflow = 'hidden';
    loadIndex().then(function () { if (input.value) render(input.value); });
    input.focus();
    input.select();
  }
  function closeSearch() {
    if (!modal) return;
    modal.hidden = true;
    doc.body.style.overflow = '';
  }

  function excerpt(text, needle) {
    var lower = normalize(text);
    var at = lower.indexOf(needle);
    if (at === -1) return text.slice(0, 110);
    var start = Math.max(0, at - 30);
    var slice = text.slice(start, start + 130);
    return (start > 0 ? '…' : '') + slice;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function highlight(text, needle) {
    var safe = escapeHtml(text);
    if (!needle) return safe;
    var lowerSafe = normalize(safe);
    var at = lowerSafe.indexOf(needle);
    if (at === -1) return safe;
    return safe.slice(0, at) + '<mark>' + safe.slice(at, at + needle.length) +
      '</mark>' + safe.slice(at + needle.length);
  }

  function render(query) {
    if (!results) return;
    var q = normalize(query.trim());
    if (!q) {
      results.innerHTML =
        '<p class="search-empty">章タイトル・見出し・本文からキーワードを探します。</p>';
      return;
    }
    if (!index) { results.innerHTML = '<p class="search-empty">読み込み中…</p>'; return; }

    var hits = [];
    index.forEach(function (row) {
      var inTitle = normalize(row.s).indexOf(q);
      var inText = normalize(row.t).indexOf(q);
      var inPage = normalize(row.p).indexOf(q);
      if (inTitle === -1 && inText === -1 && inPage === -1) return;
      var score = inTitle !== -1 ? 0 : (inPage !== -1 ? 40 : 100);
      score += inTitle !== -1 ? inTitle : (inText !== -1 ? Math.min(inText, 900) / 10 : 0);
      hits.push({ row: row, score: score });
    });
    hits.sort(function (a, b) { return a.score - b.score; });
    hits = hits.slice(0, 30);

    if (!hits.length) {
      results.innerHTML = '<p class="search-empty">「' + escapeHtml(query) +
        '」に一致する項目は見つかりませんでした。</p>';
      return;
    }
    results.innerHTML = hits.map(function (hit, i) {
      var r = hit.row;
      return '<a class="search-hit' + (i === 0 ? ' is-active' : '') + '" href="' +
        r.u + '#' + r.a + '">' +
        '<p class="search-hit-crumb">' + escapeHtml(r.p) + '</p>' +
        '<p class="search-hit-title">' + highlight(r.s, q) + '</p>' +
        '<p class="search-hit-text">' + highlight(excerpt(r.t, q), q) + '</p></a>';
    }).join('');
    activeIdx = 0;
  }

  function moveActive(delta) {
    var hits = $$('.search-hit', results);
    if (!hits.length) return;
    hits[activeIdx] && hits[activeIdx].classList.remove('is-active');
    activeIdx = (activeIdx + delta + hits.length) % hits.length;
    hits[activeIdx].classList.add('is-active');
    hits[activeIdx].scrollIntoView({ block: 'nearest' });
  }

  if (openBtn) openBtn.addEventListener('click', openSearch);
  if (closeBtn) closeBtn.addEventListener('click', closeSearch);
  if (modal) {
    modal.addEventListener('click', function (e) {
      if (e.target === modal) closeSearch();
    });
  }
  if (input) {
    var timer = null;
    input.addEventListener('input', function () {
      clearTimeout(timer);
      var value = input.value;
      timer = setTimeout(function () { render(value); }, 90);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); moveActive(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); moveActive(-1); }
      else if (e.key === 'Enter') {
        var hits = $$('.search-hit', results);
        if (hits[activeIdx]) { e.preventDefault(); window.location.href = hits[activeIdx].href; }
      }
    });
  }

  doc.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    var typing = tag === 'input' || tag === 'textarea' || e.target.isContentEditable;
    if (e.key === 'Escape' && modal && !modal.hidden) { closeSearch(); return; }
    if (typing) return;
    if (e.key === '/' || ((e.metaKey || e.ctrlKey) && e.key === 'k')) {
      e.preventDefault();
      openSearch();
    }
  });
})();
