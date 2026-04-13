# TOOLS.md - Local Notes

## QMD - 本地文档搜索

- 安装：`npm install -g @tobilu/qmd`
- Collection：`workspace-memory` → `/home/claw/.openclaw/workspace/memory`
- 模型缓存：`~/.cache/qmd/models/`
- 命令：
  - `qmd search "关键词" -c workspace-memory`（全文搜索）
  - `qmd query "语义查询" -c workspace-memory`（混合搜索，CPU 慢）
  - `qmd vsearch "查询" -c workspace-memory`（向量搜索）
  - `qmd get qmd://workspace-memory/path/to/file.md`（获取文档）
- Context：`qmd://workspace-memory` → "Arc的双层记忆系统：热缓存MEMORY.md + 深度存储memory/目录，含人物档案、术语表、每日日志"
- 注意：CPU 模式每次查询约 8-12 秒

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.
