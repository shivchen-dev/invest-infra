---
name: memory-audit-guardian
description: Weekly memory governance audit for OpenClaw. Use when user asks to audit/optimize memory quality, reduce token overhead, verify MEMORY/TOOLS/AGENTS role boundaries, validate QMD routing quality, or run a periodic memory health check.
---

# Memory Audit Guardian

Run a structured memory-system audit and output a weekly report.

## Audit Scope

1. **File-role boundaries**
   - SOUL: persona only
   - USER: user profile only
   - MEMORY: durable facts + 热锚点（只存"去哪找"）
   - daily memory: event logs
   - TOOLS: execution rules
   - AGENTS: governance/policy

2. **Size & token budget**
   - Check core files against blueprint standards

3. **热锚点分层设计合规性**
   - Verify MEMORY.md only contains "去哪找"
   - Check detailed configs are in proper locations

## Procedure
1. Read core files: SOUL.md, USER.md, MEMORY.md, TOOLS.md, AGENTS.md
2. Compare against blueprint standards
3. Detect: size issues, duplication, role-boundary violations
4. Produce report: score (A/B/C), risks, fixes
   - Report path: `memory/audits/memory-audit-YYYY-WW.md`

## Output
- Executive summary (5 lines max)
- Findings: role-boundary issues, size risks, routing issues
- Action plan for this week
