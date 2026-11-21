# cabby-lang.github.io

The website for [Cabby](https://github.com/cabby-lang/cabby), published at
<https://cabby-lang.github.io>.

Everything the site says about the language is built from the Cabby
repository at its latest release: the manual (`tutorials/tutorials.md`, a
page per chapter), the language reference (`README.md`), the library pages
(`lib/*.md`), the style guide, the timeline and the cabbage logo. So the
docs always match the version people download, and nothing here needs
changing when Cabby does.

| Here | What it is |
|---|---|
| `build.py` | builds the site into `_site/` |
| `layout.html` | the frame around every page: top bar, sidebar, footer |
| `pages/` | the hand-written pages: home, docs, the playground (`playground-live.html`, and `playground.html` for when there's no interpreter), 404, and the code shown on the home page (`pages/snippets/`) |
| `assets/` | the look (`style.css`), copy buttons and the phone menu (`site.js`), icons |
| `.github/workflows/pages.yml` | builds and publishes the site |

## Publishing

GitHub Actions builds and publishes the site when this repository
changes, and once a day, so a new Cabby release appears within a day by
itself. To publish one straight away: **Actions → Publish the site → Run
workflow**.

The Download page comes from the release itself: its `.deb` and
`.pkg.tar.zst` files, their sizes and SHA-256 checksums, and the source
archives. A Mac file, once a release has one (a name with `macos`,
`darwin` or `arm64` in it), appears there too.

## The playground

The playground runs Cabby's own interpreter, built for WebAssembly by
Cabby's `make wasm-site` (`wasm/README.md` in the Cabby repository). The
workflow builds it from the release with wasi-sdk 32; its examples are the
ones in Cabby's `wasm/index.html`. If a release can't be built for it, the
site is still published, and the Playground page says it's coming.

With the playground there, whole programs in the docs (those with a `main`,
that don't use a library a browser hasn't) get a **Try it** button that
opens them in it. A program can be shared as a link: it travels in the
address (`/playground/#code=...`), so nothing is stored anywhere.

## Building it yourself

Needs Python 3 and pandoc (`sudo pacman -S pandoc`, `sudo apt install pandoc`,
`brew install pandoc`).

    git clone https://github.com/cabby-lang/cabby
    python3 build.py --cabby cabby --out _site
    cd _site && python3 -m http.server 8000

Then open <http://localhost:8000>. Without `--release release.json` it reads
the latest release from GitHub. For the playground, build Cabby for
WebAssembly first and add `--wasm`:

    make -C cabby wasm-site
    python3 build.py --cabby cabby --out _site --wasm cabby/build/wasm-site

## Your own domain, later

Buy the name, then in **Settings → Pages → Custom domain** type it in and
add the DNS records GitHub shows. All the site's links start at `/`, so
nothing else changes.
