# Embedded HTML/CSS and editorial text retain readable source lines.
# ruff: noqa: E501
"""Render the repository manual as a portable HTML reader with embedded figures."""

import argparse
import base64
import html
import os
import re
import struct
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/manual-usuario"
CHAPTERS = [
    "README.md",
    "01-acceso.md",
    "02-talla-y-peso.md",
    "03-encuestas.md",
    "04-nutrir.md",
]

CSS = """
summary{cursor:pointer;font-weight:650;padding:12px 0}pre{overflow:auto;max-width:100%;padding:18px;background:#eee8da;border-radius:7px}main,article{min-width:0}td,th,code,a{overflow-wrap:anywhere}table{max-width:100%}

:root{--paper:#f6f3ea;--ink:#292a23;--green:#283e30;--sage:#e9eedf;--line:#ddd6c6;--muted:#666859;--gold:#bd952b}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:28px}body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.75 system-ui,-apple-system,sans-serif}
aside{position:fixed;inset:0 auto 0 0;width:260px;padding:38px 24px;background:var(--green);color:var(--paper);overflow:auto}aside .brand{font:700 38px Georgia,serif;letter-spacing:-2px}aside small{display:block;font-size:11px;letter-spacing:1.5px;margin:6px 0 24px;text-transform:uppercase;color:#d7dfc8}aside a{display:block;padding:10px 12px;margin:5px 0;border-radius:7px;text-decoration:none;color:inherit;font-size:14px;line-height:1.5}aside a:hover,aside a:focus{background:#40513b}aside input{width:100%;padding:11px;border:1px solid #91a18a;background:transparent;color:white;border-radius:6px;margin-bottom:18px}aside input::placeholder{color:#d7dfc8}
main{margin-left:260px;padding:60px 5vw 100px;max-width:1450px}article{max-width:960px;margin:auto}section.chapter{padding-top:32px;margin-top:55px;border-top:2px solid var(--gold)}section.chapter:first-child{border:0;margin:0;padding:0}h1,h2,h3{font-family:Georgia,serif;line-height:1.2;letter-spacing:-.5px}h1{font-size:48px;color:var(--green);margin:0 0 30px}h2{font-size:29px;margin:54px 0 22px;scroll-margin-top:28px}h3{font-size:23px;margin-top:34px}p,li{max-width:78ch}a{color:#356143;text-underline-offset:4px}strong{font-weight:650}li{padding-left:3px;margin:9px 0}table{border-collapse:collapse;width:100%;font-size:15px;margin:28px 0;background:#fffdf6}th,td{text-align:left;vertical-align:top;padding:15px;border-bottom:1px solid var(--line)}th{background:var(--sage);font-size:13px}figure{margin:36px 0 46px;padding:18px;background:#fffdf7;border:1px solid var(--line);border-radius:13px;break-inside:avoid}figure img{display:block;width:100%;height:auto;margin:auto;border-radius:6px;cursor:zoom-in}figure.mobile img{width:328px;max-width:100%;height:auto;box-shadow:0 3px 18px #292a2314}figcaption{color:var(--muted);font-size:13px;line-height:1.5;padding:17px 2px 0}figcaption b{font-size:10px;letter-spacing:1px;background:var(--sage);padding:4px 6px;border-radius:4px;margin-right:8px}blockquote{border-left:3px solid var(--gold);padding:12px 22px;background:#eee8d5;margin:26px 0}code{font-size:.86em;background:#ebe6d9;padding:2px 5px;border-radius:3px}footer{padding-top:30px;margin-top:55px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}dialog{border:0;padding:16px;background:var(--paper);max-width:96vw;max-height:96vh;border-radius:10px}dialog::backdrop{background:#101a16d9}dialog img{display:block;max-width:90vw;max-height:84vh;object-fit:contain}dialog button{float:right;font:inherit;border:1px solid var(--line);border-radius:5px;padding:5px 12px;background:white;margin-bottom:10px}.toolbar button{border:1px solid var(--line);padding:8px 14px;border-radius:6px;background:#fffdf6;color:var(--green);cursor:pointer;font:inherit;font-size:13px}.toolbar{display:flex;justify-content:flex-end;margin-bottom:24px}.matched{outline:3px solid var(--gold);outline-offset:8px}
@media(max-width:850px){aside{position:static;width:auto;padding:22px}aside nav{display:flex;flex-wrap:wrap}aside a{margin:0;padding:8px}aside input{max-width:360px}main{margin:0;padding:28px 20px}h1{font-size:36px}h2{font-size:26px}table{display:block;overflow:auto}figure{padding:10px}}
@media print{body{background:white;font-size:10pt}aside,.toolbar,dialog{display:none}main{margin:0;padding:0;max-width:none}section.chapter{break-before:page}section.chapter:first-child{break-before:auto}h1{font-size:28pt}h2{font-size:17pt;break-after:avoid}figure{max-height:245mm;padding:8px;box-shadow:none}figure.mobile img{max-height:185mm}figure img{max-height:175mm;object-fit:contain}a{color:inherit;text-decoration:none}th,td{padding:7px;font-size:9pt}}
"""


