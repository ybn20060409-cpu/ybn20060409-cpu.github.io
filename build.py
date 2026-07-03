#!/usr/bin/env python3
"""
blog-v2 Static Site Builder — v4
=================================
朝暮集 — 文章与诗歌双内容静态站点生成器。
Features: 全新首页 (搜索+标签云+封面卡片入口), 文章/诗歌封面卡片列表,
          分区卡片化关于页, 增强星空 (80颗小星星+30颗中星星+3颗流星),
          TOC, reading time, OG tags, structured data, sitemap, RSS.
Usage: python build.py
"""

import json, shutil, sys, io, re, random, hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from email.utils import format_datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "posts"
POEMS_DIR = ROOT / "poems"
PAGES_DIR = ROOT / "pages"
SRC_DIR = ROOT / "src"
OUT_DIR = ROOT / "public"
OUT_POSTS_DIR = OUT_DIR / "post"
OUT_POEMS_DIR = OUT_DIR / "poem"
OUT_ARTICLES_DIR = OUT_DIR / "articles"
OUT_POETRY_DIR = OUT_DIR / "poetry"

# ── Dependencies ────────────────────────────────────────────────────────────
def _ensure_markdown():
    try:
        import markdown  # noqa: F401
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "markdown"])
_ensure_markdown()
import markdown

# ── Helpers ─────────────────────────────────────────────────────────────────
def load_json(p): return json.loads(Path(p).read_text(encoding="utf-8"))

def parse_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = 1
    while end < len(lines) and lines[end].strip() != "---":
        end += 1
    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1:])
    meta: dict = {}
    cur = None
    for line in fm_lines:
        s = line.rstrip()
        if cur and s.strip().startswith("- "):
            v = s.strip()[2:].strip().strip('"').strip("'")
            if isinstance(meta.get(cur), list):
                meta[cur].append(v)
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if v.startswith("[") and v.endswith("]"):
                meta[k] = [i.strip().strip('"').strip("'") for i in v[1:-1].split(",") if i.strip()]
                cur = k
            else:
                meta[k] = v.strip('"').strip("'")
                cur = k
    return meta, body

def md_to_html(md_text: str) -> str:
    return markdown.markdown(md_text, extensions=["extra", "codehilite", "tables", "fenced_code"])

def rfc2822(d: str) -> str:
    try:
        dt = datetime.fromisoformat(d)
    except ValueError:
        dt = datetime.strptime(d, "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt, usegmt=True)

def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def word_count(md: str) -> int:
    """Count Chinese chars + English words."""
    text = re.sub(r"<[^>]+>", "", md)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"[`*_~>#\[\]\(\)\-|!]", " ", text)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[a-zA-Z]+", text))
    return cjk + en

def reading_time(md: str) -> int:
    """Minutes to read (300 chars/min)."""
    wc = word_count(md)
    return max(1, round(wc / 300))

def extract_headings(html: str) -> list[dict]:
    """Extract h2/h3 headings with ids from HTML for TOC."""
    headings = []
    for m in re.finditer(r'<h([23])(?:\s+id="([^"]*)")?[^>]*>(.*?)</h\1>', html):
        level = int(m.group(1))
        id_ = m.group(2) or ""
        text = re.sub(r"<[^>]+>", "", m.group(3))
        headings.append({"level": level, "id": id_, "text": text})
    return headings

def add_heading_ids(html: str) -> str:
    """Add id attributes to h2/h3 for TOC linking."""
    def _replacer(m):
        level = m.group(1)
        text = m.group(2)
        slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text.strip()).strip("-").lower() or "section"
        return f'<h{level} id="{slug}">{text}</h{level}>'
    return re.sub(r"<h([23])>(.*?)</h\1>", _replacer, html)

