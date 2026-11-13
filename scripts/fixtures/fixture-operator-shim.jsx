import { atom } from 'nanostores'
export { Badge } from '@/components/ui/badge'
export { Button } from '@/components/ui/button'
export { Checkbox } from '@/components/ui/checkbox'
export { Codicon } from '@/components/ui/codicon'
export { GlyphSpinner } from '@/components/ui/glyph-spinner'
export { Input } from '@/components/ui/input'
export { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
export { useQuery } from '@tanstack/react-query'
export { useStore as useValue } from '@nanostores/react'
export { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
export const SETTINGS_PLUGINS_AREA='settings.plugins', COMPOSER_AREAS={top:'composer.top'}
export const pluginSettingsHref=id=>'/settings?tab=plugins&plugin='+id
export const PALETTE_AREA = 'fixture.palette', ROUTES_AREA = 'fixture.routes'
export const host = {
  state: { focusedSessionOwner: atom({connectionId:'fixture-host-A',profile:'coordinator-alias'}), focusedSessionId:atom('parent-A'),
    connectionId:atom('fixture-host-A'),profile:atom('coordinator-alias'),activeSessionId:atom('parent-A'),gateway:atom('open') },
  profileRoutes: async () => window.fixtureRoutes(),
  requestProfile: async (...args) => window.fixtureRPC(...args),
  retainProfile: async (...args) => window.fixtureRetain(...args),
  openSession: async (...args) => window.fixtureOpen(...args),
  onEvent: () => () => {}, notify: () => {}, logs: () => {}
}
window.fixtureHost=host
