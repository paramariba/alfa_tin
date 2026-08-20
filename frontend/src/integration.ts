export type AlfaTeenTheme = 'light' | 'dark'

export type AlfaTeenRuntimeConfig = {
  apiBase?: string
  wsUrl?: string
  accessToken?: string
  theme?: AlfaTeenTheme
}

type BridgeMessage = {
  channel: 'alfa-teen-invest'
  version: 1
  type: string
  payload?: Record<string, unknown>
}

declare global {
  interface Window {
    __ALFA_TEEN_INVEST_CONFIG__?: AlfaTeenRuntimeConfig
  }
}

export const AUTH_TOKEN_KEY = 'alfa-tin-access-token'
export const PLUGIN_CHANNEL = 'alfa-teen-invest'
export const PLUGIN_PROTOCOL_VERSION = 1

const query = new URLSearchParams(window.location.search)
export const isEmbedded = query.get('embed') === '1'

let parentOrigin = query.get('parentOrigin') || ''
let runtimeConfig: Required<Pick<AlfaTeenRuntimeConfig, 'apiBase'>> & AlfaTeenRuntimeConfig = {
  apiBase: '/api/v1',
  ...(window.__ALFA_TEEN_INVEST_CONFIG__ || {}),
}
let memoryAccessToken = runtimeConfig.accessToken || ''

if (isEmbedded) document.documentElement.dataset.embed = 'true'

function cleanBase(value: string) {
  const trimmed = value.trim()
  return trimmed.length > 1 ? trimmed.replace(/\/$/, '') : trimmed
}

export function configureRuntime(next: AlfaTeenRuntimeConfig = {}) {
  runtimeConfig = {
    ...runtimeConfig,
    ...next,
    apiBase: cleanBase(next.apiBase || runtimeConfig.apiBase || '/api/v1'),
  }
  if (typeof next.accessToken === 'string') memoryAccessToken = next.accessToken
  if (next.theme) applyHostTheme(next.theme)
}

export function getApiUrl(path: string) {
  const suffix = path.startsWith('/') ? path : `/${path}`
  return `${runtimeConfig.apiBase}${suffix}`
}

export function getAccessToken() {
  if (memoryAccessToken) return memoryAccessToken
  if (isEmbedded) return ''
  return localStorage.getItem(AUTH_TOKEN_KEY) || ''
}

export function setAccessToken(token: string, persist = !isEmbedded) {
  memoryAccessToken = token
  if (!persist) return
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token)
  else localStorage.removeItem(AUTH_TOKEN_KEY)
}

export function clearAccessToken() {
  memoryAccessToken = ''
  if (!isEmbedded) localStorage.removeItem(AUTH_TOKEN_KEY)
}

export function getMarketWebSocketUrl() {
  if (runtimeConfig.wsUrl) return runtimeConfig.wsUrl
  if (/^https?:\/\//i.test(runtimeConfig.apiBase)) {
    const api = new URL(runtimeConfig.apiBase)
    return `${api.protocol === 'https:' ? 'wss:' : 'ws:'}//${api.host}/ws/market`
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = import.meta.env.DEV ? `${window.location.hostname}:8000` : window.location.host
  return `${protocol}//${host}/ws/market`
}

export function applyHostTheme(theme: AlfaTeenTheme) {
  document.documentElement.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0f0f11' : '#f5f5f6')
}

export function isTrustedHostMessage(event: MessageEvent): event is MessageEvent<BridgeMessage> {
  if (!isEmbedded || event.source !== window.parent) return false
  if (parentOrigin && event.origin !== parentOrigin) return false
  const message = event.data as Partial<BridgeMessage> | null
  return Boolean(message && message.channel === PLUGIN_CHANNEL && message.version === PLUGIN_PROTOCOL_VERSION && typeof message.type === 'string')
}

export function rememberHostOrigin(origin: string) {
  if (!parentOrigin) parentOrigin = origin
}

export function emitPluginEvent(type: string, payload: Record<string, unknown> = {}) {
  if (!isEmbedded || window.parent === window) return
  const message: BridgeMessage = {channel: PLUGIN_CHANNEL, version: PLUGIN_PROTOCOL_VERSION, type, payload}
  window.parent.postMessage(message, parentOrigin || '*')
}

