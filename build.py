#!/usr/bin/env python3
"""
blog-v2 Static Site Builder — v3
=================================
Reads Markdown posts + pages, generates a feature-rich static blog.
Features: TOC, reading time, OG tags, structured data, sitemap,
          tag cloud, search index, starfield background, 404 page.
Usage: python build.py
"""

import json, shutil, sys, io, re, random
from datetime import date, datetime, timezone
from pathlib import Path
from email.utils import format_datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "posts"
PAGES_DIR = ROOT / "pages"
SRC_DIR = ROOT / "src"
OUT_DIR = ROOT / "public"
OUT_POSTS_DIR = OUT_DIR / "post"

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

# ── Posts loading ───────────────────────────────────────────────────────────
def load_posts(config: dict) -> list[dict]:
    posts = []
    for md_file in sorted(POSTS_DIR.glob("*.md"), reverse=True):
        raw = md_file.read_text(encoding="utf-8")
        meta, body_md = parse_frontmatter(raw)
        meta.setdefault("title", md_file.stem)
        meta.setdefault("date", str(date.today()))
        meta.setdefault("tags", [])
        meta.setdefault("excerpt", "")
        meta.setdefault("draft", False)
        meta.setdefault("pinned", False)
        if isinstance(meta["draft"], str):
            meta["draft"] = meta["draft"].lower() in ("true", "yes", "1")
        if isinstance(meta["pinned"], str):
            meta["pinned"] = meta["pinned"].lower() in ("true", "yes", "1")
        if isinstance(meta["tags"], str):
            meta["tags"] = [meta["tags"]]
        if meta["draft"]:
            continue
        slug = md_file.stem
        html_body = md_to_html(body_md)
        html_body = add_heading_ids(html_body)
        headings = extract_headings(html_body)
        posts.append({
            "title": meta["title"],
            "date": meta["date"],
            "tags": meta["tags"],
            "excerpt": meta["excerpt"],
            "slug": slug,
            "html_body": html_body,
            "raw_body": body_md,
            "headings": headings,
            "reading_time": reading_time(body_md),
            "word_count": word_count(body_md),
            "pinned": meta["pinned"],
        })
    # Sort: pinned first, then by date
    posts.sort(key=lambda p: (not p["pinned"], p["date"]), reverse=False)
    posts.sort(key=lambda p: p["pinned"], reverse=True)
    return posts

