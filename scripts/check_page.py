#!/usr/bin/env python3
import json, urllib.request

data = json.load(urllib.request.urlopen("http://localhost:9222/json"))
for p in data:
    if 'deepseek' in p.get('url', '').lower():
        pid = p.get('id')
        url = f'http://localhost:9222/json/{pid}/evaluate'
        req = urllib.request.Request(url,
            data=json.dumps({'expression': 'document.body.innerText.slice(0,300)'}).encode(),
            headers={'Content-Type': 'application/json'})
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            result = json.loads(resp.read())
            text = result.get('result', {}).get('result', {}).get('value', '')
            print(text)
        except Exception as e:
            print(f'Error: {e}')
        break
