<!-- OPENWIKI:START -->

## OpenWiki

This repository has a generated `openwiki/` evidence index. It is optional just-in-time context, not required startup reading.

- Treat source code and tests as authoritative. A brief's unknowns and review items are verification gaps, not automatic requirements.
- Prefer the narrowest quiet validation that proves the changed behavior. Preserve complete failure output.
- Treat `docs/plan/README.md` as the plan-governance authority: JiuwenSwarm is retired and may appear only as historical compatibility, never as a current production path, task route, dependency, or acceptance gate.
- Keep `openwiki/quickstart.md` concise and navigational. Put implementation detail in the relevant concept page instead of duplicating it in Quickstart.
- Resolve repository-file links from the generated page location, and do not publish any page containing an `openwiki: broken internal link` marker.

The scheduled OpenWiki GitHub Actions workflow refreshes the repository wiki. Do not hand-edit generated OpenWiki pages unless explicitly asked; prefer updating source code/docs and letting OpenWiki regenerate.

<!-- OPENWIKI:END -->
