# Зарубежный кэширующий прокси для картинок

Telegram-серверы не могут скачать изображения с российского origin
`memearchive.potatom.net`, поэтому бот отдаёт им ссылки на отдельный домен
`images.memearchive.potatom.net`. Этот домен указывает на зарубежный VPS
(сейчас `213.21.250.110`) и кэширует изображения из origin.

## DNS

```
images.memearchive.potatom.net A 213.21.250.110
```

Запись должна быть **DNS only** (серое облако). Если включить прокси Cloudflare,
вернутся обрывы больших изображений.

## Установка на VPS

1. Скопировать `meme_images_cache.conf` в `/etc/nginx/conf.d/`.
2. Скопировать `images.memearchive.potatom.net.conf` в
   `/etc/nginx/sites-available/` и включить:

   ```bash
   ln -s /etc/nginx/sites-available/images.memearchive.potatom.net.conf \
         /etc/nginx/sites-enabled/images.memearchive.potatom.net.conf
   ```

3. Выпустить сертификат и включить HTTPS:

   ```bash
   certbot --nginx -d images.memearchive.potatom.net \
           --non-interactive --agree-tos --redirect
   ```

4. Проверить и перезагрузить nginx:

   ```bash
   nginx -t && systemctl reload nginx
   ```

## Проверка

```bash
curl -sSI https://images.memearchive.potatom.net/image/<file>.jpg
```

Ожидается `200`, корректный `Content-Type` и заголовок `X-Cache-Status`.
Первый запрос — `MISS`, повторный — `HIT`.

## Бот

В `.env` бота:

```
IMAGE_BASE_URL=https://images.memearchive.potatom.net
```
