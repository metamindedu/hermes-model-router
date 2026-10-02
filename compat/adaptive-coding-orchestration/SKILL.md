---
name: adaptive-coding-orchestration
description: Use for coding or complex non-coding judgment.
version: 1.0.0
---

# Adaptive Coding Orchestration

This compatibility entry covers coding and complex non-coding judgment (ambiguous evidence, consequential content errors or repeated conceptual failure), not routine writing/extraction. It preserves the existing slash name. The canonical policy and executable routing are owned by the **model-router** plugin.

1. Load `skill_view(name="model-router:adaptive-coding-orchestration")`.
2. Query `coding_route(action="config")` (discover the tool if deferred).
3. Follow the bundled policy. Model IDs, Heavy/Light links, fallback consent and routing-enabled profiles come from the plugin, not this file or a BAT.

If the profile's routing is disabled or the plugin is unavailable, do not invoke legacy scripts or change global settings to bypass it. Continue only safe local work; report any required Heavy review unmet. Plugin Python tools may require a new session after activation.

High-risk semantic final review and explicit independent final review require Heavy; Light preliminary review is never a substitute. An independent review is a fresh child, not Heavy Main's own opinion. Native delegate_task does not upgrade its model because its prompt says "review".
