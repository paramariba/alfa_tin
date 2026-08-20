export type AlfaTeenInvestPage = 'home' | 'market' | 'tin' | 'learn' | 'social' | 'profile'
export type AlfaTeenInvestTheme = 'light' | 'dark'

export interface AlfaTeenInvestInstance {
  readonly element: HTMLIFrameElement
  setToken(token: string): void
  setTheme(theme: AlfaTeenInvestTheme): void
  navigate(page: AlfaTeenInvestPage): void
  refresh(): void
  update(options: Partial<AlfaTeenInvestOptions>): void
  destroy(): void
}

export interface AlfaTeenInvestOptions {
  appUrl?: string
  apiBase?: string
  wsUrl?: string
  accessToken?: string
  token?: string
  theme?: AlfaTeenInvestTheme
  title?: string
  height?: string
  minHeight?: string
  borderRadius?: string
  onReady?(instance: AlfaTeenInvestInstance): void
  onAuthRequired?(payload: Record<string, unknown>, instance: AlfaTeenInvestInstance): void
  onNavigate?(page: AlfaTeenInvestPage, instance: AlfaTeenInvestInstance): void
  onEvent?(name: string, payload: Record<string, unknown>): void
}

export interface AlfaTeenInvestSdk {
  readonly version: string
  readonly protocolVersion: number
  mount(target: string | HTMLElement, options?: AlfaTeenInvestOptions): AlfaTeenInvestInstance
}

declare global {
  interface Window {
    AlfaTeenInvest: AlfaTeenInvestSdk
  }
  const AlfaTeenInvest: AlfaTeenInvestSdk
}

export {}
