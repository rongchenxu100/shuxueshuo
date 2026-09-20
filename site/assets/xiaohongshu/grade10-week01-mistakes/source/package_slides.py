from pathlib import Path
import json
import html
import zipfile

p = Path(__file__).resolve().parent.parent
m = json.loads((p/'source/slide-manifest.json').read_text())
titles = ['封面','二次项系数','集合元素','边界代入验证','维恩图','任意与反例','包含关系中的空集','充分与必要','理解题意 · 自测']
figures = ''.join(
    f'<figure><a href="{s["png"]}" target="_blank"><img src="{s["png"]}" width="1080" height="1440" alt="{html.escape(t)}"></a><figcaption>{i:02d} · {t}　<a href="{s["png"]}" download>下载</a></figcaption></figure>'
    for i,(s,t) in enumerate(zip(m['slides'],titles),1)
)
(p/'index.html').write_text('''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>高一第一周错题复盘 · 小红书图片</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f4ec;color:#123d43;font:16px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}
header{max-width:1200px;margin:40px auto 30px;padding:0 20px}h1{font-size:30px;margin-bottom:8px}a{color:#087e77;text-underline-offset:4px}
nav{display:flex;gap:24px;flex-wrap:wrap}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),360px));gap:30px;max-width:1200px;margin:auto;padding:0 12px 50px;justify-content:center}
figure{margin:0}img{display:block;width:100%;height:auto;border-radius:8px;box-shadow:0 4px 20px #123d4312}figcaption{padding:12px 4px;font-size:15px}
</style>
<header><h1>高一第一周错题复盘</h1><p>9张 · 封面＋8类代表题 · 1080×1440 PNG<br>点击图片看原图。最后一张为自测，未标正确选项。</p>
<nav><a href="grade10-week01-images.zip" download>下载整套图片与文案</a><a href="post-copy.md">发布文案</a><a href="source/slide-manifest.json">SVG源文件清单</a></nav></header>
<main>'''+figures+'</main></html>',encoding='utf-8')
with zipfile.ZipFile(p/'grade10-week01-images.zip','w',zipfile.ZIP_DEFLATED) as z:
    for s in m['slides']:
        z.write(p/s['png'],s['png'])
    z.write(p/'post-copy.md','post-copy.md')
print('Preview and ZIP ready')
