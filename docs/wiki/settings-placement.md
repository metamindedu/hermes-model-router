# Native plugin settings placement

Plugin preferences belong in **Settings → Plugins**, not a main-sidebar task page. The operator chose this convention for both Telegram Bridge and Models and routing. A placement change must preserve the existing page/context and scoped save/CAS semantics; navigation is not permission to change models, membership, fallback, Fast or runtime budgets.

Keep the old workspace route only as an unadvertised compatibility alias, retarget the command palette and remove the main-sidebar contribution. Use public registration and deep links, including the documented low-level settings contribution on older SDKs; never add a private core override or silently restore the old sidebar.

App-wide Desktop materialization uses the default package source: changing a named-profile copy alone does not prove operating activation. Preserve baseline declarations, user settings and original metadata; distinguish deployed files, native menu/renderer observation and official catalog admission. See [[profile-boundaries]] and [[index]].