def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ── Cover Gradients ─────────────────────────────────────────────────────────
def generate_cover_gradient(title, index=0):
    h = int(hashlib.md5(title.encode()).hexdigest()[:6], 16)
    hue1 = h % 360; hue2 = (h // 7) % 360
    return f'background:linear-gradient(135deg,hsl({hue1},60%,35%),hsl({hue2},50%,25%));'

def generate_poem_cover_gradient(title, index=0):
    h = int(hashlib.md5(title.encode()).hexdigest()[:6], 16)
    hue1 = (h % 180) + 10; hue2 = ((h // 7) % 180) + 20
    return f'background:linear-gradient(135deg,hsl({hue1},55%,38%),hsl({hue2},48%,28%));'

# ── Content Loading ─────────────────────────────────────────────────────────
def load_content(config):
    posts = []; poems = []
    for md_file in sorted(POSTS_DIR.glob("*.md"), reverse=True):
        raw = md_file.read_text(encoding="utf-8")
        meta, body_md = parse_frontmatter(raw)
        meta.setdefault("title",md_file.stem); meta.setdefault("date",str(date.today()))
        meta.setdefault("tags",[]); meta.setdefault("excerpt","")
        meta.setdefault("draft",False); meta.setdefault("pinned",False)
        if isinstance(meta["draft"],str): meta["draft"] = meta["draft"].lower() in ("true","yes","1")
        if isinstance(meta["pinned"],str): meta["pinned"] = meta["pinned"].lower() in ("true","yes","1")
        if isinstance(meta["tags"],str): meta["tags"] = [meta["tags"]]
        if meta["draft"]: continue
        slug = md_file.stem
        html_body = add_heading_ids(md_to_html(body_md))
        headings = extract_headings(html_body)
        posts.append(dict(title=meta["title"],date=meta["date"],tags=meta["tags"],
            excerpt=meta["excerpt"],slug=slug,html_body=html_body,raw_body=body_md,
            headings=headings,reading_time=reading_time(body_md),
            word_count=word_count(body_md),pinned=meta["pinned"]))
    posts.sort(key=lambda p:(not p["pinned"],p["date"]),reverse=False)
    posts.sort(key=lambda p:p["pinned"],reverse=True)

    for md_file in sorted(POEMS_DIR.glob("*.md"), reverse=True):
        raw = md_file.read_text(encoding="utf-8")
        meta, body_md = parse_frontmatter(raw)
        meta.setdefault("title",md_file.stem); meta.setdefault("date",str(date.today()))
        meta.setdefault("tags",[]); meta.setdefault("excerpt","")
        meta.setdefault("draft",False)
        if isinstance(meta["draft"],str): meta["draft"] = meta["draft"].lower() in ("true","yes","1")
        if isinstance(meta["tags"],str): meta["tags"] = [meta["tags"]]
        if meta["draft"]: continue
        slug = md_file.stem
        html_body = add_heading_ids(md_to_html(body_md))
        headings = extract_headings(html_body)
        poems.append(dict(title=meta["title"],date=meta["date"],tags=meta["tags"],
            excerpt=meta["excerpt"],slug=slug,html_body=html_body,raw_body=body_md,
            headings=headings,reading_time=reading_time(body_md),
            word_count=word_count(body_md)))
    poems.sort(key=lambda p:p["date"],reverse=True)
    return posts, poems

# ── Starfield CSS ───────────────────────────────────────────────────────────
def generate_starfield_css(seed=42):
    """Generate starfield CSS: 80 small + 30 medium stars + 3 shooting stars."""
    rng = random.Random(seed)
    stars_small = []; stars_med = []
    for _ in range(80):
        x = round(rng.uniform(0,100),1); y = round(rng.uniform(0,100),1)
        opacity = round(rng.uniform(0.5,0.9),2)
        stars_small.append(f"{x}vw {y}vh 0 {rng.uniform(0.3,0.6):.2f}px rgba(255,255,255,{opacity})")
    for _ in range(30):
        x = round(rng.uniform(0,100),1); y = round(rng.uniform(0,100),1)
        opacity = round(rng.uniform(0.5,0.9),2)
        stars_med.append(f"{x}vw {y}vh 0 {rng.uniform(0.6,1.0):.2f}px rgba(200,210,255,{opacity})")
    return f"""
/* Auto-generated starfield */
.stars-small{{
  position:fixed;inset:0;z-index:0;pointer-events:none;
  box-shadow:{','.join(stars_small)};
  animation:twinkle-small 4s ease-in-out infinite alternate;
}}
.stars-medium{{
  position:fixed;inset:0;z-index:0;pointer-events:none;
  box-shadow:{','.join(stars_med)};
  animation:twinkle-med 6s ease-in-out infinite alternate-reverse;
}}
@keyframes twinkle-small{{0%{{opacity:0.5}}50%{{opacity:0.85}}100%{{opacity:0.6}}}}
@keyframes twinkle-med{{0%{{opacity:0.4}}30%{{opacity:0.75}}70%{{opacity:0.5}}100%{{opacity:0.7}}}}

/* Shooting stars */
.shooting-star{{
  position:fixed;z-index:1;pointer-events:none;
  width:120px;height:0.5px;
  background:linear-gradient(to right,transparent,rgba(255,255,255,0.5),transparent);
  animation:shoot1 20s linear infinite;
  top:15vh;right:-120px;transform:rotate(-20deg);
}}
.shooting-star:nth-child(2){{
  top:30vh;animation-name:shoot2;animation-duration:27s;animation-delay:8s;
  transform:rotate(-15deg);
}}
.shooting-star:nth-child(3){{
  top:55vh;animation-name:shoot3;animation-duration:23s;animation-delay:15s;
  transform:rotate(-25deg);
}}
@keyframes shoot1{{
  0%{{right:-120px;top:15vh;opacity:0}}
  3%{{opacity:0.7}}
  7%{{right:110vw;top:70vh;opacity:0}}
  100%{{right:110vw;top:70vh;opacity:0}}
}}
@keyframes shoot2{{
  0%{{right:-120px;top:30vh;opacity:0}}
  2%{{opacity:0.6}}
  6%{{right:110vw;top:75vh;opacity:0}}
  100%{{right:110vw;top:75vh;opacity:0}}
}}
@keyframes shoot3{{
  0%{{right:-120px;top:55vh;opacity:0}}
  4%{{opacity:0.5}}
  8%{{right:110vw;top:85vh;opacity:0}}
  100%{{right:110vw;top:85vh;opacity:0}}
}}

@media(prefers-reduced-motion:reduce){{
  .stars-small,.stars-medium,.shooting-star{{animation:none}}
}}
"""
def render_page(config: dict, title: str, body: str, extra_head: str = "",
                og_title: str = None, og_desc: str = None, og_url: str = None,
                og_type: str = "website", ld_json: str = None,
                include_stars: bool = True) -> str:
    """Render complete HTML page."""
    site_url = config["site"]["url"].rstrip("/")
    og_title = og_title or title
    og_desc = og_desc or config["site"]["description"]
    og_url = og_url or site_url

    nav = "\n".join(f'            <a href="{l["href"]}">{l["label"]}</a>' for l in config.get("nav", []))

    og = f"""
    <meta property="og:title" content="{escape_html(og_title)}">
    <meta property="og:description" content="{escape_html(og_desc)}">
    <meta property="og:url" content="{og_url}">
    <meta property="og:type" content="{og_type}">
    <meta property="og:site_name" content="{escape_html(config['site']['name'])}">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="{escape_html(og_title)}">
    <meta name="twitter:description" content="{escape_html(og_desc)}">"""

    ld = ""
    if ld_json:
        ld = f'\n    <script type="application/ld+json">\n{ld_json}\n    </script>'

    stars = ""
    if include_stars:
        stars = '\n    <link rel="stylesheet" href="/starfield.css">'

    return f"""<!DOCTYPE html>
<html lang="{config['site']['language']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape_html(title)} — {escape_html(config['site']['name'])}</title>
    <meta name="description" content="{escape_html(og_desc)}">
    <meta name="keywords" content="{escape_html(config['site'].get('keywords',''))}">
    <meta name="author" content="{escape_html(config['author']['name'])}">{og}
    <link rel="alternate" type="application/rss+xml" title="{escape_html(config['site']['name'])} RSS" href="/rss.xml">
    <link rel="stylesheet" href="/style.css">{stars}
    {extra_head}{ld}
</head>
<body>
    <div class="stars-small"></div>
    <div class="stars-medium"></div>
    <div class="shooting-star"></div>
    <div class="shooting-star"></div>
    <div class="shooting-star"></div>
    <div class="sunset-glow"></div>
    <header class="site-header">
        <div class="container">
            <a href="/" class="logo" title="朝暮集">{config['author']['avatar']} {escape_html(config['site']['name'])}</a>
            <button class="nav-toggle" aria-label="菜单" id="navToggle">☰</button>
            <nav id="siteNav">
{nav}
            </nav>
        </div>
    </header>
    <main class="container">
{body}
    </main>
    <footer class="site-footer">
        <div class="container">
            <p>{config['footer']}</p>
            <p class="admin-entry" id="adminEntry" style="display:none">
                <a href="/admin/">⚙️ 管理</a>
            </p>
        </div>
    </footer>
    <button class="back-to-top" id="backToTop" title="回到顶部" aria-label="回到顶部">↑</button>
    <div class="toast" id="toast"></div>
    <script src="/app.js"></script>
</body>
</html>"""

# ── Page builders ───────────────────────────────────────────────────────────

def build_homepage(posts, poems, config):
    """全新首页: 搜索+标签云 + 超大标题朝暮集 + 文章/诗歌悬浮卡片入口"""
    # Tag cloud from posts + poems
    tag_counts = {}
    for p in posts + poems:
        for t in p.get("tags",[]):
            tag_counts[t] = tag_counts.get(t,0) + 1
    tag_btns = '<button class="tag-btn active" data-tag="_all">全部</button>'
    for t, c in sorted(tag_counts.items()):
        tag_btns += f'\n                    <button class="tag-btn" data-tag="{escape_html(t)}">{escape_html(t)}<span class="tag-count">{c}</span></button>'

    body = f"""
    <section class="home-hero">
        <div class="home-search">
            <div class="search-bar">
                <span class="search-icon">&#128269;</span>
                <input type="text" id="searchInput" placeholder="搜索文章与诗歌..." autocomplete="off">
            </div>
            <div class="tag-cloud" id="tagCloud">
                {tag_btns}
            </div>
        </div>
        <h1 class="home-title">朝 暮 集</h1>
        <div class="home-modules">
            <a href="/articles/" class="home-module module-posts">
                <span class="module-icon">&#128218;</span>
                <span class="module-label">文章</span>
                <span class="module-count">{len(posts)} 篇</span>
            </a>
            <a href="/poetry/" class="home-module module-poems">
                <span class="module-icon">&#127912;</span>
                <span class="module-label">诗歌</span>
                <span class="module-count">{len(poems)} 首</span>
            </a>
        </div>
    </section>"""

    html = render_page(config, config["site"]["name"], body,
                       og_type="website", include_stars=True)
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    print("   ✅ index.html")


def build_articles_list(posts, config):
    """生成 /articles/index.html — 文章封面卡片列表"""
    items = ""
    for i, p in enumerate(posts):
        grad = generate_cover_gradient(p["title"], i)
        tags_html = " · ".join(f'<span class="cover-tag">{escape_html(t)}</span>' for t in p.get("tags",[])[:3])
        items += f"""
            <a href="/post/{p['slug']}.html" class="cover-card-link">
                <article class="cover-card" style="{grad}">
                    <div class="cover-card-inner">
                        <h2 class="cover-title">{escape_html(p['title'])}</h2>
                        <div class="cover-meta">
                            <time datetime="{p['date']}">{p['date']}</time>
                        </div>
                        <div class="cover-tags">{tags_html}</div>
                    </div>
                </article>
            </a>"""
    body = f"""
    <section class="list-page">
        <h1 class="list-page-title">文章</h1>
        <p class="list-page-sub">共 {len(posts)} 篇文章</p>
        <div class="cover-grid">
            {items}
        </div>
    </section>"""
    html = render_page(config, "文章", body, og_type="website", include_stars=True)
    OUT_ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_ARTICLES_DIR / "index.html").write_text(html, encoding="utf-8")
    print("   ✅ articles/index.html")

def build_poetry_list(poems, config):
    """生成 /poetry/index.html — 诗歌封面卡片列表 (暖色调)"""
    items = ""
    for i, p in enumerate(poems):
        grad = generate_poem_cover_gradient(p["title"], i)
        tags_html = " · ".join(f'<span class="cover-tag">{escape_html(t)}</span>' for t in p.get("tags",[])[:3])
        items += f"""
            <a href="/poem/{p['slug']}.html" class="cover-card-link">
                <article class="cover-card poem-cover" style="{grad}">
                    <div class="cover-card-inner">
                        <h2 class="cover-title">{escape_html(p['title'])}</h2>
                        <div class="cover-meta">
                            <time datetime="{p['date']}">{p['date']}</time>
                        </div>
                        <div class="cover-tags">{tags_html}</div>
                    </div>
                </article>
            </a>"""
    body = f"""
    <section class="list-page">
        <h1 class="list-page-title">诗歌</h1>
        <p class="list-page-sub">共 {len(poems)} 首诗歌</p>
        <div class="cover-grid">
            {items}
        </div>
    </section>"""
    html = render_page(config, "诗歌", body, og_type="website", include_stars=True)
    OUT_POETRY_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_POETRY_DIR / "index.html").write_text(html, encoding="utf-8")
    print("   ✅ poetry/index.html")


def build_post_page(post: dict, config: dict):
    """Generate a single post page with TOC, progress bar, OG tags, structured data."""
    site_url = config["site"]["url"].rstrip("/")
    post_url = f"{site_url}/post/{post['slug']}.html"

    # Structured data
    ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post["title"],
        "datePublished": post["date"],
        "author": {"@type": "Person", "name": config["author"]["name"]},
        "description": post.get("excerpt", ""),
        "url": post_url,
    }, ensure_ascii=False)

    # TOC sidebar
    toc_html = ""
    if post["headings"] and len(post["headings"]) >= 2:
        toc_items = ""
        for h in post["headings"]:
            indent = "toc-indent" if h["level"] == 3 else ""
            toc_items += f'\n                <li class="toc-item {indent}"><a href="#{h["id"]}">{escape_html(h["text"])}</a></li>'
        toc_html = f"""
    <aside class="toc-sidebar" id="tocSidebar">
        <button class="toc-toggle" id="tocToggle" aria-label="切换目录">📑 目录</button>
        <nav class="toc-nav" id="tocNav">
            <ol>{toc_items}
            </ol>
        </nav>
    </aside>"""

    tags_html = "".join(f'<span class="tag">{escape_html(t)}</span>' for t in post.get("tags", []))

    # Admin edit button (visibility controlled by JS via token detection)
    admin_edit = f'<a href="/admin/#edit={post["slug"]}" class="admin-edit-link" id="adminEditLink" style="display:none">✏️ 编辑此文章</a>'

    body = f"""
    <div class="progress-bar" id="progressBar"></div>
    <article class="single-post">
        <header class="post-header">
            <h1>{escape_html(post['title'])}</h1>
            <div class="post-meta">
                <time datetime="{post['date']}">{post['date']}</time>
                <span>· 约 {post['reading_time']} 分钟</span>
                <span>· {post['word_count']} 字</span>
                <div class="post-tags">{tags_html}</div>
            </div>
        </header>
        {toc_html}
        <div class="post-content" id="postContent">
            {post['html_body']}
        </div>
        <div class="post-actions">
            <div class="share-buttons">
                <button class="share-btn" onclick="copyLink()" title="复制链接">📋 复制链接</button>
                <button class="share-btn" onclick="shareTo('twitter')" title="分享到 X">🐦</button>
                <button class="share-btn" onclick="shareTo('weixin')" title="分享到微信">💬</button>
            </div>
            {admin_edit}
        </div>
        <nav class="post-nav">
            <a href="/" class="back-home">← 返回首页</a>
        </nav>
    </article>"""

    html = render_page(config, post["title"], body,
                       og_title=post["title"], og_desc=post.get("excerpt", ""),
                       og_url=post_url, og_type="article", ld_json=ld,
                       include_stars=False)
    (OUT_POSTS_DIR / f"{post['slug']}.html").write_text(html, encoding="utf-8")
    print(f"   ✅ post/{post['slug']}.html")