# ── Starfield CSS ───────────────────────────────────────────────────────────
def generate_starfield_css(seed: int = 42) -> str:
    """Generate deterministic starfield CSS: 60 small + 20 medium stars + 2 shooting stars."""
    rng = random.Random(seed)
    stars_small = []
    stars_med = []
    for _ in range(60):
        x = round(rng.uniform(0, 100), 1)
        y = round(rng.uniform(0, 100), 1)
        opacity = round(rng.uniform(0.3, 0.7), 2)
        stars_small.append(f"{x}vw {y}vh 0 {rng.uniform(0.3,0.6):.2f}px rgba(255,255,255,{opacity})")
    for _ in range(20):
        x = round(rng.uniform(0, 100), 1)
        y = round(rng.uniform(0, 100), 1)
        opacity = round(rng.uniform(0.25, 0.65), 2)
        stars_med.append(f"{x}vw {y}vh 0 {rng.uniform(0.6,1.0):.2f}px rgba(200,210,255,{opacity})")
    return f"""
/* Auto-generated starfield + shooting stars */
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
@keyframes twinkle-small{{
  0%{{opacity:0.5}}50%{{opacity:0.85}}100%{{opacity:0.6}}
}}
@keyframes twinkle-med{{
  0%{{opacity:0.4}}30%{{opacity:0.75}}70%{{opacity:0.5}}100%{{opacity:0.7}}
}}

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
    <div class="sunset-glow"></div>
    <header class="site-header">
        <div class="container">
            <a href="/about.html" class="logo" title="个人主页">{config['author']['avatar']} {escape_html(config['site']['name'])}</a>
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

def build_homepage(posts: list[dict], config: dict):
    """Generate index.html with hero, search, tag cloud, and post cards."""
    hero = f"""
    <section class="hero">
        <h1 class="hero-name">{escape_html(config['author']['name'])}</h1>
        <p class="hero-tagline">{escape_html(config['site']['tagline'])}</p>
        <div class="hero-divider"></div>
    </section>

    <div class="module-card personal-card">
        <a href="/about.html" class="personal-avatar">{config['author']['avatar']}</a>
        <p class="personal-bio">{escape_html(config['author']['bio'])}</p>
        <div class="personal-links">
            {''.join(f'<a href="{s["url"]}" target="_blank" rel="noopener">{s["platform"]}</a>' for s in config.get("social", []))}
        </div>
    </div>"""

    # Tag cloud
    tag_counts = {}
    for p in posts:
        for t in p["tags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    tag_buttons = '<button class="tag-btn active" data-tag="_all">全部</button>'
    for t, c in sorted(tag_counts.items()):
        tag_buttons += f'\n                    <button class="tag-btn" data-tag="{escape_html(t)}">{escape_html(t)}<span class="tag-count">{c}</span></button>'

    # Post cards
    if not posts:
        cards = '<p class="no-posts">还没有文章，敬请期待</p>'
    else:
        cards = ""
        for p in posts:
            tags_html = " · ".join(f'<span class="tag-link" data-tag="{escape_html(t)}">{escape_html(t)}</span>' for t in p.get("tags", []))
            pin_mark = ' <span class="pin-badge">置顶</span>' if p.get("pinned") else ""
            cards += f"""
        <a href="/post/{p['slug']}.html" class="post-card-link" data-tags="{','.join(t for t in p['tags'])}">
            <article class="module-card post-card">
                <h2 class="post-card-title">{escape_html(p['title'])}{pin_mark}</h2>
                <div class="post-card-meta">
                    <time datetime="{p['date']}">{p['date']}</time>
                    <span>· {p['reading_time']} 分钟</span>
                    <span class="post-card-tags">{tags_html}</span>
                </div>
            </article>
        </a>"""

    body = hero + f"""
    <div class="module-card search-card">
        <input type="text" id="searchInput" placeholder="搜索文章..." autocomplete="off">
    </div>

    <div class="tag-cloud" id="tagCloud">
        {tag_buttons}
    </div>

    <section class="posts-section">
        <h2 class="section-title">文章</h2>
        <div class="post-list" id="postList">
            {cards}
        </div>
        <p class="no-results" id="noResults" style="display:none">没有找到匹配的文章 😕</p>
    </section>"""

    html = render_page(config, config["site"]["name"], body,
                       og_type="website", include_stars=True)
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    print("   ✅ index.html")


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


def build_about(config: dict):
    """Generate about.html (personal homepage)."""
    about_md = PAGES_DIR / "about.md"
    if about_md.exists():
        raw = about_md.read_text(encoding="utf-8")
        meta, body_md = parse_frontmatter(raw)
        content = add_heading_ids(md_to_html(body_md))
    else:
        content = f"""<h2>关于我</h2><p>{escape_html(config['author']['bio'])}</p>
<h3>我的理念</h3><blockquote>{escape_html(config['author'].get('philosophy', ''))}</blockquote>"""

    social_html = "".join(
        f'<a href="{s["url"]}" target="_blank" rel="noopener" class="about-link">{s["platform"]}</a>'
        for s in config.get("social", [])
    )

    # Admin edit button
    admin_edit = '<a href="/admin/#edit=about" class="admin-edit-link" id="adminEditLink" style="display:none">✏️ 编辑个人主页</a>'

    body = f"""
    <section class="about-page">
        <div class="about-header">
            <div class="about-avatar">{config['author']['avatar']}</div>
            <h1>{escape_html(config['author']['name'])}</h1>
        </div>
        <div class="about-content" id="aboutContent">
            {content}
        </div>
        <div class="about-links">
            {social_html}
        </div>
        <div class="post-actions">
            {admin_edit}
        </div>
    </section>"""

    html = render_page(config, "关于", body,
                       og_title=f"关于 {config['author']['name']}",
                       og_desc=config['author'].get('bio', ''),
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


def build_rss(posts: list[dict], config: dict):
    """Generate rss.xml."""
    site_url = config["site"]["url"].rstrip("/")
    items = ""
    for p in posts:
        items += f"""
    <item>
      <title>{xml_escape(p['title'])}</title>
      <link>{site_url}/post/{p['slug']}.html</link>
      <guid isPermaLink="true">{site_url}/post/{p['slug']}.html</guid>
      <pubDate>{rfc2822(p['date'])}</pubDate>
      <description>{xml_escape(p.get('excerpt', ''))}</description>
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


