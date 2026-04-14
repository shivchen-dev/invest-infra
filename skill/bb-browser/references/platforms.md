# Supported Platforms

Full list: 103 commands across 36 platforms. Run `bb-browser site update` for latest.

## Search Platforms
```
bb-browser site google/search "query"
bb-browser site baidu/search "query"
bb-browser site zhihu/search "query"
bb-browser site weibo/search "query"
bb-browser site xiaohongshu/search "query"
bb-browser site reddit/search "query"
```

## News & Finance
```
bb-browser site zhihu/hot                    # Hot topics
bb-browser site weibo/hot                   # Hot searches
bb-browser site xueqiu/stock SH600519       # Stock quote
bb-browser site xueqiu/hot-stock 5         # Hot stocks
bb-browser site eastmoney/stock "茅台"       # Stock data
bb-browser site 36kr/newsflash              # News flash
```

## Video
```
bb-browser site youtube/search "query"
bb-browser site bilibili/search "query"
bb-browser site bilibili/video BVxxxxx
```

## Social
```
bb-browser site xiaohongshu/search "query"
bb-browser site xiaohongshu/note <url>      # Needs xsec_token
bb-browser site jike/search "query"
```

## Dev
```
bb-browser site github/repo owner/repo
bb-browser site github/issues owner/repo
bb-browser site hackernews/top 10
bb-browser site stackoverflow/search "query"
bb-browser site arxiv/search "transformer"
```

## Knowledge
```
bb-browser site wikipedia/summary "Python"
```

## Xiaohongshu Note Access

The `xiaohongshu/note` command needs a full URL with valid `xsec_token`:

1. First search to get note with token:
   ```bash
   bb-browser site xiaohongshu/search "关键词" --json
   ```
2. Copy the `url` field (includes `xsec_token`)
3. Pass full URL to note command:
   ```bash
   bb-browser site xiaohongshu/note "<full_url_with_token>" --json
   ```

If note fails with "Note detail not loaded", the note is deleted/restricted.
