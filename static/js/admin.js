(function () {
    const TOKEN_KEY = 'memeArchiveAdminToken';
    const POLL_MS = 15000;

    const el = {
        loginCard: document.getElementById('loginCard'),
        loginForm: document.getElementById('loginForm'),
        tokenInput: document.getElementById('tokenInput'),
        loginError: document.getElementById('loginError'),
        panel: document.getElementById('panel'),
        statsGrid: document.getElementById('statsGrid'),
        statsUpdated: document.getElementById('statsUpdated'),
        pendingList: document.getElementById('pendingList'),
        pendingMeta: document.getElementById('pendingMeta'),
        memesList: document.getElementById('memesList'),
        deleteId: document.getElementById('deleteId'),
        deleteIdBtn: document.getElementById('deleteIdBtn'),
        logoutBtn: document.getElementById('logoutBtn'),
        toasts: document.getElementById('toasts')
    };

    let token = sessionStorage.getItem(TOKEN_KEY) || '';
    let pollTimer = null;
    let countdownTimer = null;
    let thumbUrls = [];
    let renderGen = 0;

    function toast(message, type = 'info') {
        const node = document.createElement('div');
        node.className = 'toast ' + type;
        node.textContent = message;
        el.toasts.appendChild(node);
        requestAnimationFrame(() => node.classList.add('visible'));
        setTimeout(() => {
            node.classList.remove('visible');
            setTimeout(() => node.remove(), 300);
        }, 4000);
    }

    async function readError(res) {
        try {
            const data = await res.json();
            if (data && data.detail) return String(data.detail);
        } catch (err) {
            console.error('Error payload', err);
        }
        return res.status + ' ' + res.statusText;
    }

    function authHeaders() {
        return token ? { 'X-API-Key': token } : {};
    }

    async function api(path, options = {}) {
        const headers = Object.assign({}, authHeaders(), options.headers || {});
        const res = await fetch(path, Object.assign({}, options, { headers }));
        if (res.status === 401) {
            showLogin('Неверный или истёкший токен администратора.');
            throw new Error('unauthorized');
        }
        if (res.status === 503) {
            showLogin('ADMIN_TOKEN не задан на сервере.');
            throw new Error('unauthorized');
        }
        if (!res.ok) throw new Error(await readError(res));
        return res;
    }

    function formatDuration(seconds) {
        const total = Math.max(0, Math.floor(seconds));
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        if (hours > 0) return hours + ' ч ' + minutes + ' мин';
        return minutes + ' мин';
    }

    function formatLeft(seconds) {
        const total = Math.max(0, Math.floor(seconds));
        if (total >= 3600) return formatDuration(total);
        const minutes = Math.floor(total / 60);
        const rest = total % 60;
        return minutes + ':' + String(rest).padStart(2, '0');
    }

    function stat(value, label, accent = false) {
        const node = document.createElement('div');
        node.className = 'stat' + (accent ? ' accent' : '');
        const valueNode = document.createElement('div');
        valueNode.className = 'stat-value';
        valueNode.textContent = String(value);
        const labelNode = document.createElement('div');
        labelNode.className = 'stat-label';
        labelNode.textContent = label;
        node.append(valueNode, labelNode);
        return node;
    }

    function renderStats(data) {
        el.statsGrid.replaceChildren(
            stat(data.images, 'мемов в архиве', true),
            stat(data.pending_count, 'на модерации', true),
            stat(data.upstream_blocked_for > 0 ? formatDuration(data.upstream_blocked_for) : 'нет', 'Gemini заблокирован', data.upstream_blocked_for > 0),
            stat(data.uploads_received, 'загрузок получено'),
            stat(data.uploads_manual_approved, 'одобрено вручную'),
            stat(data.uploads_auto_approved, 'опубликовано автоматически'),
            stat(data.uploads_rejected, 'отклонено'),
            stat(data.captcha_failures, 'ошибок капчи'),
            stat(data.description_calls, 'описаний получено'),
            stat(data.description_errors, 'ошибок описаний'),
            stat(data.description_rate_limits, '429 при описаниях'),
            stat(data.embedding_document_calls, 'эмбеддингов документов'),
            stat(data.embedding_query_calls, 'эмбеддингов запросов'),
            stat(data.embedding_errors, 'ошибок эмбеддингов'),
            stat(Math.round(data.cache_hit_rate * 100) + '%', 'попаданий в кэш'),
            stat(data.cache_size, 'записей в кэше'),
            stat(data.gemini_calls, 'всего вызовов Gemini'),
            stat(data.gemini_errors, 'всего ошибок Gemini')
        );
        el.statsUpdated.textContent = data.updated_at ? 'обновлено ' + data.updated_at : '';
    }

    async function loadThumb(img, url, gen) {
        try {
            const res = await fetch(url, { headers: authHeaders(), cache: 'no-store' });
            if (!res.ok) return;
            const blob = await res.blob();
            if (gen !== renderGen) return;
            const objectUrl = URL.createObjectURL(blob);
            thumbUrls.push(objectUrl);
            img.src = objectUrl;
        } catch (err) {
            console.error('Thumb error', err);
        }
    }

    function renderPending(data) {
        renderGen += 1;
        const gen = renderGen;
        thumbUrls.forEach((url) => URL.revokeObjectURL(url));
        thumbUrls = [];

        el.pendingMeta.textContent = data.total + ' / ' + data.max_items;
        el.pendingList.replaceChildren();

        if (!data.items.length) {
            const empty = document.createElement('div');
            empty.className = 'empty';
            empty.textContent = 'Очередь пуста';
            el.pendingList.appendChild(empty);
            return;
        }

        data.items.forEach((item) => {
            const card = document.createElement('article');
            card.className = 'pending-card';

            const img = document.createElement('img');
            img.className = 'pending-thumb';
            img.alt = item.original_filename || 'мем на модерации';
            loadThumb(img, item.image_url, gen);

            const body = document.createElement('div');
            body.className = 'pending-body';

            const name = document.createElement('div');
            name.className = 'pending-name';
            name.textContent = item.original_filename || item.id;

            const tags = document.createElement('div');
            tags.className = 'pending-tags';
            (item.tags || []).forEach((tag) => {
                const chip = document.createElement('span');
                chip.className = 'pending-tag';
                chip.textContent = '#' + tag;
                tags.appendChild(chip);
            });

            const meta = document.createElement('div');
            meta.className = 'pending-meta';
            const sizeKb = item.size ? Math.max(1, Math.floor(item.size / 1024)) + ' КБ' : '?';
            meta.textContent = [
                (item.width || '?') + 'x' + (item.height || '?'),
                sizeKb,
                item.id.slice(0, 12) + '…'
            ].join(' · ');

            const countdown = document.createElement('div');
            countdown.className = 'pending-countdown';
            countdown.dataset.expires = item.expires_at || '';
            countdown.textContent = 'осталось ' + formatLeft(item.seconds_left);

            const actions = document.createElement('div');
            actions.className = 'pending-actions';

            const approveBtn = document.createElement('button');
            approveBtn.type = 'button';
            approveBtn.className = 'btn btn-primary';
            approveBtn.textContent = 'ОПУБЛИКОВАТЬ';
            approveBtn.addEventListener('click', async () => {
                approveBtn.disabled = true;
                try {
                    await api('/api/v1/admin/pending/' + encodeURIComponent(item.id) + '/approve', { method: 'POST' });
                    toast('Мем опубликован', 'success');
                    await loadDashboard();
                } catch (err) {
                    if (err.message !== 'unauthorized') {
                        toast('Не удалось опубликовать: ' + err.message, 'error');
                    }
                    approveBtn.disabled = false;
                }
            });

            const rejectBtn = document.createElement('button');
            rejectBtn.type = 'button';
            rejectBtn.className = 'btn btn-danger';
            rejectBtn.textContent = 'ОТКЛОНИТЬ';
            rejectBtn.addEventListener('click', async () => {
                if (!window.confirm('Отклонить этот мем?')) return;
                rejectBtn.disabled = true;
                try {
                    await api('/api/v1/admin/pending/' + encodeURIComponent(item.id) + '/reject', { method: 'POST' });
                    toast('Мем отклонён', 'success');
                    await loadDashboard();
                } catch (err) {
                    if (err.message !== 'unauthorized') {
                        toast('Не удалось отклонить: ' + err.message, 'error');
                    }
                    rejectBtn.disabled = false;
                }
            });

            actions.append(approveBtn, rejectBtn);
            body.append(name, tags, meta, countdown, actions);
            card.append(img, body);
            el.pendingList.appendChild(card);
        });

        tickCountdowns();
    }

    async function deleteMeme(imageId, button) {
        if (!imageId) return;
        if (!window.confirm('Удалить мем ' + imageId.slice(0, 12) + '… из архива?')) return;
        if (button) button.disabled = true;
        try {
            await api('/api/v1/admin/memes/' + encodeURIComponent(imageId), { method: 'DELETE' });
            toast('Мем удалён', 'success');
            await loadDashboard();
        } catch (err) {
            if (err.message !== 'unauthorized') toast('Не удалось удалить: ' + err.message, 'error');
        } finally {
            if (button) button.disabled = false;
        }
    }

    function renderMemes(items) {
        el.memesList.replaceChildren();
        if (!items.length) {
            const empty = document.createElement('div');
            empty.className = 'empty';
            empty.textContent = 'В архиве пока нет мемов';
            el.memesList.appendChild(empty);
            return;
        }
        items.forEach((item) => {
            const card = document.createElement('article');
            card.className = 'meme-admin';

            const img = document.createElement('img');
            img.loading = 'lazy';
            img.alt = item.original_filename || item.id;
            img.src = '/image/' + encodeURIComponent(item.stored_name);

            const body = document.createElement('div');
            body.className = 'meme-admin-body';

            const title = document.createElement('div');
            title.className = 'meme-admin-title';
            title.textContent = item.original_filename || item.id;

            const open = document.createElement('a');
            open.className = 'btn';
            open.href = '/meme/' + encodeURIComponent(item.id);
            open.textContent = 'ОТКРЫТЬ';

            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'btn btn-danger';
            remove.textContent = 'УДАЛИТЬ';
            remove.addEventListener('click', () => deleteMeme(item.id, remove));

            body.append(title, open, remove);
            card.append(img, body);
            el.memesList.appendChild(card);
        });
    }

    function tickCountdowns() {
        document.querySelectorAll('[data-expires]').forEach((node) => {
            const target = Date.parse(node.dataset.expires || '');
            if (Number.isNaN(target)) return;
            const left = Math.round((target - Date.now()) / 1000);
            node.textContent = left > 0 ? 'осталось ' + formatLeft(left) : 'публикуется...';
        });
    }

    async function loadDashboard() {
        try {
            const [statsRes, pendingRes, memesRes] = await Promise.all([
                api('/api/v1/admin/stats'),
                api('/api/v1/admin/pending'),
                fetch('/images?limit=24&order=new', { cache: 'no-store' })
            ]);
            if (!memesRes.ok) throw new Error(await readError(memesRes));
            const [statsData, pendingData, memesData] = await Promise.all([
                statsRes.json(),
                pendingRes.json(),
                memesRes.json()
            ]);
            renderStats(statsData);
            renderPending(pendingData);
            renderMemes(memesData.results || []);
        } catch (err) {
            if (err.message !== 'unauthorized') toast('Ошибка загрузки: ' + err.message, 'error');
        }
    }

    function startPolling() {
        stopPolling();
        pollTimer = window.setInterval(() => {
            if (!document.hidden) loadDashboard();
        }, POLL_MS);
        countdownTimer = window.setInterval(tickCountdowns, 1000);
    }

    function stopPolling() {
        if (pollTimer) window.clearInterval(pollTimer);
        if (countdownTimer) window.clearInterval(countdownTimer);
        pollTimer = null;
        countdownTimer = null;
    }

    function showPanel() {
        el.loginCard.classList.add('hidden');
        el.panel.classList.remove('hidden');
        el.loginError.classList.add('hidden');
        startPolling();
    }

    function showLogin(message) {
        stopPolling();
        token = '';
        sessionStorage.removeItem(TOKEN_KEY);
        el.panel.classList.add('hidden');
        el.loginCard.classList.remove('hidden');
        if (message) {
            el.loginError.textContent = message;
            el.loginError.classList.remove('hidden');
        }
    }

    async function login(candidate) {
        token = candidate;
        try {
            const res = await fetch('/api/v1/admin/pending', { headers: authHeaders(), cache: 'no-store' });
            if (res.status === 503) throw new Error('ADMIN_TOKEN не задан на сервере.');
            if (res.status === 401) throw new Error('Неверный токен администратора.');
            if (!res.ok) throw new Error(await readError(res));
            sessionStorage.setItem(TOKEN_KEY, token);
            el.tokenInput.value = '';
            showPanel();
            await loadDashboard();
        } catch (err) {
            token = '';
            sessionStorage.removeItem(TOKEN_KEY);
            el.loginError.textContent = err.message;
            el.loginError.classList.remove('hidden');
        }
    }

    el.loginForm.addEventListener('submit', (event) => {
        event.preventDefault();
        const candidate = el.tokenInput.value.trim();
        if (!candidate) {
            el.loginError.textContent = 'Введите токен администратора.';
            el.loginError.classList.remove('hidden');
            return;
        }
        login(candidate);
    });

    el.logoutBtn.addEventListener('click', () => {
        showLogin('');
        el.loginError.classList.add('hidden');
    });

    el.deleteIdBtn.addEventListener('click', () => {
        const imageId = el.deleteId.value.trim();
        if (!imageId) {
            toast('Введите id мема', 'error');
            return;
        }
        deleteMeme(imageId, el.deleteIdBtn).finally(() => {
            el.deleteId.value = '';
        });
    });

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && !el.panel.classList.contains('hidden')) loadDashboard();
    });

    if (token) {
        login(token);
    } else {
        showLogin('');
        el.loginError.classList.add('hidden');
    }
})();