def build_poem_page(poem, config):
    """Generate poem detail page, similar to post page."""
    site_url = config["site"]["url"].rstrip("/")
    poem_url = f"{site_url}/poem/{poem['slug']}.html"

    # Structured data
    ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": poem["title"],
        "datePublished": poem["date"],
        "author": {"@type": "Person", "name": config["author"]["name"]},
        "description": poem.get("excerpt", ""),
        "url": poem_url,
    }, ensure_ascii=False)

    # TOC sidebar
    toc_html = ""
    if poem["headings"] and len(poem["headings"]) >= 2:
        toc_items = ""
        for h in poem["headings"]:
            indent = "toc-indent" if h["level"] == 3 else ""
            toc_items += f'\n                <li class="toc-item {indent}"><a href="#{h["id"]}">{escape_html(h["text"])}</a></li>'
        toc_html = f"""
    <aside class="toc-sidebar" id="tocSidebar">
        <button class="toc-toggle" id="tocToggle" aria-label="切换目录">📑 目录</button>
        <nav class="toc-nav" id="tocNav">
            <ol>{toc_items}
            </ol>
        </nav>
    </aside>"""

    tags_html = "".join(f'<span class="tag">{escape_html(t)}</span>' for t in poem.get("tags", []))

    body = f"""
    <div class="progress-bar" id="progressBar"></div>
    <article class="single-post">
        <header class="post-header">
            <h1>{escape_html(poem['title'])}</h1>
            <div class="post-meta">
                <time datetime="{poem['date']}">{poem['date']}</time>
                <span>· {poem.get('word_count',0)} 字</span>
                <div class="post-tags">{tags_html}</div>
            </div>
        </header>
        {toc_html}
        <div class="post-content" id="postContent">
            {poem['html_body']}
        </div>
        <div class="post-actions">
            <div class="share-buttons">
                <button class="share-btn" onclick="copyLink()" title="复制链接">📋 复制链接</button>
                <button class="share-btn" onclick="shareTo('twitter')" title="分享到 X">🐦</button>
                <button class="share-btn" onclick="shareTo('weixin')" title="分享到微信">💬</button>
            </div>
        </div>
        <nav class="post-nav">
            <a href="/poetry/" class="back-home">← 返回诗歌列表</a>
        </nav>
    </article>"""

    html = render_page(config, poem["title"], body,
                       og_title=poem["title"], og_desc=poem.get("excerpt", ""),
                       og_url=poem_url, og_type="article", ld_json=ld,
                       include_stars=False)
    OUT_POEMS_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_POEMS_DIR / f"{poem['slug']}.html").write_text(html, encoding="utf-8")
    print(f"   ✅ poem/{poem['slug']}.html")


