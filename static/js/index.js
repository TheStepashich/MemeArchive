const el = {
        queryInput: document.getElementById('queryInput'),
        searchBox: document.getElementById('searchBox'),
        searchToggle: document.getElementById('searchToggle'),
        sortSelect: document.getElementById('sortSelect'),
        tagsList: document.getElementById('tagsList'),
        allTagsBtn: document.getElementById('allTagsBtn'),
        addBtn: document.getElementById('addBtn'),
        uploadWrap: document.getElementById('uploadWrap'),
        imageFile: document.getElementById('imageFile'),
        uploadTagsInput: document.getElementById('uploadTagsInput'),
        uploadBtn: document.getElementById('uploadBtn'),
        cancelUploadBtn: document.getElementById('cancelUploadBtn'),
        uploadLoader: document.getElementById('uploadLoader'),
        captchaRow: document.getElementById('captchaRow'),
        captchaImage: document.getElementById('captchaImage'),
        captchaInput: document.getElementById('captchaInput'),
        captchaRefreshBtn: document.getElementById('captchaRefreshBtn'),
        searchMeta: document.getElementById('searchMeta'),
        resultsDiv: document.getElementById('results'),
        feedSentinel: document.getElementById('feedSentinel'),
        loadMoreBtn: document.getElementById('loadMoreBtn'),
        toasts: document.getElementById('toasts')
    };

    const PAGE_SIZE = 24;
    const SEARCH_N = 24;

    let isUploading = false;
    let isSearching = false;
    let mode = 'feed';
    let order = 'new';
    let selectedTags = new Set();
    let feedOffset = 0;
    let feedTotal = 0;
    let feedLoading = false;
    let feedHasMore = true;
    let feedController = null;
    let searchController = null;
    let captchaEnabled = false;
    let captchaId = null;

    function toast(message, type = 'info') {
        const node = document.createElement('div');
        node.className = 'toast ' + type;
        node.textContent = message;
        el.toasts.appendChild(node);
        requestAnimationFrame(() => node.classList.add('visible'));
        setTimeout(() => {
            node.classList.remove('visible');
            setTimeout(() => node.remove(), 200);
        }, 4000);
    }

    async function readError(res) {
        try {
            const data = await res.json();
            return data.detail || res.statusText || 'неизвестная ошибка';
        } catch (err) {
            return res.statusText || 'неизвестная ошибка';
        }
    }

    function formatFeedDate(value) {
        if (!value) return '';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '';
        return date.toLocaleString('ru-RU', {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    function setUploading(value) {
        isUploading = !!value;
        el.uploadLoader.classList.toggle('hidden', !isUploading);
        el.uploadBtn.disabled = isUploading;
        el.cancelUploadBtn.disabled = isUploading;
    }

    function setSearching(value) {
        isSearching = !!value;
    }

    async function refreshCaptcha() {
        if (!captchaEnabled) return;
        try {
            const res = await fetch('/captcha', { cache: 'no-store' });
            if (!res.ok) throw new Error(await readError(res));
            const data = await res.json();
            captchaId = data.id;
            el.captchaImage.src = data.image;
            el.captchaInput.value = '';
        } catch (err) {
            console.error('Captcha error', err);
            captchaId = null;
            toast('Не удалось загрузить капчу: ' + err.message, 'error');
        }
    }

    async function loadPublicConfig() {
        try {
            const res = await fetch('/config', { cache: 'no-store' });
            if (!res.ok) return;
            const data = await res.json();
            captchaEnabled = !!data.captcha_enabled;
            el.captchaRow.classList.toggle('hidden', !captchaEnabled);
        } catch (err) {
            console.error('Config error', err);
        }
    }

    el.captchaRefreshBtn.addEventListener('click', refreshCaptcha);

    el.addBtn.addEventListener('click', () => {
        el.uploadWrap.classList.toggle('visible');
    });

    el.cancelUploadBtn.addEventListener('click', () => {
        el.uploadWrap.classList.remove('visible');
        el.imageFile.value = '';
        el.uploadTagsInput.value = '';
        if (captchaEnabled) refreshCaptcha();
    });

    el.uploadBtn.addEventListener('click', async () => {
        const file = el.imageFile.files?.[0];
        if (!file) {
            toast('Выберите изображение для загрузки', 'error');
            return;
        }
        if (captchaEnabled && !el.captchaInput.value.trim()) {
            toast('Введите код с картинки', 'error');
            return;
        }

        setUploading(true);
        const formData = new FormData();
        formData.append('file', file);
        formData.append('tags', el.uploadTagsInput.value);
        if (captchaEnabled) {
            formData.append('captcha_id', captchaId || '');
            formData.append('captcha_answer', el.captchaInput.value.trim());
        }

        try {
            const res = await fetch('/add', { method: 'POST', body: formData });
            if (!res.ok) {
                throw new Error(await readError(res));
            }
            const data = await res.json();
            el.imageFile.value = '';
            el.uploadTagsInput.value = '';
            el.uploadWrap.classList.remove('visible');
            if (data.pending) {
                const until = data.expires_at ? formatDate(data.expires_at) : '';
                toast(until ? 'Мем на модерации до ' + until : 'Мем отправлен на модерацию', 'success');
            } else {
                toast(data.duplicate ? 'Такой мем уже есть в архиве' : 'Мем добавлен в архив', 'success');
                await refreshTagChips();
                if (mode === 'feed') loadFeed(true);
            }
        } catch (err) {
            console.error('Upload error', err);
            toast('Ошибка при добавлении: ' + err.message, 'error');
        } finally {
            setUploading(false);
            if (captchaEnabled) refreshCaptcha();
        }
    });

    el.queryInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') performSearch();
    });

    const mobileMedia = window.matchMedia('(max-width: 768px)');
    const headerEl = document.querySelector('.header');

    function placeSearchBox() {
        if (mobileMedia.matches) {
            headerEl.after(el.searchBox);
        } else {
            el.searchToggle.after(el.searchBox);
        }
    }

    placeSearchBox();
    if (mobileMedia.matches) {
        el.searchBox.classList.add('collapsed');
    }
    el.searchToggle.addEventListener('click', () => {
        const collapsed = el.searchBox.classList.toggle('collapsed');
        if (!collapsed) el.queryInput.focus();
    });
    mobileMedia.addEventListener('change', (event) => {
        placeSearchBox();
        if (!event.matches) el.searchBox.classList.remove('collapsed');
    });

    el.sortSelect.addEventListener('change', () => {
        order = el.sortSelect.value;
        if (mode !== 'feed') {
            el.queryInput.value = '';
        }
        loadFeed(true);
    });

    el.loadMoreBtn.addEventListener('click', () => loadFeed(false));

    function updateFeedSentinel() {
        const visible = mode === 'feed' && feedHasMore;
        el.feedSentinel.classList.toggle('hidden', !visible);
    }

    async function loadFeed(reset = false) {
        if (reset) {
            if (feedController) feedController.abort();
            if (searchController) searchController.abort();
            feedController = null;
            searchController = null;
            feedLoading = false;
            setSearching(false);
            mode = 'feed';
            feedOffset = 0;
            feedHasMore = true;
            el.searchMeta.classList.add('hidden');
            renderResults([], { emptyText: 'Загрузка ленты...' });
        } else if (feedLoading) {
            return;
        }
        if (!feedHasMore) {
            updateFeedSentinel();
            return;
        }

        const controller = new AbortController();
        feedController = controller;
        feedLoading = true;
        updateFeedSentinel();

        try {
            const params = new URLSearchParams({
                limit: String(PAGE_SIZE),
                offset: String(feedOffset),
                order
            });
            selectedTags.forEach((tag) => params.append('tags', tag));
            const res = await fetch('/images?' + params.toString(), { signal: controller.signal });
            if (!res.ok) throw new Error(await readError(res));
            const data = await res.json();
            const items = data.results || [];

            renderResults(items, {
                append: !reset,
                emptyText: feedIsEmptyText(data.total)
            });

            feedOffset = data.next_offset;
            feedTotal = data.total;
            feedHasMore = items.length > 0 && feedOffset < data.total;

            el.searchMeta.textContent = `Загружено: ${feedOffset} из ${data.total}`;
            el.searchMeta.classList.remove('hidden');
            saveFeedState();
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Feed error', err);
            toast('Ошибка при загрузке ленты: ' + err.message, 'error');
            feedHasMore = false;
        } finally {
            if (feedController === controller) {
                feedController = null;
                feedLoading = false;
                updateFeedSentinel();
            }
        }
    }

    function feedIsEmptyText(total) {
        if (total) return 'Не удалось отобразить изображения.';
        if (selectedTags.size) return 'С такими тегами ничего нет.';
        return 'Архив пока пуст. Добавьте первый мем!';
    }

    function maybeLoadMore() {
        if (mode === 'feed' && !feedLoading && feedHasMore) {
            loadFeed(false);
        }
    }

    const TOTAL_POLL_MS = 15000;
    let totalPollBusy = false;

    async function refreshFeedTotal() {
        if (mode !== 'feed' || document.hidden || totalPollBusy) return;
        totalPollBusy = true;
        try {
            const res = await fetch('/health', { cache: 'no-store' });
            if (!res.ok) return;
            const data = await res.json();
            const total = Number(data.images);
            if (!Number.isFinite(total) || total === feedTotal) return;

            const wasEmpty = feedOffset === 0 && feedTotal === 0;
            feedTotal = total;
            if (wasEmpty) {
                loadFeed(true);
                return;
            }
            feedHasMore = feedOffset < feedTotal;
            if (feedOffset > 0) {
                el.searchMeta.textContent = `Загружено: ${feedOffset} из ${feedTotal}`;
                el.searchMeta.classList.remove('hidden');
            }
            updateFeedSentinel();
        } catch (err) {
            console.debug('Feed total poll failed', err);
        } finally {
            totalPollBusy = false;
        }
    }

    setInterval(refreshFeedTotal, TOTAL_POLL_MS);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refreshFeedTotal();
    });

    async function performSearch() {
        const query = el.queryInput.value.trim();
        if (!query) {
            loadFeed(true);
            return;
        }

        if (searchController) searchController.abort();
        if (feedController) feedController.abort();
        feedController = null;
        feedLoading = false;
        const controller = new AbortController();
        searchController = controller;
        mode = 'search';
        feedHasMore = false;
        updateFeedSentinel();
        setSearching(true);
        el.searchMeta.classList.add('hidden');
        renderResults([], { emptyText: 'ПОИСК...' });

        try {
            const res = await fetch('/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query,
                    n_results: SEARCH_N,
                    tags: [...selectedTags]
                }),
                signal: controller.signal
            });

            if (!res.ok) {
                throw new Error(await readError(res));
            }

            const data = await res.json();
            renderResults(data.results || []);
            if (data.matched_tag) {
                const similar = data.results.length - data.matched_tag_count;
                el.searchMeta.textContent = `По тегу #${data.matched_tag}: ${data.matched_tag_count} · похожих: ${similar}`;
            } else {
                el.searchMeta.textContent = `Найдено: ${data.results.length} из ${data.total} в архиве`;
            }
            el.searchMeta.classList.remove('hidden');
            saveFeedState();
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Search error', err);
            toast('Ошибка при поиске: ' + err.message, 'error');
            renderResults([], { emptyText: 'Ничего не найдено.' });
        } finally {
            if (searchController === controller) {
                searchController = null;
                setSearching(false);
            }
        }
    }

    function renderResults(items, { append = false, emptyText = 'Ничего не найдено.' } = {}) {
        if (!append) el.resultsDiv.innerHTML = '';
        if (!items || items.length === 0) {
            if (!append) {
                const empty = document.createElement('div');
                empty.className = 'empty-state';
                empty.textContent = emptyText;
                el.resultsDiv.appendChild(empty);
            }
            return;
        }

        const fragment = document.createDocumentFragment();
        items.forEach((item) => {
            fragment.appendChild(buildCard(item));
        });
        el.resultsDiv.appendChild(fragment);
    }

    function buildCard(item) {
        const card = document.createElement('article');
        card.className = 'meme-card';
        card.tabIndex = 0;
        const openMeme = () => {
            saveFeedState();
            window.location.href = '/meme/' + encodeURIComponent(item.id);
        };
        card.addEventListener('click', (event) => {
            if (event.target.closest('button')) return;
            openMeme();
        });
        card.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                openMeme();
            }
        });

        const img = document.createElement('img');
        img.className = 'meme-image';
        img.src = '/image/' + encodeURIComponent(item.stored_name || '');
        img.alt = (item.description || 'Мем').slice(0, 120);
        img.loading = 'lazy';
        if (item.width && item.height) {
            img.width = item.width;
            img.height = item.height;
        }

        const content = document.createElement('div');
        content.className = 'meme-content';

        const title = document.createElement('h3');
        title.className = 'meme-title';
        title.textContent = item.original_filename || 'Мем';

        content.appendChild(title);

        if (item.description) {
            const desc = document.createElement('p');
            desc.className = 'meme-desc';
            desc.textContent = item.description;
            content.appendChild(desc);
        }

        if ((item.tags || []).length) {
            const tags = document.createElement('div');
            tags.className = 'meme-tags';
            item.tags.forEach((tag) => {
                const badge = document.createElement('span');
                badge.className = 'meme-tag';
                badge.textContent = '#' + tag;
                tags.appendChild(badge);
            });
            content.appendChild(tags);
        }

        const footer = document.createElement('div');
        footer.className = 'meme-footer';

        const date = document.createElement('span');
        date.className = 'date';
        const dateText = formatFeedDate(item.created_at);
        date.textContent = dateText || '—';
        if (dateText) date.title = dateText;

        footer.appendChild(date);
        content.appendChild(footer);

        card.appendChild(img);
        card.appendChild(content);
        return card;
    }

    function toggleTag(tag) {
        if (selectedTags.has(tag)) {
            selectedTags.delete(tag);
        } else {
            selectedTags.add(tag);
        }
        updateChipStates();
        if (mode !== 'feed') el.queryInput.value = '';
        loadFeed(true);
    }

    function clearTagFilter() {
        if (!selectedTags.size) return;
        selectedTags.clear();
        updateChipStates();
        if (mode !== 'feed') el.queryInput.value = '';
        loadFeed(true);
    }

    async function refreshTagChips() {
        allTagsCache = null;
        revealedTags = 0;
        el.allTagsBtn.classList.remove('hidden');

        let tags = [];
        try {
            const res = await fetch('/tags?limit=3');
            if (res.ok) tags = (await res.json()) || [];
        } catch (err) {
            console.error('Tags error', err);
        }

        const chips = [...selectedTags];
        tags.forEach((tag) => {
            if (!chips.includes(tag)) chips.push(tag);
        });

        el.tagsList.innerHTML = '';
        const allChip = document.createElement('span');
        allChip.className = 'tag tag-active';
        allChip.textContent = 'ВСЕ';
        allChip.addEventListener('click', clearTagFilter);
        el.tagsList.appendChild(allChip);

        chips.forEach((tag) => {
            const chip = document.createElement('span');
            chip.className = 'tag tag-default';
            chip.dataset.tag = tag;
            chip.textContent = tag;
            chip.addEventListener('click', () => toggleTag(tag));
            el.tagsList.appendChild(chip);
        });

        updateChipStates();
    }

    function appendTagChip(container, tag) {
        const chip = document.createElement('span');
        chip.className = 'tag tag-default';
        chip.dataset.tag = tag;
        chip.textContent = tag;
        chip.addEventListener('click', () => toggleTag(tag));
        container.appendChild(chip);
    }

    const TAGS_BATCH = 20;
    let allTagsCache = null;
    let revealedTags = 0;

    async function loadMoreTags() {
        if (allTagsCache === null) {
            try {
                const res = await fetch('/tags');
                if (!res.ok) throw new Error(await readError(res));
                allTagsCache = (await res.json()) || [];
            } catch (err) {
                allTagsCache = null;
                console.error('All tags error', err);
                toast('Не удалось загрузить теги: ' + err.message, 'error');
                return;
            }
        }

        if (!allTagsCache.length) {
            el.allTagsBtn.classList.add('hidden');
            toast('Теги ещё не заданы', 'info');
            return;
        }

        const existing = new Set(
            Array.from(el.tagsList.querySelectorAll('[data-tag]'), (chip) => chip.dataset.tag)
        );
        const batch = allTagsCache.slice(revealedTags, revealedTags + TAGS_BATCH);
        batch.forEach((tag) => {
            if (!existing.has(tag)) appendTagChip(el.tagsList, tag);
        });
        revealedTags += batch.length;
        updateChipStates();

        if (revealedTags >= allTagsCache.length) {
            el.allTagsBtn.classList.add('hidden');
        }
    }

    el.allTagsBtn.addEventListener('click', loadMoreTags);

    function updateChipStates() {
        const allChip = el.tagsList.firstElementChild;
        if (allChip) {
            allChip.classList.toggle('tag-active', selectedTags.size === 0);
            allChip.classList.toggle('tag-default', selectedTags.size > 0);
        }
        document.querySelectorAll('#tagsList [data-tag]').forEach((chip) => {
            const active = selectedTags.has(chip.dataset.tag);
            chip.classList.toggle('tag-active', active);
            chip.classList.toggle('tag-default', !active);
        });
    }

    const feedObserver = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) maybeLoadMore();
    }, { rootMargin: '400px 0px' });
    feedObserver.observe(el.feedSentinel);

    const FEED_STATE_KEY = 'feedState';

    function saveFeedState(scrollY = null) {
        try {
            sessionStorage.setItem(FEED_STATE_KEY, JSON.stringify({
                mode,
                order,
                query: el.queryInput.value.trim(),
                selectedTags: [...selectedTags],
                feedOffset,
                scrollY: scrollY === null ? window.scrollY : scrollY
            }));
        } catch (err) {
            console.warn('State save failed', err);
        }
    }

    function readFeedState() {
        try {
            const raw = sessionStorage.getItem(FEED_STATE_KEY);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : null;
        } catch (err) {
            return null;
        }
    }

    async function restoreFeed(saved) {
        const target = Math.max(0, Number(saved.feedOffset) || 0);
        let guard = 0;
        await loadFeed(true);
        while (feedHasMore && feedOffset < target && guard < 40) {
            await loadFeed(false);
            guard += 1;
        }
        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        window.scrollTo(0, Number(saved.scrollY) || 0);
    }

    window.addEventListener('pagehide', () => saveFeedState());

    (async () => {
        const urlQuery = new URLSearchParams(window.location.search).get('query');
        const saved = urlQuery ? null : readFeedState();

        if (saved) {
            el.sortSelect.value = saved.order || 'new';
            order = el.sortSelect.value;
            selectedTags = new Set(saved.selectedTags || []);
        }

        await loadPublicConfig();
        if (captchaEnabled) await refreshCaptcha();
        await refreshTagChips();

        if (urlQuery) {
            el.queryInput.value = urlQuery;
            performSearch();
        } else if (saved && saved.mode === 'search' && saved.query) {
            el.queryInput.value = saved.query;
            await performSearch();
            await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            window.scrollTo(0, Number(saved.scrollY) || 0);
        } else if (saved) {
            await restoreFeed(saved);
        } else {
            loadFeed(true);
        }
    })();
