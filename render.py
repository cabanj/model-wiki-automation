"""Shared HTML rendering for the model wiki."""

import os
import html as H
from datetime import datetime

TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_CSS = open(os.path.join(TEMPLATE_DIR, "render", "base.css"), encoding="utf-8").read()


def esc(s):
    return H.escape(str(s if s is not None else ""), quote=True)


def fmt_ts(ts):
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts[:16].replace("T", " ")


def fmt_context(n):
    return f"{n:,}".replace(",", "&thinsp;") if n else "—"


ICONS = {
    "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    "bench": '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    "list": '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
}

PAGES = [
    ("index.html", "Home", "home"),
    ("comparisons-benchmarks.html", "Benchmarks", "bench"),
    ("comparisons-free-models-ranking.html", "Free models", "list"),
]

SITE_CONFIG = {
    "site_url": "https://llmroster.dev",  # Canonical site URL; drives canonical/og:url/RSS links.
    "support_url": "https://ko-fi.com/jacekcaban",  # Optional GitHub Sponsors/Buy Me a Coffee URL.
    "support_label": "Support",
    "support_blurb": "Free to run, no ads. If it saved you money, consider a tip.",
}


def support_link():
    """Sidebar support link, or '' when support_url is unset."""
    if not SITE_CONFIG["support_url"]:
        return ""
    url = SITE_CONFIG["support_url"]
    label = SITE_CONFIG["support_label"]
    return (f'<a class="support-link" href="{esc(url)}" target="_blank" rel="noopener noreferrer">'
            f'<span class="nav-icon"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="1.7" width="18" height="18">'
            f'<path d="M12 21s-7-4.5-9-8.5A5 5 0 0 1 12 6a5 5 0 0 1 9 6.5C19 16.5 12 21 12 21z"/></svg></span>'
            f'<span class="nav-title">{esc(label)}</span></a>')


def site_url(path=""):
    """Absolute URL for a site-relative path, or "" when site_url is unset."""
    base = SITE_CONFIG["site_url"].rstrip("/")
    if not base:
        return ""
    return f"{base}/{path.lstrip('/')}" if path else base


def meta_tags():
    """Canonical link, Open Graph URL and absolute RSS alternate, or '' when unconfigured."""
    base = site_url()
    if not base:
        return ""
    return (
        f'<link rel="canonical" href="{esc(base)}">'
        f'<meta property="og:url" content="{esc(base)}">'
        f'<meta property="og:site_name" content="llmroster.dev">'
        f'<link rel="alternate" type="application/rss+xml" '
        f'title="LLM Roster — Model Changes" href="{esc(site_url("feed.xml"))}">'
    )

PROVIDER_CONFIG = {
    "openrouter": {
        "label": "OpenRouter",
        "url": "https://openrouter.ai/?ref=YOUR_REF_CODE",
        "keys_url": "https://openrouter.ai/keys?ref=YOUR_REF_CODE",
        "configured": False,
    },
    "nous": {
        "label": "Nous Portal",
        "url": "https://portal.nousresearch.com/?ref=YOUR_REF_CODE",
        "keys_url": "https://inference.nousresearch.com/?ref=YOUR_REF_CODE",
        "configured": False,
    },
    "opencode-zen": {
        "label": "OpenCode Zen",
        "url": "https://opencode.ai/zen?ref=YOUR_REF_CODE",
        "keys_url": "https://opencode.ai/zen?ref=YOUR_REF_CODE",
        "configured": False,
    },
}


def external_link(label, url, sponsored=False):
    rel = "noopener noreferrer sponsored" if sponsored else "noopener noreferrer"
    return f'<a href="{esc(url)}" target="_blank" rel="{rel}">{esc(label)}</a>'


def model_id(value, model_name=""):
    value = str(value or "")
    label = f"Copy model ID: {value}"
    return (f'<span class="model-id-wrap"><code class="model-id">{esc(value)}</code>'
            f'<button type="button" class="copy-button" data-copy-value="{esc(value)}" '
            f'aria-label="{esc(label)}" title="Copy model ID"><span aria-hidden="true">Copy</span></button>'
            f'</span>')


