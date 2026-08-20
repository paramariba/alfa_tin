# Интеграция в Альфа‑Инвестиции

Модуль остаётся самостоятельным React/FastAPI-приложением, но production-сборка также содержит готовый загрузчик `alfa-teen-invest-plugin.js`. Загрузчик монтирует приложение в изолированный `iframe`, поэтому CSS, React и остальные зависимости не конфликтуют с хост-приложением.

## Быстрое подключение

```html
<div id="alfa-teen-invest" style="height: 100dvh"></div>
<script src="https://teen-invest.example.ru/alfa-teen-invest-plugin.js"></script>
<script>
  const teenInvest = AlfaTeenInvest.mount('#alfa-teen-invest', {
    appUrl: 'https://teen-invest.example.ru/',
    apiBase: 'https://teen-invest-api.example.ru/api/v1',
    wsUrl: 'wss://teen-invest-api.example.ru/ws/market',
    accessToken: moduleAccessToken,
    theme: 'light',
    onAuthRequired() {
      // Получить/обновить токен, который принимает backend модуля, затем:
      // teenInvest.setToken(newToken)
    },
    onNavigate(page) {
      console.log('Активный раздел модуля:', page)
    }
  })
```

Токен передаётся только через `postMessage` после handshake и не попадает в URL, историю браузера или referrer. Сообщения проверяются по `window`, origin, имени канала и версии протокола.

Сейчас backend принимает собственный JWT временной регистрации. Если `accessToken` не передан, внутри iframe останется работающий экран входа/регистрации. При подключении Alfa ID хост должен передавать токен после обмена/валидации на backend — интерфейс SDK менять не потребуется.

## API экземпляра

```js
teenInvest.setToken(newToken)
teenInvest.setTheme('dark')
teenInvest.navigate('tin') // home | market | tin | learn | social | profile
teenInvest.refresh()
teenInvest.update({apiBase, wsUrl, accessToken, theme})
teenInvest.destroy()
```

Контейнер также получает DOM-события:

- `alfa-teen-invest:plugin-ready`;
- `alfa-teen-invest:plugin-initialized`;
- `alfa-teen-invest:auth-required`;
- `alfa-teen-invest:authenticated`;
- `alfa-teen-invest:route-changed`.

## Backend и CORS

Если UI модуля и API расположены на разных origin, перечислите доверенные хосты через запятую:

```env
CORS_ALLOWED_ORIGINS=https://invest.alfabank.ru,https://mobile-shell.alfabank.ru
```

Значение `*` намеренно игнорируется, поскольку модуль передаёт авторизационный токен. Для production необходимо использовать точные HTTPS-origin.

В конфигурации reverse proxy также нужно разрешить встраивание только доверенному приложению, например `Content-Security-Policy: frame-ancestors https://invest.alfabank.ru`. Не используйте одновременно запрещающий `X-Frame-Options: DENY`.

## Режимы работы

- Обычный URL `/` — самостоятельное PWA с регистрацией, темой, desktop sidebar и текущим `start.sh`.
- URL `/?embed=1&parentOrigin=...` — режим хост-приложения: без desktop-оболочки и собственной кнопки темы, с полноразмерным адаптивным интерфейсом.
- В embed-режиме service worker не регистрируется, поэтому модуль не вмешивается в кеш хост-приложения.

Для проверки SDK после `npm run build` загрузчик находится в `frontend/dist/alfa-teen-invest-plugin.js`.
