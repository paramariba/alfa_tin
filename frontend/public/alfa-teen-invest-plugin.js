(function (global) {
  'use strict'

  var CHANNEL = 'alfa-teen-invest'
  var VERSION = 1
  var scriptUrl = document.currentScript && document.currentScript.src
  var defaultAppUrl = scriptUrl ? new URL('./', scriptUrl).toString() : global.location.origin + '/'

  function resolveTarget(target) {
    var element = typeof target === 'string' ? document.querySelector(target) : target
    if (!element) throw new Error('AlfaTeenInvest: контейнер для плагина не найден')
    return element
  }

  function mount(target, options) {
    options = options || {}
    var container = resolveTarget(target)
    var appUrl = new URL(options.appUrl || defaultAppUrl, global.location.href)
    appUrl.searchParams.set('embed', '1')
    appUrl.searchParams.set('parentOrigin', global.location.origin)

    var frame = document.createElement('iframe')
    frame.src = appUrl.toString()
    frame.title = options.title || 'Альфа Тин'
    frame.setAttribute('allow', 'clipboard-write')
    frame.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin')
    frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox')
    frame.style.display = 'block'
    frame.style.width = '100%'
    frame.style.height = options.height || '100%'
    frame.style.minHeight = options.minHeight || '640px'
    frame.style.border = '0'
    frame.style.background = 'transparent'
    frame.style.borderRadius = options.borderRadius || '0'

    var destroyed = false
    var ready = false
    var config = {
      accessToken: options.accessToken || options.token || '',
      apiBase: options.apiBase || '',
      wsUrl: options.wsUrl || '',
      theme: options.theme || 'light'
    }

    function send(type, payload) {
      if (destroyed || !frame.contentWindow) return
      frame.contentWindow.postMessage({channel: CHANNEL, version: VERSION, type: type, payload: payload || {}}, appUrl.origin)
    }

    function sendInit() {
      send('HOST_INIT', config)
    }

    function emit(name, payload) {
      var event = new CustomEvent('alfa-teen-invest:' + name.toLowerCase().replace(/_/g, '-'), {detail: payload || {}})
      container.dispatchEvent(event)
      if (typeof options.onEvent === 'function') options.onEvent(name, payload || {})
    }

    function onMessage(event) {
      if (destroyed || event.source !== frame.contentWindow || event.origin !== appUrl.origin) return
      var message = event.data || {}
      if (message.channel !== CHANNEL || message.version !== VERSION) return
      var payload = message.payload || {}
      if (message.type === 'PLUGIN_READY') {
        ready = true
        sendInit()
        if (typeof options.onReady === 'function') options.onReady(api)
      } else if (message.type === 'AUTH_REQUIRED' && typeof options.onAuthRequired === 'function') {
        options.onAuthRequired(payload, api)
      } else if (message.type === 'ROUTE_CHANGED' && typeof options.onNavigate === 'function') {
        options.onNavigate(payload.page, api)
      }
      emit(message.type, payload)
    }

    global.addEventListener('message', onMessage)
    frame.addEventListener('load', function () { if (ready) sendInit() })
    container.appendChild(frame)

    var api = {
      element: frame,
      setToken: function (token) {
        config.accessToken = token || ''
        send('HOST_SET_TOKEN', {accessToken: config.accessToken})
      },
      setTheme: function (theme) {
        config.theme = theme === 'dark' ? 'dark' : 'light'
        send('HOST_SET_THEME', {theme: config.theme})
      },
      navigate: function (page) { send('HOST_NAVIGATE', {page: page}) },
      refresh: function () { send('HOST_REFRESH') },
      update: function (next) {
        next = next || {}
        if (Object.prototype.hasOwnProperty.call(next, 'accessToken') || Object.prototype.hasOwnProperty.call(next, 'token')) config.accessToken = next.accessToken || next.token || ''
        if (next.apiBase) config.apiBase = next.apiBase
        if (next.wsUrl) config.wsUrl = next.wsUrl
        if (next.theme) config.theme = next.theme
        sendInit()
      },
      destroy: function () {
        if (destroyed) return
        destroyed = true
        global.removeEventListener('message', onMessage)
        frame.remove()
      }
    }

    return api
  }

  global.AlfaTeenInvest = {mount: mount, version: '1.0.0', protocolVersion: VERSION}
})(window)