def build_about(config):
    """分区卡片化关于页: 关于我/我的理念/技术栈/联系方式 四个卡片"""
    about_md = PAGES_DIR / "about.md"
    if about_md.exists():
        raw = about_md.read_text(encoding="utf-8")
        meta, body_md = parse_frontmatter(raw)
        content = md_to_html(body_md)
    else:
        content = f"<p>{escape_html(config['author']['bio'])}</p>"

    philosophy = escape_html(config["author"].get("philosophy",""))
    tech_stack = config.get("tech_stack",[])
    tech_html = " · ".join(f'<span class="tech-badge">{escape_html(t)}</span>' for t in tech_stack) if tech_stack else "内容创作、Python、前端开发"
    social_html = "".join(
        f'<a href="{s["url"]}" target="_blank" rel="noopener" class="about-link">{s["platform"]}</a>'
        for s in config.get("social",[]))

    body = f"""
    <section class="about-page">
        <div class="about-grid">
            <div class="about-card">
                <h2>👤 关于我</h2>
                <div class="about-avatar">{config['author']['avatar']}</div>
                <h3>{escape_html(config['author']['name'])}</h3>
                <p>{escape_html(config['author'].get('bio',''))}</p>
            </div>
            <div class="about-card">
                <h2>💡 我的理念</h2>
                <blockquote>{philosophy}</blockquote>
            </div>
            <div class="about-card">
                <h2>🛠️ 技术栈</h2>
                <p class="tech-stack">{tech_html}</p>
            </div>
            <div class="about-card">
                <h2>📬 联系方式</h2>
                <div class="about-links">{social_html}</div>
            </div>
        </div>
        <div class="about-content" id="aboutContent">
            {content}
        </div>
    </section>"""

    html = render_page(config, "关于", body,
                       og_title=f"关于 {config['author']['name']}",
                       og_desc=config['author'].get('bio',''),
                       og_type="profile", include_stars=False)
    (OUT_DIR / "about.html").write_text(html, encoding="utf-8")
    print("   ✅ about.html")


