# Playwright + Chromium 安装指南

## 环境要求

- Playwright (Node.js)
- Chromium 浏览器
- Node.js 环境

---

## 安装步骤

### 步骤1: 安装 Playwright

```bash
npm install -g playwright
# 或
pip3 install playwright
```

### 步骤2: 安装 Chromium

```bash
playwright install chromium
```

> 注意：需要下载约 167MB，确保网络稳定。

### 步骤3: 验证安装

```bash
playwright --version
ls ~/.cache/ms-playwright/chromium-*/
```

---

## 系统 Chromium 备选

如果 Playwright 自动安装失败，可使用系统包管理器：

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y chromium-browser
```

---

## 故障排除

### 错误: `playwright: command not found`

```bash
export PATH="$HOME/.local/bin:$PATH"
# 或重新安装
npm install -g playwright
```

### 错误: `Executable doesn't exist`

```bash
playwright install chromium
```

### 错误: 下载被中断 (SIGKILL)

系统内存限制导致，尝试：
1. 使用系统包管理器安装 Chromium
2. 在其他机器安装后复制 `~/.cache/ms-playwright/` 目录

---

## 自动检测

agent-bridge 自动检测系统 Chromium：

```python
# 自动查找以下路径
/snap/bin/chromium
/usr/bin/chromium-browser
/usr/bin/chromium
/usr/bin/google-chrome
/usr/bin/google-chrome-stable
```

---

*2026-04-16*
