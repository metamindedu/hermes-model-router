# Hermes Model Router
Read PLAN.md before changes. One native Hermes plugin: UI + safe settings backend + gated routing + bundled skill. No Hermes core changes, no secrets in output/repo. No live profile writes from implementation workers. Use supported config CLI for settings. Preserve unrelated state. Unit/integration tests use fake homes and fake subprocesses. Heavy independent final review required before live installation. Never claim model identity from requested flags alone.

## Common PR/CI policy

Small bounded changes do not require a PR when repository protections permit reviewed, approved non-forced default-branch integration. Keep local checks, required independent review, UI preview and publication approval. PRs are optional for larger/parallel/external changes; PR success is not installation or release acceptance. Preserve the complete Windows/Linux regression suites on branch pushes and PRs, but do not repeat them merely for a tag push. Superseded PR runs may be cancelled; branch verification is not automatically cancelled. This CI policy does not authorize plugin installation, profile/config/auth changes, catalog publication or a new release.
