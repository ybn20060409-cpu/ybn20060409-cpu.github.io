/* ══════════════════════════════════════════════════════════════
   blog-v2 · 首页交互：搜索 + 标签云 + URL hash + 卡片动画
   ══════════════════════════════════════════════════════════════ */

(function() {
  'use strict';

  var cards = document.querySelectorAll('.post-card');
  if (!cards.length) return;

  // ── 标签云 ────────────────────────────────────────────────
  var tagContainer = document.getElementById('tagCloud');
  var activeTags = [];
  var searchTerm = '';

  if (tagContainer) {
    tagContainer.addEventListener('click', function(e) {
      var btn = e.target.closest('.tag-btn');
      if (!btn) return;
      var tag = btn.dataset.tag;

      if (tag === '_all') {
        activeTags = [];
      } else {
        var idx = activeTags.indexOf(tag);
        if (idx >= 0) {
          activeTags.splice(idx, 1);
        } else {
          activeTags.push(tag);
        }
      }

      updateTagUI();
      filterCards();
      updateURLHash();
    });
  }

  function updateTagUI() {
    var btns = document.querySelectorAll('.tag-btn');
    btns.forEach(function(b) {
      if (b.dataset.tag === '_all') {
        b.classList.toggle('active', activeTags.length === 0);
      } else {
        b.classList.toggle('active', activeTags.indexOf(b.dataset.tag) >= 0);
      }
    });
  }

  // ── 搜索 ─────────────────────────────────────────────────
  var searchInput = document.getElementById('searchInput');
  if (searchInput) {
    var debounceTimer;
    searchInput.addEventListener('input', function() {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function() {
        searchTerm = searchInput.value.trim().toLowerCase();
        filterCards();
        updateURLHash();
      }, 150);
    });

    // 清除按钮
    var clearBtn = document.getElementById('searchClear');
    if (clearBtn) {
      clearBtn.addEventListener('click', function() {
        searchInput.value = '';
        searchTerm = '';
        filterCards();
        updateURLHash();
        clearBtn.style.display = 'none';
      });
      searchInput.addEventListener('input', function() {
        clearBtn.style.display = searchInput.value ? '' : 'none';
      });
    }
  }

  // ── 过滤逻辑 ─────────────────────────────────────────────
  function filterCards() {
    var visibleCount = 0;

    cards.forEach(function(card) {
      var tags = card.dataset.tags ? card.dataset.tags.split(',') : [];
      var title = (card.dataset.title || '').toLowerCase();
      var excerpt = (card.dataset.excerpt || '').toLowerCase();
      var tagStr = (card.dataset.tags || '').toLowerCase();

      // 标签筛选
      var tagMatch = activeTags.length === 0 ||
        activeTags.every(function(t) { return tags.indexOf(t) >= 0; });

      // 关键词搜索
      var searchMatch = !searchTerm ||
        title.indexOf(searchTerm) >= 0 ||
        excerpt.indexOf(searchTerm) >= 0 ||
        tagStr.indexOf(searchTerm) >= 0;

      if (tagMatch && searchMatch) {
        card.style.display = '';
        // 动画延迟
        card.style.animationDelay = (visibleCount * 0.05) + 's';
        visibleCount++;
      } else {
        card.style.display = 'none';
      }
    });

    // 空状态
    var emptyEl = document.getElementById('emptyState');
    if (emptyEl) {
      emptyEl.style.display = visibleCount === 0 ? '' : 'none';
    }

    // 更新计数
    var countEl = document.getElementById('postCount');
    if (countEl) {
      countEl.textContent = visibleCount;
    }
  }

  // ── URL hash ─────────────────────────────────────────────
  function updateURLHash() {
    var params = [];
    if (searchTerm) params.push('q=' + encodeURIComponent(searchTerm));
    if (activeTags.length) params.push('tag=' + activeTags.map(encodeURIComponent).join(','));
    var hash = params.length ? '#' + params.join('&') : '';
    if (window.location.hash !== hash) {
      history.replaceState(null, '', hash || window.location.pathname);
    }
  }

  function readURLHash() {
    var hash = window.location.hash.slice(1);
    if (!hash) return;
    var parts = hash.split('&');
    parts.forEach(function(part) {
      var kv = part.split('=');
      if (kv[0] === 'q' && kv[1]) {
        searchTerm = decodeURIComponent(kv[1]);
        if (searchInput) {
          searchInput.value = searchTerm;
          var cb = document.getElementById('searchClear');
          if (cb) cb.style.display = searchTerm ? '' : 'none';
        }
      }
      if (kv[0] === 'tag' && kv[1]) {
        activeTags = decodeURIComponent(kv[1]).split(',').filter(Boolean);
      }
    });
  }

  // ── 初始化 ───────────────────────────────────────────────
  readURLHash();
  updateTagUI();
  filterCards();

  // ── 键盘快捷键 ──────────────────────────────────────────
  document.addEventListener('keydown', function(e) {
    // Ctrl+K or / to focus search
    if ((e.ctrlKey && e.key === 'k') || (e.key === '/' && !e.ctrlKey && !e.metaKey && document.activeElement === document.body)) {
      e.preventDefault();
      if (searchInput) searchInput.focus();
    }
  });

})();
