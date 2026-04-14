---
name: bb-browser
description: >
  bb-browser is a CLI tool that controls Chrome via CDP (Chrome DevTools Protocol) to access websites using your existing browser login state — no API keys, no re-login needed.

  Use when needing to:
  - Search or read content from platforms requiring authentication (小红书/知乎/微博/Bilibili/etc.)
  - Scrape content that needs login state
  - Access authenticated pages without cookies/cookie management
  - Fetch real-time data from sites without public APIs

  Prerequisites: Chrome/Chromium running with `--remote-debugging-port=9222` (Playwright launches it automatically).

  Commands: `bb-browser site <platform>/<command> [args]`
---

# bb-browser

Use browser login state without re-authenticating.

## Quick Start

```bash
# 1. Ensure Chrome is running with CDP (Playwright does this automatically)
# 2. Set CDP URL
export BB_BROWSER_CDP_URL=http://localhost:9222

# 3. Use site commands
bb-browser site xiaohongshu/search "关键词"
bb-browser site zhihu/hot
bb-browser site weibo/hot
```

## Core Workflow

1. **Chrome with CDP**: Browser must run with `--remote-debugging-port=9222`
   - Playwright's `launch_persistent_context` + `args=['--remote-debugging-port=9222']` handles this
   - Or start Chrome manually: `google-chrome --remote-debugging-port=9222`

2. **Set CDP URL**: `export BB_BROWSER_CDP_URL=http://localhost:9222`

3. **Run site commands**: `bb-browser site <platform>/<action> [args]`

## Common Commands

| Platform | Command | Description |
|----------|---------|-------------|
| xiaohongshu | `site xiaohongshu/search "query"` | Search notes |
| xiaohongshu | `site xiaohongshu/note <url>` | Get note detail (needs xsec_token) |
| zhihu | `site zhihu/hot` | Hot topics |
| zhihu | `site zhihu/search "query"` | Search questions |
| weibo | `site weibo/hot` | Hot searches |
| bilibili | `site bilibili/search "query"` | Search videos |
| github | `site github/repo owner/repo` | Repo info |
| xueqiu | `site xueqiu/stock SH600519` | Stock quote |

For full platform list: `bb-browser site update` then `bb-browser site recommend`

## Output Formats

```bash
# JSON output (machine readable)
bb-browser site xiaohongshu/search "query" --json

# With jq filter
bb-browser site xueqiu/hot-stock 5 --jq '.items[] | {name, changePercent}'
```

## Key Flags

| Flag | Description |
|------|-------------|
| `--json` | JSON output |
| `--jq '.expr'` | jq filter for JSON output |
| `--cdp http://host:port` | Override CDP URL |
| `--openclaw` | Use OpenClaw's built-in browser (requires gateway pairing) |

## Notes

- Session/token: Some sites (xiaohongshu) require valid `xsec_token` from search results to access individual notes
- Community adapters: `bb-browser site update` pulls latest adapters from `epiral/bb-sites`
- Adapter list: `bb-browser site recommend`
- Supported: 103 commands across 36 platforms

For platform-specific adapter details, see [references/platforms.md](references/platforms.md).