def render(output, linked_assets=False):
    chapters, nav, embedded = [], [], set()
    converter = markdown.Markdown(extensions=["tables", "fenced_code", "toc"])

    def image_source(image, raw):
        if linked_assets:
            relative = Path(os.path.relpath(image, output.parent)).as_posix()
            return html.escape(relative, quote=True)
        return "data:image/png;base64," + base64.b64encode(raw).decode()

    for index, filename in enumerate(CHAPTERS):
        source = (SOURCE / filename).read_text()
        converter.reset()
        body = converter.convert(source)
        # Prefix heading anchors so chapter-local names never collide.
        body = re.sub(r'id="([^"]+)"', lambda m: f'id="c{index}-{m[1]}"', body)
        title = source.splitlines()[0].removeprefix("# ")
        anchor = f"chapter-{index}"
        nav.append(f'<a href="#{anchor}">{html.escape(title)}</a>')

        def embed(match):
            alt, src = match[1], match[2]
            image = SOURCE / src
            if not image.is_file():
                raise RuntimeError(f"Missing figure: {image}")
            raw = image.read_bytes()
            src = image_source(image, raw)
            width, height = struct.unpack(">II", raw[16:24])
            embedded.add(image.name)
            mobile = "app-" in image.name
            caption = html.escape(html.unescape(alt))
            return (
                f'<figure id="captura-{image.stem}" class="{"mobile" if mobile else "web"}"><img src="{src}" '
                f'alt="{alt}" width="{width}" height="{height}" tabindex="0" role="button" aria-label="Ampliar: {alt}" loading="lazy">'
                f"<figcaption><b>{'APP ANDROID' if mobile else 'BACKOFFICE'}</b>{caption}</figcaption></figure>"
            )

        body = re.sub(r'<img alt="([^"]*)" src="([^"]+)"\s*/?>', embed, body)
        chapters.append(f'<section class="chapter" id="{anchor}">{body}</section>')

    def local_link(match):
        target = match[1]
        if target in CHAPTERS:
            return f'href="#chapter-{CHAPTERS.index(target)}"'
        return match[0]

    body = re.sub(r'href="([^"]+\.md)"', local_link, "".join(chapters))
    gallery = []
    for image in sorted((SOURCE / "assets").glob("*.png")):
        if image.name in embedded:
            continue
        raw = image.read_bytes()
        src = image_source(image, raw)
        width, height = struct.unpack(">II", raw[16:24])
        caption = html.escape(image.stem.replace("-", " "))
        gallery.append(
            f'<figure id="captura-{image.stem}" class="{"mobile" if image.stem.startswith("app-") else "web"}">'
            f'<img src="{src}" alt="{caption}" width="{width}" height="{height}" loading="lazy" tabindex="0" role="button" aria-label="Ampliar: {caption}">'
            f"<figcaption>{caption}</figcaption></figure>"
        )
    body += (
        '<section class="chapter" id="galeria"><details><summary>Galería de capturas adicionales</summary>'
        + "".join(gallery)
        + "</details></section>"
    )
    body = re.sub(r'href="assets/([^"/]+)\.png"', r'href="#captura-\1"', body)
    body = re.sub(r'href="([^"]+\.md)"', local_link, body)
    document = (
        f'<!doctype html><html lang="es-AR"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>Raíz · Manual de usuario</title>'
        f'<style>{CSS}</style></head><body><aside><div class="brand">Raíz</div>'
        '<small>Manual de usuario · App + Web</small><label for="search">Buscar un tema</label>'
        '<input id="search" type="search" placeholder="Ej.: sincronizar" autocomplete="off">'
        f'<nav aria-label="Capítulos">{"".join(nav)}</nav></aside><main>'
        '<div class="toolbar"><button onclick="window.print()">Imprimir</button></div>'
        f"<article>{body}<footer>Ingeniería Para la Alimentación · Edición de trabajo 25/10/2026 · Datos de demostración</footer>"
        '</article></main><dialog aria-label="Captura ampliada"><button type="button">Cerrar</button><img alt=""></dialog>'
        '<script>const dialog=document.querySelector("dialog");'
        'function reveal(n){for(let p=n;p;p=p.parentElement){if(p.tagName==="DETAILS")p.open=true}const d=n.querySelector(":scope > details");if(d)d.open=true}'
        'document.querySelectorAll("a[href^=\\"#\\"]").forEach(a=>a.addEventListener("click",()=>{const n=document.getElementById(a.hash.slice(1));if(n)reveal(n)}));'
        'function zoom(img){dialog.querySelector("img").src=img.src;dialog.querySelector("img").alt=img.alt;dialog.showModal()}'
        'document.querySelectorAll("figure img").forEach(img=>{img.onclick=()=>zoom(img);img.onkeydown=e=>{if(e.key==="Enter")zoom(img)}});'
        'dialog.querySelector("button").onclick=()=>dialog.close();'
        'document.getElementById("search").onkeydown=e=>{if(e.key!=="Enter")return;document.querySelectorAll(".matched").forEach(n=>n.classList.remove("matched"));'
        'const q=e.target.value.trim().toLocaleLowerCase("es");if(!q)return;const hit=Array.from(document.querySelectorAll("h2,h3,p,li")).find(n=>n.textContent.toLocaleLowerCase("es").includes(q));'
        'if(hit){reveal(hit);hit.classList.add("matched");hit.scrollIntoView({block:"center"})}};'
        "</script></body></html>"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document)
    print(f"Rendered {output} ({len(document):,} characters)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".context/manual/manual.html"
    )
    parser.add_argument(
        "--linked-assets",
        action="store_true",
        help="Reference repository images instead of embedding them in the HTML",
    )
    args = parser.parse_args()
    render(args.output, linked_assets=args.linked_assets)
