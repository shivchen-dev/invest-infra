# Playwright + Chromium 安装指南

## 当前问题

1. **Playwright CLI** 不在 PATH → 已修复 ✅
2. **Chromium 浏览器** 未安装 → 需要安装

---

## 快速解决方案

### 步骤1: 添加 Playwright 到 PATH

```bash
export PATH="$HOME/.local/bin:$PATH"
```

永久添加（添加到 ~/.bashrc）:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 步骤2: 安装 Chromium

由于当前环境限制大文件下载，有以下几种方式：

#### 方式A: 系统包管理器（推荐，如果有 sudo）

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y chromium-browser

# 或安装 Chrome
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list'
sudo apt-get update
sudo apt-get install -y google-chrome-stable
```

#### 方式B: Playwright 自动安装（资源充足时）

```bash
export PATH="$HOME/.local/bin:$PATH"
playwright install chromium
```

**注意**: 需要下载 167MB，确保网络稳定和内存充足。

#### 方式C: 手动下载安装

```bash
# 运行安装脚本
cd /home/chenjian/.openclaw/workspace-browser/projects/active/copilot-bridge/scripts
bash install_chromium_light.sh
```

#### 方式D: Docker 方式（推荐用于开发）

```bash
# 拉取包含浏览器的镜像
docker pull mcr.microsoft.com/playwright:v1.40.0-jammy

# 运行容器
docker run -it \
  -v /home/chenjian/.openclaw/workspace-browser:/workspace \
  mcr.microsoft.com/playwright:v1.40.0-jammy \
  bash

# 在容器内
cd /workspace/projects/active/copilot-bridge
cd tests && python3 test_copilot.py basic
```

---

## 验证安装

```bash
# 1. 检查 Playwright
which playwright
playwright --version

# 2. 检查 Chromium
ls -la ~/.cache/ms-playwright/chromium-*/

# 或检查系统 Chromium
which chromium-browser
which google-chrome

# 3. 运行测试
cd /home/chenjian/.openclaw/workspace-browser/projects/active/copilot-bridge/tests
python3 test_copilot.py basic
```

---

## 故障排除

### 错误: `playwright: command not found`

```bash
# 添加 PATH
export PATH="$HOME/.local/bin:$PATH"

# 或重新安装
pip3 install --user playwright
```

### 错误: `Executable doesn't exist`

```bash
# 安装浏览器
playwright install chromium

# 或安装所有浏览器
playwright install
```

### 错误: 下载被中断 (SIGKILL)

系统内存限制导致，尝试：
1. 使用系统包管理器安装 Chromium
2. 使用 Docker 环境
3. 在其他机器安装后复制 `~/.cache/ms-playwright/` 目录

---

## Copilot Bridge 自动检测

Copilot Bridge 已配置自动检测系统 Chromium：

```python
# 会自动查找以下路径
/snap/bin/chromium
/usr/bin/chromium-browser
/usr/bin/chromium
/usr/bin/google-chrome
/usr/bin/google-chrome-stable
```

如果安装了系统 Chromium，无需运行 `playwright install`。
