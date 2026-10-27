(function () {
    const STORAGE_KEY = 'theme';
    const root = document.documentElement;
    const button = document.getElementById('themeToggle');
    const media = window.matchMedia('(prefers-color-scheme: dark)');

    function resolve() {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored === 'dark' || stored === 'light') return stored;
        return media.matches ? 'dark' : 'light';
    }

    function current() {
        return root.dataset.theme === 'dark' ? 'dark' : 'light';
    }

    function apply(theme) {
        root.dataset.theme = theme;
        if (button) {
            button.innerHTML = theme === 'dark'
                ? '☀ <span class="theme-label">СВЕТЛАЯ</span>'
                : '☾ <span class="theme-label">ТЁМНАЯ</span>';
            button.title = theme === 'dark'
                ? 'Переключить на светлую тему'
                : 'Переключить на тёмную тему';
            button.setAttribute('aria-label', button.title);
        }
    }

    media.addEventListener('change', () => {
        if (!localStorage.getItem(STORAGE_KEY)) {
            apply(resolve());
        }
    });

    if (button) {
        button.addEventListener('click', () => {
            const next = current() === 'dark' ? 'light' : 'dark';
            try {
                localStorage.setItem(STORAGE_KEY, next);
            } catch (err) {
                console.warn('Theme storage unavailable', err);
            }
            apply(next);
        });
    }

    apply(resolve());
})();
