#!/usr/bin/env python3
"""Builds the Cabby website from the cabby repository.

    python3 build.py --cabby ../cabby --out _site [--release release.json]

Everything the site says about the language comes from the cabby
repository at the version being published: the manual (tutorials.md),
the language reference (README.md), the library pages (lib/*.md), the
style guide, the timeline and the logo. The hand-written pages (home,
download, playground) live in pages/, and the look in assets/.

Needs Python 3.8+ and pandoc (for GitHub-flavored Markdown).
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from string import Template

HERE = Path(__file__).resolve().parent
REPO = "cabby-lang/cabby"
GITHUB = f"https://github.com/{REPO}"


# ---------------------------------------------------------------- markdown

def md_to_html(text):
    """GitHub-flavored Markdown to an HTML fragment. Heading ids follow
    GitHub's rules (so links written for GitHub keep working), and code is
    left alone for our own highlighter."""
    r = subprocess.run(
        ["pandoc", "-f", "gfm", "-t", "html5", "--no-highlight", "--wrap=none", "--preserve-tabs"],
        input=text.encode(), capture_output=True, check=True)
    return r.stdout.decode()


# ------------------------------------------------------------ highlighting

class Highlighter:
    """Colors Cabby code the way `cabby`'s own highlighter (highlight.c)
    does, with its word lists read from highlight.c so the two agree."""

    def __init__(self, cabby_dir):
        src = (cabby_dir / "highlight.c").read_text()

        def words(name):
            m = re.search(r"\b" + name + r"\[\]\s*=\s*\{(.*?)\};", src, re.S)
            return set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()

        self.keywords = words("keywords")
        self.types = words("types")
        self.constants = words("constants") or {"true", "false"}
        self.functions = words("functions")
        self.members = words("members")
        self.lib_functions = words("lib_function_names")
        self.lib_types = words("lib_type_names")
        # every library is a namespace: gui.window, tui.label ...
        self.libraries = {p.stem for p in (cabby_dir / "lib").glob("*.hby")} | self.lib_functions
        self.token = re.compile(r"""
            (?P<lcom>//.*)
          | (?P<bcom>/\*)
          | (?P<str>"(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?)
          | (?P<num>\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\b)
          | (?P<qual>\b[A-Za-z_]\w*\.[A-Za-z_]\w*)
          | (?P<word>\b[A-Za-z_]\w*\b)
          | (?P<member>\.[A-Za-z_]\w*)
        """, re.X)

    @staticmethod
    def span(cls, text):
        return f'<span class="{cls}">{html.escape(text, quote=False)}</span>'

    def line(self, s, in_comment):
        out = []
        i = 0
        if in_comment:
            end = s.find("*/")
            if end < 0:
                return self.span("c", s), True
            out.append(self.span("c", s[:end + 2]))
            i = end + 2
        first_word = True
        while i < len(s):
            m = self.token.search(s, i)
            if not m:
                out.append(html.escape(s[i:], quote=False))
                break
            out.append(html.escape(s[i:m.start()], quote=False))
            kind, text = m.lastgroup, m.group()
            i = m.end()
            if kind == "lcom":
                out.append(self.span("c", text))
            elif kind == "bcom":
                end = s.find("*/", m.end())
                if end < 0:
                    out.append(self.span("c", s[m.start():]))
                    return "".join(out), True
                out.append(self.span("c", s[m.start():end + 2]))
                i = end + 2
            elif kind == "str":
                out.append(self.string(text))
            elif kind == "num":
                out.append(self.span("n", text))
            elif kind == "qual":
                lib, name = text.split(".", 1)
                if text in self.lib_types:
                    out.append(self.span("t", text))
                elif lib in self.libraries:
                    cls = "f" if lib in self.lib_functions else "t"
                    out.append(self.span(cls, text))
                else:  # Name.length: color the word, then the member
                    out.append(self.word(lib, first_word))
                    out.append(self.member("." + name))
            elif kind == "word":
                if first_word and text == "use":
                    rest = s[i:]
                    out.append(self.span("u", text) + self.span("u", rest))
                    break
                out.append(self.word(text, first_word))
            elif kind == "member":
                out.append(self.member(text))
            first_word = False
        return "".join(out), False

    def string(self, text):
        parts = re.split(r"(\\x[0-9a-fA-F]{1,2}|\\.|%[-+ 0#]*\d*(?:\.\d+)?[a-zA-Z])", text)
        return '<span class="s">' + "".join(
            self.span("e", p) if i % 2 else html.escape(p, quote=False)
            for i, p in enumerate(parts)) + "</span>"

    def word(self, w, first):
        if w in self.keywords:
            return self.span("k", w)
        if w in self.types:
            return self.span("t", w)
        if w in self.constants:
            return self.span("n", w)
        if w in self.functions:
            return self.span("f", w)
        if w == "self":
            return self.span("e", w)
        return html.escape(w, quote=False)

    def member(self, m):
        if m[1:] in self.members:
            return "." + self.span("e", m[1:])
        return html.escape(m, quote=False)

    def code(self, text):
        lines, in_comment = [], False
        for ln in text.split("\n"):
            h, in_comment = self.line(ln, in_comment)
            lines.append(h)
        return "\n".join(lines)

    LOOKS_LIKE_CABBY = re.compile(
        r"^\s*(?:int|void|str|double|bool|object|use|if|for|while|println|print|return|list|lookup|const|struct|enum)\b|[{}]\s*$|//",
        re.M)

    def html_blocks(self, fragment):
        """Highlights the <pre> blocks pandoc wrote: those marked cabby, and
        unmarked ones that look like Cabby. `text`, `sh` and the rest stay
        as they are."""
        def repl(m):
            cls, body = m.group(1) or "", m.group(2)
            code = html.unescape(body)
            if cls == "cabby" or (cls == "" and self.LOOKS_LIKE_CABBY.search(code)):
                return f'<pre class="code cabby"><code>{self.code(code)}</code></pre>'
            lang = f" {cls}" if cls else ""
            return f'<pre class="code{lang}"><code>{body}</code></pre>'
        return re.sub(r'<pre(?: class="([\w-]+)")?><code>(.*?)</code></pre>', repl, fragment, flags=re.S)


# ----------------------------------------------------------------- the site

class Site:
    def __init__(self, cabby_dir, out_dir, release):
        self.cabby = cabby_dir
        self.out = out_dir
        self.release = release
        vh = (cabby_dir / "version.h").read_text()
        self.version = re.search(r'CABBY_VERSION "([^"]+)"', vh).group(1)
        self.version_date = re.search(r'CABBY_VERSION_DATE "([^"]+)"', vh).group(1)
        self.tag = release.get("tag_name") or f"v{self.version}"
        self.hl = Highlighter(cabby_dir)
        self.layout = Template((HERE / "layout.html").read_text())
        self.manual_pages = []      # [(slug, title, part)]
        self.manual_ids = {}        # heading id -> manual page slug
        self.libraries = []         # [(name, description)]

    # where a page of the cabby repository lives on the site
    def site_url_for(self, repo_path, fragment=""):
        p = repo_path.as_posix()
        frag = f"#{fragment}" if fragment else ""
        if p == "tutorials/tutorials.md":
            if fragment and fragment in self.manual_ids:
                return f"/docs/manual/{self.manual_ids[fragment]}/#{fragment}"
            return "/docs/manual/" + frag
        fixed = {"README.md": "/docs/reference/", "STYLE.md": "/docs/style/",
                 "TIMELINE.md": "/docs/timeline/", "tutorials/README.md": "/docs/tutorials/"}
        if p in fixed:
            return fixed[p] + frag
        m = re.fullmatch(r"lib/(\w+)\.md", p)
        if m:
            return f"/docs/libraries/{m.group(1)}/" + frag
        kind = "tree" if (self.cabby / p).is_dir() else "blob"
        return f"{GITHUB}/{kind}/{self.tag}/{p}" + frag

    def fix_links(self, fragment, source, page_ids=None):
        """Points links between the repository's files at the site's pages,
        and the manual's own #links at the chapter they're in."""
        src_dir = Path(source).parent

        def repl(m):
            href = html.unescape(m.group(1))
            if re.match(r"^[a-z]+:", href) or href.startswith("/"):
                return m.group(0)
            path, _, frag = href.partition("#")
            if not path:
                if source == "tutorials/tutorials.md" and page_ids is not None and frag not in page_ids:
                    href = self.site_url_for(Path(source), frag)
                else:
                    return m.group(0)
            else:
                target = Path(os.path.normpath(src_dir / path))
                href = self.site_url_for(target, frag)
            return f'href="{html.escape(href)}"'
        return re.sub(r'href="([^"]*)"', repl, fragment)

    def render(self, html_fragment, source):
        return self.hl.html_blocks(self.fix_links(html_fragment, source))

    def write(self, url, title, content, *, section="", sidebar="", description="", body_class=""):
        path = self.out / url.strip("/") / "index.html" if not url.endswith(".html") else self.out / url.strip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        full_title = f"{title} · Cabby" if title != "Cabby" else "Cabby, a programming language"
        here = ' aria-current="page"'
        nav = "".join(
            f'<a href="{href}"{here if section == key else ""}>{name}</a>'
            for key, href, name in [("docs", "/docs/", "Docs"), ("download", "/download/", "Download"),
                                    ("playground", "/playground/", "Playground")])
        layout_class = "with-sidebar" if sidebar else "no-sidebar"
        path.write_text(self.layout.substitute(
            title=html.escape(full_title), description=html.escape(description or
                "Cabby: a small, natively compiled language with a quiet syntax and Rust-style ownership."),
            nav=nav, sidebar=f'<nav class="sidebar" aria-label="In this section">{sidebar}</nav>' if sidebar else "",
            content=content, layout_class=layout_class, body_class=body_class,
            version=self.version, version_date=self.version_date, tag=self.tag, github=GITHUB))

    # ------------------------------------------------------------ the manual

    def build_manual(self):
        src = (self.cabby / "tutorials/tutorials.md").read_text()
        full = md_to_html(src)
        # cut the book at its parts (h2) and chapters (h3)
        pieces = re.split(r'(?=<h[23] id=")', full)
        front, pages, part, pending_part, started = "", [], "", "", False
        for piece in pieces:
            m = re.match(r'<h([23]) id="([^"]+)">(.*?)</h\1>', piece, re.S)
            if m and m.group(1) == "2" and m.group(3).startswith("Part "):
                started = True
            if not started or not m:
                if started and pages:
                    pages[-1]["html"] += piece
                else:
                    front += piece
                continue
            level, hid, htext = m.groups()
            text = re.sub(r"<[^>]+>", "", htext)
            if level == "2":
                part = html.unescape(text)
                pending_part += piece
                continue
            slug = re.sub(r"^(chapter|appendix)-([0-9a-z]+)-.*$", r"\1-\2", hid)
            pages.append({"slug": slug, "title": html.unescape(text), "part": part,
                          "html": pending_part + piece})
            pending_part = ""
        for p in pages:
            for hid in re.findall(r'id="([^"]+)"', p["html"]):
                self.manual_ids[hid] = p["slug"]

        def sidebar(current):
            out, last_part = ['<a class="sidebar-home" href="/docs/manual/">The Cabby Manual</a>'], None
            for p in pages:
                if p["part"] != last_part:
                    if last_part is not None:
                        out.append("</ol>")
                    open_ = " open" if any(q["part"] == p["part"] and q["slug"] == current for q in pages) else ""
                    out.append(f'<p class="sidebar-part{open_}">{html.escape(p["part"])}</p><ol>')
                    last_part = p["part"]
                cur = ' aria-current="page"' if p["slug"] == current else ""
                short = re.sub(r"^(Chapter|Appendix) [0-9A-Z]+: ", "", p["title"])
                num = re.match(r"^(?:Chapter|Appendix) ([0-9A-Z]+)", p["title"])
                n = f'<span class="num">{num.group(1)}</span>' if num else ""
                out.append(f'<li><a href="/docs/manual/{p["slug"]}/"{cur}>{n}{html.escape(short)}</a></li>')
            out.append("</ol>")
            return "".join(out)

        front_ids = set(re.findall(r'id="([^"]+)"', front))
        front_html = self.render(self.fix_links(front, "tutorials/tutorials.md", front_ids), "tutorials/tutorials.md")
        self.write("/docs/manual/", "The Cabby Manual", f'<article class="prose">{front_html}</article>',
                   section="docs", sidebar=sidebar(None),
                   description="The Cabby Manual: learn Cabby one idea at a time.")
        for i, p in enumerate(pages):
            ids = set(re.findall(r'id="([^"]+)"', p["html"]))
            body = self.render(self.fix_links(p["html"], "tutorials/tutorials.md", ids), "tutorials/tutorials.md")
            prev_ = pages[i - 1] if i else None
            next_ = pages[i + 1] if i + 1 < len(pages) else None
            pager = '<nav class="pager">'
            pager += (f'<a class="prev" href="/docs/manual/{prev_["slug"]}/"><small>Previous</small>{html.escape(prev_["title"])}</a>'
                      if prev_ else '<a class="prev" href="/docs/manual/"><small>Previous</small>Contents</a>')
            if next_:
                pager += f'<a class="next" href="/docs/manual/{next_["slug"]}/"><small>Next</small>{html.escape(next_["title"])}</a>'
            pager += "</nav>"
            crumbs = f'<p class="crumbs"><a href="/docs/manual/">The Cabby Manual</a> · {html.escape(p["part"])}</p>'
            self.write(f"/docs/manual/{p['slug']}/", p["title"],
                       f'<article class="prose">{crumbs}{body}{pager}</article>',
                       section="docs", sidebar=sidebar(p["slug"]))
        self.manual_pages = pages

    # --------------------------------------------- single-page documents

    def build_document(self, source, url, title, *, toc_level="2", description=""):
        body = self.render(md_to_html((self.cabby / source).read_text()), source)
        heads = re.findall(rf'<h{toc_level} id="([^"]+)">(.*?)</h{toc_level}>', body, re.S)
        side = "".join(f'<li><a href="#{hid}">{re.sub(r"<[^>]+>", "", t)}</a></li>' for hid, t in heads)
        sidebar = f'<a class="sidebar-home" href="{url}">{html.escape(title)}</a><ol class="toc">{side}</ol>' if heads else ""
        self.write(url, title, f'<article class="prose">{body}</article>', section="docs",
                   sidebar=sidebar, description=description)

    def build_libraries(self):
        names = sorted(p.stem for p in (self.cabby / "lib").glob("*.md"))
        for name in names:
            text = (self.cabby / "lib" / f"{name}.md").read_text()
            m = re.match(r"#\s+(\S+)\s+[—-]+\s+(.*)", text)
            desc = m.group(2).strip() if m else ""
            self.libraries.append((name, desc))
        side = '<a class="sidebar-home" href="/docs/libraries/">Libraries</a><ol class="toc">' + "".join(
            f'<li><a href="/docs/libraries/{n}/"{{cur_{n}}}>{n}</a></li>' for n, _ in self.libraries) + "</ol>"
        for name, desc in self.libraries:
            source = f"lib/{name}.md"
            body = self.render(md_to_html((self.cabby / source).read_text()), source)
            sidebar = re.sub(r"\{cur_(\w+)\}", lambda m: ' aria-current="page"' if m.group(1) == name else "", side)
            self.write(f"/docs/libraries/{name}/", f"{name} library", f'<article class="prose">{body}</article>',
                       section="docs", sidebar=sidebar, description=f"Cabby's {name} library: {desc}")
        cards = "".join(
            f'<a class="lib" href="/docs/libraries/{n}/"><code>use {n}</code><span>{self.inline(d)}</span></a>'
            for n, d in self.libraries)
        intro = ('<h1>Libraries</h1><p class="lead">Each library has a page with everything there is to know about it. '
                 'Bring one into a program with <code>use</code> and its name.</p>')
        self.write("/docs/libraries/", "Libraries", f'<article class="prose wide">{intro}<div class="libs">{cards}</div></article>',
                   section="docs")

    @staticmethod
    def inline(text):
        """`code` in a one-line description."""
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text, quote=False))

    # ----------------------------------------------- hand-written pages

    def page(self, name):
        text = (HERE / "pages" / name).read_text()

        def code(m):
            src = (HERE / "pages" / "snippets" / m.group(1)).read_text().rstrip("\n")
            return f'<pre class="cabby"><code>{html.escape(src, quote=False)}</code></pre>'
        text = re.sub(r"\{\{code:([\w.-]+)\}\}", code, text)
        text = re.sub(r"\{\{raw:([\w.-]+)\}\}", lambda m: html.escape(
            (HERE / "pages" / "snippets" / m.group(1)).read_text().rstrip("\n"), quote=False), text)
        text = re.sub(r"\{\{(version|version_date|tag)\}\}", lambda m: str(getattr(self, m.group(1))), text)
        return self.hl.html_blocks(text)

    def build_docs_home(self):
        chapters = sum(1 for p in self.manual_pages if p["slug"].startswith("chapter-"))
        content = self.page("docs.html").replace("{{chapters}}", str(chapters)).replace(
            "{{library_count}}", str(len(self.libraries)))
        self.write("/docs/", "Documentation", content, section="docs")

    def build_download(self):
        assets = self.release.get("assets", [])

        def find(pattern):
            for a in assets:
                if re.search(pattern, a["name"]):
                    return a
            return None

        def size(a):
            return f'{a["size"] / 1_000_000:.1f} MB'

        def sha(a):
            d = a.get("digest") or ""
            return f'<p class="sha">SHA-256 <code>{html.escape(d.split(":", 1)[-1])}</code></p>' if d.startswith("sha256:") else ""

        v, tag = self.version, self.tag
        source_tgz = f"{GITHUB}/archive/refs/tags/{tag}.tar.gz"
        source_zip = f"{GITHUB}/archive/refs/tags/{tag}.zip"
        deb, arch = find(r"\.deb$"), find(r"\.pkg\.tar\.zst$")
        mac = find(r"(?i)(macos|darwin|apple|arm64).*\.(tar\.gz|zip|pkg|dmg)$")

        cards = []
        if deb:
            cards.append(f'''
<section class="dl" id="debian">
  <h2><img src="/assets/os-debian.svg" alt="" width="28" height="28">Debian and Ubuntu</h2>
  <p>A <code>.deb</code> package for 64-bit Intel and AMD computers. <code>apt</code> installs what it needs with it.</p>
  <a class="button" href="{deb["browser_download_url"]}">Download {html.escape(deb["name"])}</a> <span class="size">{size(deb)}</span>
  <pre class="code sh"><code>wget {deb["browser_download_url"]}
sudo apt install ./{html.escape(deb["name"])}</code></pre>
  <p class="small">Remove it with <code>sudo apt remove cabby</code>.</p>{sha(deb)}
</section>''')
        if arch:
            cards.append(f'''
<section class="dl" id="arch">
  <h2><img src="/assets/os-arch.svg" alt="" width="28" height="28">Arch Linux</h2>
  <p>A <code>pacman</code> package for x86_64. <code>pacman</code> can install it straight from its address.</p>
  <a class="button" href="{arch["browser_download_url"]}">Download {html.escape(arch["name"])}</a> <span class="size">{size(arch)}</span>
  <pre class="code sh"><code>sudo pacman -U {arch["browser_download_url"]}</code></pre>
  <p class="small">Remove it with <code>sudo pacman -R cabby</code>.</p>{sha(arch)}
</section>''')
        if mac:
            mac_body = f'''<a class="button" href="{mac["browser_download_url"]}">Download {html.escape(mac["name"])}</a> <span class="size">{size(mac)}</span>{sha(mac)}'''
        else:
            mac_body = f'''<p>For Macs with an Apple processor. Cabby builds itself into a Homebrew formula of its own and
  installs from it, so <code>brew upgrade</code> and <code>brew uninstall</code> look after it. You need
  <a href="https://brew.sh">Homebrew</a> and Apple's Command Line Tools (<code>xcode-select --install</code>).</p>
  <pre class="code sh"><code>curl -L {source_tgz} | tar xz
cd cabby-{v}
packaging/homebrew/build-tap.sh</code></pre>
  <p class="small">Remove it with <code>brew uninstall cabby</code>, then <code>brew untap cabby/local</code>.</p>'''
        cards.append(f'''
<section class="dl" id="mac">
  <h2><img src="/assets/os-apple.svg" alt="" width="28" height="28">Mac</h2>
  {mac_body}
</section>''')
        cards.append(f'''
<section class="dl" id="source">
  <h2><img src="/assets/os-source.svg" alt="" width="28" height="28">Source code</h2>
  <p>Cabby {v} as it was released, to read, build or change. MIT License.</p>
  <a class="button" href="{source_tgz}">Download .tar.gz</a> <a class="button secondary" href="{source_zip}">Download .zip</a>
  <pre class="code sh"><code>curl -L {source_tgz} | tar xz
cd cabby-{v}
make
sudo make install</code></pre>
  <p class="small">Or follow it as it grows: <a href="{GITHUB}">{REPO} on GitHub</a>.</p>
</section>''')
        released = (self.release.get("published_at") or self.version_date)[:10]
        notes = self.release.get("html_url") or f"{GITHUB}/releases"
        content = f'''
<div class="page-head">
  <h1>Download Cabby</h1>
  <p class="lead">Cabby {v}, released {released}. <a href="{notes}">Release notes</a> ·
  <a href="/docs/timeline/">What each version brought</a> · <a href="{GITHUB}/releases">Earlier versions</a></p>
</div>
<div class="downloads">{"".join(cards)}</div>
<section class="after">
  <h2>Check it worked</h2>
  <pre class="code sh"><code>cabby --version</code></pre>
  <p>It should say <code>Cabby {v} ({self.version_date})</code>. Then type <code>cabby</code> for the interactive session,
  or read <a href="/docs/manual/chapter-1/">Chapter 1 of the manual</a>.</p>
</section>'''
        self.write("/download/", "Download", content, section="download",
                   description=f"Download Cabby {v} for Debian, Arch Linux and the Mac, or get the source code.")

    def build(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        shutil.copytree(HERE / "assets", self.out / "assets")
        shutil.copy(self.cabby / "icons/cabby.svg", self.out / "assets/cabby.svg")
        shutil.copy(self.cabby / "icons/cabby.svg", self.out / "favicon.svg")
        self.build_manual()
        self.build_document("README.md", "/docs/reference/", "Language reference",
                            description="The Cabby language reference, section by section.")
        self.build_document("STYLE.md", "/docs/style/", "Style guide",
                            description="How to name things and lay out Cabby code.")
        self.build_document("TIMELINE.md", "/docs/timeline/", "Timeline",
                            description="What each version of Cabby brought.")
        self.build_document("tutorials/README.md", "/docs/tutorials/", "Tutorial programs",
                            description="The runnable tutorial programs that go with the manual.")
        self.build_libraries()
        self.build_docs_home()
        self.build_download()
        self.write("/", "Cabby", self.page("index.html"), section="home", body_class="home")
        self.write("/playground/", "Playground", self.page("playground.html"), section="playground",
                   description="Run Cabby in your browser.")
        self.write("/404.html", "Not found", self.page("404.html"))
        (self.out / ".nojekyll").write_text("")
        count = sum(1 for _ in self.out.rglob("*.html"))
        print(f"built Cabby {self.version} ({self.tag}): {count} pages in {self.out}")


def load_release(path):
    if path:
        return json.loads(Path(path).read_text())
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:  # the site still builds, with the source download only
        print(f"warning: couldn't read the latest release ({e})", file=sys.stderr)
        return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cabby", default="cabby", help="the cabby repository, at the version to publish")
    ap.add_argument("--out", default="_site", help="where the site goes")
    ap.add_argument("--release", help="the GitHub release, as JSON (default: fetch the latest)")
    a = ap.parse_args()
    Site(Path(a.cabby).resolve(), Path(a.out).resolve(), load_release(a.release)).build()


if __name__ == "__main__":
    main()