def page(title, active, body, generated_at, extra_head=""):
    nav = []
    for href, label, icon in PAGES:
        cur = " active" if href == active else ""
        aria = ' aria-current="page"' if href == active else ""
        nav.append(
            f'<a href="{href}" class="nav-link{cur}"{aria} title="{esc(label)}">'
            f'<span class="nav-icon"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.7" width="18" height="18">{ICONS[icon]}</svg></span>'
            f'<span class="nav-title">{esc(label)}</span></a>')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — LLM Roster</title>
<meta name="description" content="Free-tier AI model directory — benchmarks, rankings, and practical model insights">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
{meta_tags()}
<style>{BASE_CSS}</style>
{extra_head}
</head>
<body>
<a class="skip-link" href="#main-content">Skip to content</a>
<aside class="sidebar" id="sidebar">
  <div class="sidebar-brand"><a href="index.html">
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
    <span>LLM Roster</span></a>
  </div>
  <nav class="sidebar-nav" aria-label="LLM Roster pages">
    <div class="nav-section">Explore</div>
    {''.join(nav)}
  </nav>
  <div class="sidebar-support">
    {support_link()}
    <p class="support-blurb">{esc(SITE_CONFIG['support_blurb'])}</p>
  </div>
</aside>
<div class="nav-backdrop" id="nav-backdrop" aria-hidden="true"></div>
<header class="header" role="banner">
  <button class="nav-toggle" aria-label="Open navigation" aria-expanded="false" aria-controls="sidebar">
<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="22" height="22"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
  </button>
  <a class="htitle" href="index.html">LLM Roster</a>
  <div class="header-meta"><span>Model intelligence</span><time datetime="{esc(generated_at)}">{fmt_ts(generated_at)}</time></div>
  <div class="header-links"><span class="header-link-label"><a href="https://runpod.io?ref=zkpkr4fe" target="_blank" rel="noopener noreferrer sponsored">RunPod</a> &mdash; affiliate link</span></div>
</header>
<main class="main" role="main" id="main-content">
  {body}
  <footer class="footer">
    <div class="footer-links"><a href="feed.xml">Model changes feed</a><a href="privacy.html">Privacy</a><a href="contact.html">Contact</a></div>
    <div>Generated {fmt_ts(generated_at)} · Sources refresh daily · Paid proxy scores are labelled explicitly</div>
  </footer>
  <div class="sr-only" aria-live="polite" data-copy-status></div>