def build_404(config: dict):
    """Generate 404.html."""
    body = f"""
    <section class="error-page">
        <div class="error-avatar">{config['author']['avatar']}</div>
        <h1>404</h1>
        <p>页面未找到</p>
        <p class="error-sub">你访问的页面不存在，或者已被删除。</p>
        <div class="error-links">
            <a href="/" class="btn-primary">← 返回首页</a>
        </div>
    </section>"""
    html = render_page(config, "404", body, include_stars=True)
    (OUT_DIR / "404.html").write_text(html, encoding="utf-8")
    print("   ✅ 404.html")


def build_rss(posts, poems, config):
    """Generate rss.xml including posts and poems."""
    site_url = config["site"]["url"].rstrip("/")
    items = ""
    for p in posts:
        items += f"""
    <item>
      <title>{xml_escape(p['title'])}</title>
      <link>{site_url}/post/{p['slug']}.html</link>
      <guid isPermaLink="true">{site_url}/post/{p['slug']}.html</guid>
      <pubDate>{rfc2822(p['date'])}</pubDate>
      <description>{xml_escape(p.get('excerpt',''))}</description>
    </item>"""
    for p in poems:
        items += f"""
    <item>
      <title>【诗歌】{xml_escape(p['title'])}</title>
      <link>{site_url}/poem/{p['slug']}.html</link>
      <guid isPermaLink="true">{site_url}/poem/{p['slug']}.html</guid>
      <pubDate>{rfc2822(p['date'])}</pubDate>
      <description>{xml_escape(p.get('excerpt',''))}</description>
    </item>"""
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{xml_escape(config['site']['name'])}</title>
  <link>{site_url}</link>
  <description>{xml_escape(config['site']['description'])}</description>
  <language>{config['site']['language']}</language>
  <lastBuildDate>{rfc2822(str(date.today()))}</lastBuildDate>
  <atom:link href="{site_url}/rss.xml" rel="self" type="application/rss+xml"/>
{items}
</channel>
</rss>"""
    (OUT_DIR / "rss.xml").write_text(rss, encoding="utf-8")
    print("   ✅ rss.xml")

def build_search_index(posts, poems):
    def _preview(raw):
        txt = re.sub(r"<[^>]+>"," ",raw); txt = re.sub(r"\s+"," ",txt).strip()
        return txt[:300]
    idx = []
    for p in posts:
        idx.append(dict(title=p["title"],date=p["date"],tags=p.get("tags",[]),
            excerpt=p.get("excerpt",""),body_preview=_preview(p["raw_body"]),
            url=f"/post/{p['slug']}.html",reading_time=p["reading_time"],
            pinned=p.get("pinned",False),type="post"))
    for p in poems:
        idx.append(dict(title=p["title"],date=p["date"],tags=p.get("tags",[]),
            excerpt=p.get("excerpt",""),body_preview=_preview(p["raw_body"]),
            url=f"/poem/{p['slug']}.html",reading_time=p["reading_time"],
            pinned=False,type="poem"))
    (OUT_DIR / "search-index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    print("   ✅ search-index.json")

def build_tags_json(posts, poems):
    tags = {}
    for p in posts + poems:
        for t in p.get("tags",[]):
            if t not in tags: tags[t] = {"count":0,"items":[]}
            tags[t]["count"] += 1
            url = f"/post/{p['slug']}.html" if "pinned" in p else f"/poem/{p['slug']}.html"
            tags[t]["items"].append({"title":p["title"],"url":url,"date":p["date"]})
    (OUT_DIR / "tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=2), encoding="utf-8")
    print("   ✅ tags.json")

def build_sitemap(posts, poems, config):
    site_url = config["site"]["url"].rstrip("/")
    urls = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{site_url}/</loc><priority>1.0</priority></url>
  <url><loc>{site_url}/articles/</loc><priority>0.9</priority></url>
  <url><loc>{site_url}/poetry/</loc><priority>0.9</priority></url>
  <url><loc>{site_url}/about.html</loc><priority>0.8</priority></url>"""
    for p in posts:
        urls += f'\n  <url><loc>{site_url}/post/{p["slug"]}.html</loc><priority>0.7</priority></url>'
    for p in poems:
        urls += f'\n  <url><loc>{site_url}/poem/{p["slug"]}.html</loc><priority>0.7</priority></url>'
    urls += "\n</urlset>"
    (OUT_DIR / "sitemap.xml").write_text(urls, encoding="utf-8")
    print("   ✅ sitemap.xml")

