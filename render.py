"""HTML rendering: base template extracted 1:1 from the deployed wiki pages."""

import os
import html as H

TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_CSS = open(os.path.join(TEMPLATE_DIR, "render", "base.css"), encoding="utf-8").read()


def esc(s):
    return H.escape(str(s if s is not None else ""))


def fmt_context(n):
    return f"{n:,}".replace(",", "&thinsp;") if n else "—"


ICONS = {
    "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    "bench": '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    "list": '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="18" y2="18"/>',
    "router": '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/><line x1="12" y1="12" x2="20" y2="12"/><line x1="12" y1="5" x2="20" y2="5"/>',
}

PAGES = [
    ("index.html", "Home", "home"),
    ("comparisons-benchmarks.html", "Benchmarks — Free Roster vs Paid Frontier", "bench"),
    ("comparisons-free-models-ranking.html", "Free Models — Ranked by Use Case", "list"),
    ("comparisons-router-changelog.html", "Router — Model Chain Changes", "router"),
]


def page(title, active, body, generated_at, extra_head=""):
    nav = []
    for href, label, icon in PAGES:
        cur = " active" if href == active else ""
        aria = ' aria-current="page"' if href == active else ""
        nav.append(
            f'<a href="{href}" class="nav-link{cur}"{aria} title="{esc(label)}">'
            f'<span class="nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" width="18" height="18">{ICONS[icon]}</svg></span>'
            f'<span class="nav-title">{esc(label)}</span></a>')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — Hermes Model Wiki</title>
<meta name="description" content="Free-tier AI model knowledge base — benchmarks, rankings, and config guides for Hermes Agent">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{BASE_CSS}</style>
{extra_head}
</head>
<body>
<a class="skip-link" href="#main-content">Skip to content</a>
<aside class="sidebar" id="sidebar">
  <div class="sidebar-brand"><a href="index.html">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
    <span>Hermes Wiki</span></a>
  </div>
  <div class="search-wrap"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>  <input class="search-input" id="search-input" type="search" placeholder="Filter pages…" aria-label="Filter wiki pages"></div>
  <nav class="sidebar-nav" aria-label="Wiki pages">
{''.join(nav)}
  </nav>
</aside>
<header class="header" role="banner">
  <button class="nav-toggle" aria-label="Toggle navigation" aria-expanded="false" aria-controls="sidebar">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="22" height="22"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>  </button>
  <a class="htitle" href="index.html">Hermes Model Wiki</a>
  <div class="header-meta"><time datetime="{generated_at[:10]}">{generated_at[:10]}</time></div>
</header>
<main class="main" role="main" id="main-content">
{body}
  <footer class="footer">Generated {generated_at} · Auto-refreshes daily · Powered by Hermes</footer>
</main>
<script>
document.querySelector('.nav-toggle').addEventListener('click',function(){{
  var s=document.getElementById('sidebar');s.classList.toggle('open');
  this.setAttribute('aria-expanded',s.classList.contains('open'));
}});
document.addEventListener('DOMContentLoaded',function(){{
  var input=document.getElementById('search-input');
  if(!input)return;
  input.addEventListener('input',function(){{
    var q=this.value.toLowerCase().trim();
    document.querySelectorAll('.nav-link').forEach(function(link){{
      var title=link.querySelector('.nav-title');
      if(!title){{link.classList.remove('hidden');return}}
      var txt=title.textContent.toLowerCase();
      if(!q||txt.indexOf(q)!==-1)link.classList.remove('hidden');
      else link.classList.add('hidden');
    }});
  }});
}});
</script>
</body>
</html>"""


def table(headers, rows, cls=""):
    th = "".join(f"<th>{h}</th>" for h in headers)
    trs = "".join(f"<tr>{''.join(f'<td>{c}</td>' for c in r)}</tr>" for r in rows)
    # fixed score column: identical width in ALL tables for visual alignment
    if len(headers) == 2:
        colgroup = '<col style="width:auto"><col style="width:22ch">'
    elif len(headers) == 4:  # summary table: Use case | Model | Why | Score
        colgroup = ('<col style="width:auto"><col style="width:auto">'
                    '<col style="width:auto"><col style="width:22ch">')
    else:
        colgroup = ""
    return (f'<div class="table-wrap {cls}"><table>{colgroup}<thead><tr>{th}</tr></thead>'
            f'<tbody>{trs}</tbody></table></div>')


BADGES = {
    "price-0": '<span class="badge badge-free">$0</span>',
    "zen-free": '<span class="badge badge-zen">zen free</span>',
    "plan": '<span class="badge badge-plan">in-plan</span>',
}


def model_rows(models, show_desc=True):
    rows = []
    for m in models:
        cells = [
            " + ".join(m["sources"]),
            f'<code>{esc(m["display_id"])}</code>',
            esc(m["name"]),
            BADGES.get(m.get("free_basis"), ""),
            fmt_context(m.get("context_length")),
            esc(m.get("modalities", "text")),
        ]
        if show_desc:
            desc = m.get("description") or "—"
            cells.append(f'<span class="desc">{esc(desc)}</span>')
        rows.append(cells)
    return rows