</main>
<script>
(function(){{
  var toggle=document.querySelector('.nav-toggle');
  var sidebar=document.getElementById('sidebar');
  var backdrop=document.getElementById('nav-backdrop');
  var mobile=window.matchMedia('(max-width:1024px)');
  var open=false;
  function setOpen(next){{
    open=next;
    sidebar.classList.toggle('open',open);
    backdrop.classList.toggle('visible',open);
    toggle.setAttribute('aria-expanded',String(open));
    toggle.setAttribute('aria-label',open?'Close navigation':'Open navigation');
    if(mobile.matches&&!open){{sidebar.setAttribute('inert','');sidebar.setAttribute('aria-hidden','true')}}
    else{{sidebar.removeAttribute('inert');sidebar.removeAttribute('aria-hidden')}}
    if(open){{var first=sidebar.querySelector('a');if(first)first.focus()}}
  }}
  function syncViewport(){{if(!mobile.matches){{sidebar.classList.remove('open');backdrop.classList.remove('visible');open=false;toggle.setAttribute('aria-expanded','false')}}setOpen(open)}}
  toggle.addEventListener('click',function(){{setOpen(!open)}});
  backdrop.addEventListener('click',function(){{setOpen(false);toggle.focus()}});
  sidebar.querySelectorAll('a').forEach(function(link){{link.addEventListener('click',function(){{if(mobile.matches)setOpen(false)}})}});
  document.addEventListener('keydown',function(event){{if(event.key==='Escape'&&open){{setOpen(false);toggle.focus()}}}});
  mobile.addEventListener('change',syncViewport);
  setOpen(false);
  document.addEventListener('click',function(event){{
    var button=event.target.closest('[data-copy-value]');
    if(!button)return;
    var value=button.getAttribute('data-copy-value');
    var status=document.querySelector('[data-copy-status]');
    function feedback(label,ok){{
      button.textContent=label;
      button.classList.toggle('copied',ok);
      button.classList.toggle('copy-failed',!ok);
      if(status)status.textContent=label+(ok?'':' — allow clipboard access or select the text manually');
      window.setTimeout(function(){{button.textContent='Copy';button.classList.remove('copied','copy-failed')}},1500);
    }}
    if(navigator.clipboard&&navigator.clipboard.writeText){{
      navigator.clipboard.writeText(value).then(function(){{feedback('Copied!',true)}},function(){{feedback('Copy failed',false)}});
    }}else{{feedback('Copy failed',false)}}
  }});
  document.querySelectorAll('[data-model-filter]').forEach(function(root){{
    var input=root.querySelector('[data-model-filter-input]');
    var role=root.querySelector('[data-model-filter-role]');
    var rows=Array.prototype.slice.call(root.querySelectorAll('[data-model-row]'));
    var groups=Array.prototype.slice.call(root.querySelectorAll('[data-model-group]'));
    var count=root.querySelector('[data-model-filter-count]');
    var empty=root.querySelector('[data-model-filter-empty]');
    function apply(){{
      var query=(input?input.value:'').toLowerCase().trim();
      var selected=role?role.value:'';
      var visible=0;
      rows.forEach(function(row){{
        var matchText=!query||row.getAttribute('data-model-search').indexOf(query)!==-1;
        var matchRole=!selected||row.getAttribute('data-model-role')===selected;
        row.hidden=!(matchText&&matchRole);
        if(!row.hidden)visible++;
      }});
      groups.forEach(function(group){{group.hidden=!group.querySelector('[data-model-row]:not([hidden])')}});
      if(count)count.textContent=visible+(visible===1?' model':' models');
      if(empty)empty.hidden=visible!==0;
    }}
    if(input)input.addEventListener('input',apply);
    if(role)role.addEventListener('change',apply);
    apply();
  }});
}}());
</script>
</body>
</html>"""


def table(headers, rows, cls="", caption="", row_header=None, row_attrs=None):
    th = "".join(f'<th scope="col">{h}</th>' for h in headers)
    trs = []
    for i, row in enumerate(rows):
        cells = []
        for j, cell in enumerate(row):
            tag = "th" if j == row_header else "td"
            scope = ' scope="row"' if j == row_header else ""
            cells.append(f'<{tag}{scope}>{cell}</{tag}>')
        attrs = row_attrs[i] if row_attrs and i < len(row_attrs) else ""
        trs.append(f'<tr{attrs}>{"".join(cells)}</tr>')
    caption_html = (f'<caption>{esc(caption)}</caption>' if caption
                    else f'<caption class="sr-only">{esc(" · ".join(headers))}</caption>')
    if len(headers) == 2:
        colgroup = '<col style="width:auto"><col style="width:22ch">'
    elif len(headers) == 4:
        colgroup = ('<col style="width:auto"><col style="width:auto">'
                    '<col style="width:auto"><col style="width:22ch">')
    else:
        colgroup = ""
    return (f'<div class="table-wrap {cls}"><table>{caption_html}{colgroup}<thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></div>')


BADGES = {
    "price-0": '<span class="badge badge-free">Verified $0</span>',
    "zen-free": '<span class="badge badge-zen">Zen free</span>',
    "zen-micro": '<span class="badge badge-proxy">Zen micro</span>',
    "plan": '<span class="badge badge-plan">In plan</span>',
}


def model_search_text(m):
    return " ".join(str(m.get(key) or "") for key in
                    ("id", "display_id", "name", "description", "role", "modalities", "sources"))


def model_row_attrs(m):
    return (f' data-model-row data-model-id="{esc(m.get("id", ""))}" '
            f'data-model-role="{esc(m.get("role", ""))}" '
            f'data-model-search="{esc(model_search_text(m))}"')


def model_rows(models, show_desc=True):
    rows = []
    for m in models:
        cells = [
            f'<span class="role-pill">{esc(m.get("role", "General purpose fallback"))}</span>',
            model_id(m.get("display_id", m.get("id", ""))),
            f'<span class="model-name">{esc(m.get("name", ""))}</span>',
            BADGES.get(m.get("free_basis"), ""),
            esc(" · ".join(m.get("sources", []))),
            fmt_context(m.get("context_length")),
            esc(m.get("modalities", "text")),
        ]
        if show_desc:
            desc = m.get("description") or "—"
            cells.append(f'<span class="desc">{esc(desc)}</span>')
        rows.append(cells)
    return rows