def build_robots(config):
    site_url = config["site"]["url"].rstrip("/")
    (OUT_DIR / "robots.txt").write_text(f"""User-agent: *
Allow: /
Sitemap: {site_url}/sitemap.xml
""", encoding="utf-8")
    print("   ✅ robots.txt")


def copy_assets():
    sf_css = generate_starfield_css()
    (OUT_DIR / "starfield.css").write_text(sf_css, encoding="utf-8")
    css_src = SRC_DIR / "style.css"
    if css_src.exists(): shutil.copy(css_src, OUT_DIR / "style.css")
    else: (OUT_DIR / "style.css").write_text("/* placeholder */", encoding="utf-8")
    js_src = SRC_DIR / "app.js"
    if js_src.exists(): shutil.copy(js_src, OUT_DIR / "app.js")
    admin_src = SRC_DIR / "admin"
    admin_dst = OUT_DIR / "admin"
    admin_dst.mkdir(parents=True, exist_ok=True)
    if admin_src.exists():
        for f in admin_src.iterdir():
            if f.is_file(): shutil.copy(f, admin_dst / f.name)
    print("   ✅ starfield.css, style.css, app.js, admin/")


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print(f"🔨 blog-v2 Static Site Builder — v4")
    print(f"   Python {sys.version.split()[0]}  |  markdown {markdown.__version__}")

    if OUT_DIR.exists(): shutil.rmtree(OUT_DIR)
    OUT_POSTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_POEMS_DIR.mkdir(parents=True, exist_ok=True)

    config = load_json(ROOT / "config.json")
    posts, poems = load_content(config)
    print(f"   Posts: {len(posts)}  |  Poems: {len(poems)}")

    build_homepage(posts, poems, config)
    build_articles_list(posts, config)
    build_poetry_list(poems, config)
    for p in posts:
        build_post_page(p, config)
    for p in poems:
        build_poem_page(p, config)
    build_about(config)
    build_404(config)
    build_rss(posts, poems, config)
    build_search_index(posts, poems)
    build_tags_json(posts, poems)
    build_sitemap(posts, poems, config)
    build_robots(config)
    copy_assets()

    total = len(list(OUT_DIR.rglob("*")))
    print(f"\n🎉 Done! {total} files written to {OUT_DIR}")
    print(f"   Open {OUT_DIR / 'index.html'} in your browser.\n")

if __name__ == "__main__":
    main()
