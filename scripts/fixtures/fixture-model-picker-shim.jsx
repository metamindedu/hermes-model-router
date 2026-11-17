// Fixture-only SDK surface: real native leaf controls and the real catalog menu;
// host state, transport, profile data and the model inventory are invented.
import { atom } from 'nanostores'
export { Badge } from '@/components/ui/badge'
export { Button } from '@/components/ui/button'
export { Checkbox } from '@/components/ui/checkbox'
export { Codicon } from '@/components/ui/codicon'
export { GlyphSpinner } from '@/components/ui/glyph-spinner'
export { Input } from '@/components/ui/input'
export { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
export { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
export { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
export { ModelCatalogMenu, ModelMenuCloseContext } from '@/app/shell/model-catalog-menu'
export { useQuery } from '@tanstack/react-query'
export { useStore as useValue } from '@nanostores/react'
export const SETTINGS_PLUGINS_AREA = 'settings.plugins', COMPOSER_AREAS = { top: 'composer.top' }
export const pluginSettingsHref = id => '/settings?tab=plugins&plugin=' + id
export const PALETTE_AREA = 'fixture.palette', ROUTES_AREA = 'fixture.routes'
export const host = {
  state: { connectionId: atom('local'), profile: atom('default'), gateway: atom('open') },
  request: async (...args) => window.fixtureRequest(...args),
  profileRoutes: async () => window.fixtureRoutes(),
  requestProfile: async (...args) => window.fixtureRequestProfile(...args),
  onEvent: () => () => {}, notify: () => {}, logs: () => {}, navigate: () => {}
}
window.fixtureHost = host
