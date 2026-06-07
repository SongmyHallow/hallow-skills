#!/usr/bin/env python3
"""
游戏横纵分析报告 Markdown → HTML 转换脚本
用法: python md_to_html.py input.md output.html
依赖: pip install markdown --break-system-packages
"""

import sys
import re
import markdown

CSS = """\
/* ── GeekDreamer 暗色主题 ── */
:root {
    --bg: #1a1a2e;
    --bg-card: #16213e;
    --bg-code: #0f3460;
    --text: #e0d8c8;
    --text-dim: #a09880;
    --accent: #e94560;
    --accent2: #f0a050;
    --link: #53a8b6;
    --border: #2a2a4a;
    --h1: #e94560;
    --h2: #f0a050;
    --h3: #53a8b6;
    --quote-border: #e94560;
    --table-head: #0f3460;
    --table-stripe: rgba(233, 69, 96, 0.06);
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    background: var(--bg);
    color: var(--text);
    font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", sans-serif;
    font-size: 17px;
    line-height: 1.9;
    -webkit-font-smoothing: antialiased;
}

.container {
    max-width: 750px;
    margin: 0 auto;
    padding: 40px 24px 80px;
}

/* ── 封面区域 ── */
.cover {
    text-align: center;
    padding: 80px 0 60px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 50px;
}
.cover h1 {
    font-size: 2.4em;
    color: var(--h1);
    line-height: 1.3;
    margin-bottom: 16px;
    letter-spacing: 0.04em;
}
.cover .subtitle {
    font-size: 1.05em;
    color: var(--text-dim);
    margin-bottom: 8px;
}
.cover .date {
    font-size: 0.9em;
    color: var(--text-dim);
    opacity: 0.6;
}

/* ── 排版 ── */
h1 { font-size: 1.7em; color: var(--h1); margin: 50px 0 20px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
h2 { font-size: 1.35em; color: var(--h2); margin: 40px 0 16px; }
h3 { font-size: 1.1em; color: var(--h3); margin: 28px 0 12px; }

p { margin: 0 0 1.2em; }
a { color: var(--link); text-decoration: none; border-bottom: 1px dotted var(--link); }
a:hover { color: var(--accent); border-bottom-color: var(--accent); }

strong { color: #fff; font-weight: 600; }

blockquote {
    margin: 1.4em 0;
    padding: 12px 20px;
    border-left: 3px solid var(--quote-border);
    background: rgba(233, 69, 96, 0.06);
    border-radius: 0 6px 6px 0;
}
blockquote p { margin-bottom: 0.5em; }

hr { border: none; border-top: 1px solid var(--border); margin: 40px 0; }

/* ── 列表 ── */
ul, ol { margin: 0 0 1.2em; padding-left: 1.5em; }
li { margin-bottom: 0.35em; }

/* ── 表格 ── */
table {
    width: 100%;
    border-collapse: collapse;
    margin: 1.4em 0;
    font-size: 0.92em;
}
thead th {
    background: var(--table-head);
    color: #fff;
    padding: 10px 14px;
    text-align: left;
    font-weight: 600;
}
tbody td {
    padding: 9px 14px;
    border-bottom: 1px solid var(--border);
}
tbody tr:nth-child(even) { background: var(--table-stripe); }

/* ── 代码 ── */
code {
    background: var(--bg-code);
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 0.88em;
    color: var(--accent2);
}
pre {
    background: var(--bg-code);
    padding: 16px 20px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 1.4em 0;
    line-height: 1.5;
}
pre code { color: var(--text); padding: 0; background: none; }

/* ── 来源区块 ── */
.sources {
    margin-top: 60px;
    padding-top: 30px;
    border-top: 1px solid var(--border);
}
.sources h2 { color: var(--text-dim); font-size: 1.1em; }
.sources ul { list-style: none; padding-left: 0; }
.sources li { font-size: 0.88em; color: var(--text-dim); margin-bottom: 6px; }

/* ── 响应式 ── */
@media (max-width: 600px) {
    .container { padding: 20px 16px 60px; }
    .cover { padding: 50px 0 40px; }
    .cover h1 { font-size: 1.6em; }
    body { font-size: 15px; }
}
"""


def convert_md_to_html(md_text: str) -> str:
    """将 Markdown 文本转为完整的自包含 HTML 页面"""

    # 提取第一个 H1 作为封面标题
    title_match = re.search(r'^#\s+(.+)$', md_text, re.MULTILINE)
    title = title_match.group(1) if title_match else "游戏分析报告"

    # 去掉第一个 H1（放到封面用），后续 H1 降级
    if title_match:
        md_text = md_text[:title_match.start()] + md_text[title_match.end():]
    # 所有 # 降一级让封面标题是唯一的 h1
    # ## → h2, ### → h3 保持不变（markdown 库自动处理），但我们删掉了 # 开头
    # 现在剩余的 ## 会变成新的顶级标题，在正文里用 h2-h4 即可

    md = markdown.Markdown(extensions=['tables', 'fenced_code', 'codehilite', 'toc'])
    body_html = md.convert(md_text)

    # 检测元信息行（紧跟在原标题后的 > 引用）
    date_str = ""
    date_match = re.search(r'<p>(?:研究时间|分析日期)[：:]\s*(.+?)</p>', body_html)
    if date_match:
        date_str = date_match.group(1)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — 游戏横纵深度分析</title>
<style>
{CSS}
</style>
</head>
<body>
<div class="container">

<div class="cover">
    <h1>{title}</h1>
    <p class="subtitle">游戏横纵深度分析报告</p>
    <p class="date">GeekDreamer · {date_str or '深度分析'}</p>
</div>

{body_html}

<div class="sources">
    <p style="text-align:center;color:var(--text-dim);opacity:0.5;margin-top:40px;font-size:0.85em;">
        —— GeekDreamer ——<br>
        横纵分析法游戏深度研究
    </p>
</div>

</div>
</body>
</html>"""

    # 后处理：增强可读性
    html = html.replace('<table>', '<div style="overflow-x:auto;"><table>')
    html = html.replace('</table>', '</table></div>')

    return html


def main():
    if len(sys.argv) < 3:
        print("用法: python md_to_html.py input.md output.html")
        print("依赖: pip install markdown --break-system-packages")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    with open(input_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    html = convert_md_to_html(md_text)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"[OK] HTML report generated: {output_path}")


if __name__ == '__main__':
    main()
