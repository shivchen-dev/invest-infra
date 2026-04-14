# Ubuntu 24.04 命令变化

## apt 全面替代 apt-get
```bash
# 安装包
apt install <package>

# 更新
apt update

# 搜索
apt search <keyword>

# 清理
apt autoremove
```

## Docker Compose V2
```bash
# 旧版
docker-compose up -d

# 新版（推荐）
docker compose up -d
```

## Playwright 依赖（Ubuntu 24.04）
```bash
apt install -y \
  libnspr4 libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 \
  libcups2t64 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
  libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
  libasound2t64 libxshmfence1
```

## 中文字体
```bash
apt install -y fonts-noto-cjk
```
