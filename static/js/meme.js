const imageId = decodeURIComponent(
            window.location.pathname.split('/').filter(Boolean).pop() || ''
        );

        const el = {
            loading: document.getElementById('loading'),
            error: document.getElementById('error'),
            meme: document.getElementById('meme'),
            image: document.getElementById('memeImage'),
            title: document.getElementById('title'),
            description: document.getElementById('description'),
            tags: document.getElementById('tags'),
            meta: document.getElementById('meta'),
            copyBtn: document.getElementById('copyBtn'),
            downloadBtn: document.getElementById('downloadBtn'),
            deleteBtn: document.getElementById('deleteBtn'),
            toasts: document.getElementById('toasts')
        };

        let item = null;

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

        function formatBytes(bytes) {
            if (typeof bytes !== 'number' || bytes < 0) return '—';
            if (bytes < 1024) return bytes + ' Б';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' КБ';
            return (bytes / (1024 * 1024)).toFixed(2) + ' МБ';
        }

        function formatDate(value) {
            if (!value) return '—';
            const date = new Date(value);
            if (Number.isNaN(date.getTime())) return value;
            return date.toLocaleString('ru-RU');
        }

        function addMeta(label, value) {
            const dt = document.createElement('dt');
            dt.textContent = label;
            const dd = document.createElement('dd');
            dd.textContent = value || '—';
            el.meta.appendChild(dt);
            el.meta.appendChild(dd);
        }

        function renderTags(tags) {
            el.tags.innerHTML = '';
            (tags || []).forEach((tag) => {
                const link = document.createElement('a');
                link.className = 'meme-tag';
                link.href = '/?query=' + encodeURIComponent(tag);
                link.textContent = '#' + tag;
                el.tags.appendChild(link);
            });
        }

        function render() {
            document.title = (item.original_filename || 'Мем') + ' — Meme Archive';
            el.title.textContent = item.original_filename || 'Мем';
            el.image.src = '/image/' + encodeURIComponent(item.stored_name || '');
            el.image.alt = item.description || 'Мем';
            el.description.textContent = item.description || 'Описание отсутствует.';

            renderTags(item.tags);

            const dimensions = item.width && item.height
                ? `${item.width} × ${item.height} px`
                : '—';

            el.meta.innerHTML = '';
            addMeta('ID', item.id);
            addMeta('Файл', item.original_filename);
            addMeta('Разрешение', dimensions);
            addMeta('Размер', formatBytes(item.size));
            addMeta('Тип', item.mime_type);
            addMeta('Хеш SHA-256', item.content_hash);
            addMeta('Добавлен', formatDate(item.created_at));

            el.loading.classList.add('hidden');
            el.error.classList.add('hidden');
            el.meme.classList.remove('hidden');
        }

        function fail(message) {
            el.loading.classList.add('hidden');
            el.meme.classList.add('hidden');
            el.error.textContent = message;
            el.error.classList.remove('hidden');
        }

        async function load() {
            if (!imageId) {
                fail('Не указан идентификатор мема.');
                return;
            }
            try {
                const res = await fetch('/images/' + encodeURIComponent(imageId));
                if (!res.ok) throw new Error(await readError(res));
                item = await res.json();
                render();
            } catch (err) {
                console.error('Load error', err);
                fail('Не удалось загрузить мем: ' + err.message);
            }
        }

        el.copyBtn.addEventListener('click', async () => {
            if (!item) return;
            try {
                if (!el.image.complete || el.image.naturalWidth === 0) {
                    await new Promise((resolve, reject) => {
                        el.image.onload = resolve;
                        el.image.onerror = reject;
                    });
                }

                if (navigator.clipboard && window.ClipboardItem && 'toBlob' in HTMLCanvasElement.prototype) {
                    const canvas = document.createElement('canvas');
                    canvas.width = el.image.naturalWidth;
                    canvas.height = el.image.naturalHeight;
                    canvas.getContext('2d').drawImage(el.image, 0, 0);
                    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
                    if (!blob) throw new Error('Canvas toBlob failed');
                    await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
                    toast('Изображение скопировано', 'success');
                    return;
                }

                await navigator.clipboard.writeText(el.image.src);
                toast('Скопирована ссылка на изображение', 'success');
            } catch (err) {
                console.warn('Copy failed:', err);
                try {
                    await navigator.clipboard.writeText(el.image.src);
                    toast('Скопирована ссылка на изображение', 'success');
                } catch (fallbackErr) {
                    toast('Не удалось скопировать', 'error');
                }
            }
        });

        el.downloadBtn.addEventListener('click', () => {
            if (!item) return;
            const anchor = document.createElement('a');
            anchor.href = el.image.src;
            anchor.download = item.original_filename || item.stored_name || 'meme.jpg';
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
        });

        el.deleteBtn.addEventListener('click', async () => {
            if (!item) return;
            if (!confirm('Удалить этот мем из архива?')) return;
            el.deleteBtn.disabled = true;
            try {
                const res = await fetch('/images/' + encodeURIComponent(item.id), { method: 'DELETE' });
                if (!res.ok) throw new Error(await readError(res));
                window.location.href = '/';
            } catch (err) {
                toast('Не удалось удалить: ' + err.message, 'error');
                el.deleteBtn.disabled = false;
            }
        });

        load();