def build_search_index(posts: list[dict]):
    """Generate enhanced search-index.json."""
    idx = []
    for p in posts:
        # Strip HTML from body preview
        body_text = re.sub(r"<[^>]+>", " ", p["raw_body"])
        body_text = re.sub(r"\s+", " ", body_text).strip()
        idx.append({
            "title": p["title"],
            "date": p["date"],
            "tags": p.get("tags", []),
            "excerpt": p.get("excerpt", ""),
            "body_preview": body_text[:300],
            "url": f"/post/{p['slug']}.html",
            "reading_time": p["reading_time"],
            "pinned": p.get("pinned", False),
        })
    (OUT_DIR / "search-index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    print("   ✅ search-index.json")


def build_tags_json(posts: list[dict]):
    """Generate tags.json with tag → posts mapping."""
    tags: dict = {}
    for p in posts:
        for t in p.get("tags", []):
            if t not in tags:
                tags[t] = {"count": 0, "posts": []}
            tags[t]["count"] += 1
            tags[t]["posts"].append({
                "title": p["title"],
                "url": f"/post/{p['slug']}.html",
                "date": p["date"],
            })
    (OUT_DIR / "tags.json").write_text(json.dumps(tags, ensure_ascii=False, indent=2), encoding="utf-8")
    print("   ✅ tags.json")


def build_sitemap(posts: list[dict], config: dict):
    """Generate sitemap.xml."""
    site_url = config["site"]["url"].rstrip("/")
    urls = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{site_url}/</loc><priority>1.0</priority></url>
  <url><loc>{site_url}/about.html</loc><priority>0.8</priority></url>"""
    for p in posts:
        urls += f'\n  <url><loc>{site_url}/post/{p["slug"]}.html</loc><priority>0.7</priority></url>'
    urls += "\n</urlset>"
    (OUT_DIR / "sitemap.xml").write_text(urls, encoding="utf-8")
    print("   ✅ sitemap.xml")


def build_robots(config: dict):
    """Generate robots.txt."""
    site_url = config["site"]["url"].rstrip("/")
    robots = f"""User-agent: *
Allow: /
Sitemap: {site_url}/sitemap.xml
"""
    (OUT_DIR / "robots.txt").write_text(robots, encoding="utf-8")
    print("   ✅ robots.txt")


def copy_assets(config: dict):
    """Copy style.css, admin, generate starfield.css."""
    # Starfield CSS
    sf_css = generate_starfield_css()
    (OUT_DIR / "starfield.css").write_text(sf_css, encoding="utf-8")

    # Main CSS from src/
    css_src = SRC_DIR / "style.css"
    if css_src.exists():
        shutil.copy(css_src, OUT_DIR / "style.css")
    else:
        (OUT_DIR / "style.css").write_text("/* placeholder - use src/style.css */", encoding="utf-8")

    # JS from src/
    js_src = SRC_DIR / "app.js"
    if js_src.exists():
        shutil.copy(js_src, OUT_DIR / "app.js")

    # Admin
    admin_src = SRC_DIR / "admin"
    admin_dst = OUT_DIR / "admin"
    admin_dst.mkdir(parents=True, exist_ok=True)
    if admin_src.exists():
        for f in admin_src.iterdir():
            if f.is_file():
                shutil.copy(f, admin_dst / f.name)
    print("   ✅ starfield.css, style.css, app.js, admin/")


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print(f"🔨 blog-v2 Static Site Builder — v3")
    print(f"   Python {sys.version.split()[0]}  |  markdown {markdown.__version__}")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_POSTS_DIR.mkdir(parents=True, exist_ok=True)

    config = load_json(ROOT / "config.json")
    posts = load_posts(config)
    print(f"   Posts: {len(posts)}")

    build_homepage(posts, config)
    for p in posts:
        build_post_page(p, config)
    build_about(config)
    build_404(config)
    build_rss(posts, config)
    build_search_index(posts)
    build_tags_json(posts)
    build_sitemap(posts, config)
    build_robots(config)
    copy_assets(config)

    total = len(list(OUT_DIR.rglob("*")))
    print(f"\n🎉 Done! {total} files written to {OUT_DIR}")
    print(f"   Open {OUT_DIR / 'index.html'} in your browser.\n")

if __name__ == "__main__":
    main()
