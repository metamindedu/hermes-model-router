# Plugin-owned routing policy

Keep the routing policy in the native plugin package and reference its namespaced
skill. Settings management must not materialize a second standalone skill in a
profile: copies shadow the package, drift independently and reappear after cleanup.
Package-owned legacy-name discovery may remain an explicit external reference.

Preserve user-authored local additions during explicit cleanup; do not use a settings
save as a migration or deletion trigger. A missing independent skill is not a
settings change. Configuration/effective-state CAS and post-write readback remain
mandatory even when the unrelated local skill file is no longer hashed.

After a write-contract change, reject a persisted pre-upgrade plan that still
includes skill-copy snapshots before any writes, consume its one-shot token and
require a fresh owner-scoped reload/preview. Keep installation, resident callback
activation and catalog maintainer publication as separate verification milestones.
