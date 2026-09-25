#!/usr/bin/env python3
"""Static legal/contact pages: privacy.html and contact.html.

Kept in their own module because these are hand-written policy text, not
data-driven views: the wording is reviewed as prose and must not be
regenerated from the roster. The pages still go through render.page() so
they inherit the shared shell, nav, and footer.

Every factual claim in PRIVACY_BODY below was verified against the running
site (2026-09-25): no analytics, no cookies, no scripts, access logs rotated
at 14 generations, and the only outbound hosts are openrouter.ai,
fonts.googleapis.com, fonts.gstatic.com, ko-fi.com, runpod.io. If that set
changes, this text must be re-checked before the page is trusted again.
"""

from render import esc, page

# Reviewed as prose. Keep the claims verifiable.
CONTACT_EMAIL = "caban.jacek@gmail.com"
ROSTER_REPO = "https://github.com/cabanj/free-llm-roster"
AUTOMATION_REPO = "https://github.com/cabanj/model-wiki-automation/issues"
POLICY_UPDATED = "2026-09-25"

PRIVACY_BODY = f"""<div class="page-body">
<section class="page-head">
  <span class="eyebrow">Legal</span>
  <h1>Privacy Policy</h1>
  <p class="lead">Last updated: {esc(POLICY_UPDATED)}. This site is a static, ad-free
  reference: no accounts, no login, no cookies, no analytics, no tracking. This page
  explains what is touched when you visit.</p>
</section>

<section class="prose">
<h2>What this site does not collect</h2>
<ul>
<li>No account, no registration, no email address.</li>
<li>No cookies, no local storage, no advertising or cross-site tracking pixels.</li>
<li>No analytics scripts — no Google Analytics, Plausible, or Umami.</li>
<li>No API keys. Nothing you type anywhere on this site is sent to it.</li>
</ul>

<h2>Server logs</h2>
<p>The web server records each request in its access log: your IP address, the
timestamp, the path you requested, and your browser's User-Agent string. Logs are used
only to keep the site running and to diagnose faults. They are never joined with any
other data source, sold, or used for advertising. Most of what they contain is
automated scanners rather than visitors.</p>
<p>Access logs are rotated and kept for approximately 14 days, after which they are
deleted.</p>
<p>Under the GDPR this processing rests on our legitimate interest in operating a
secure and available service (Art. 6(1)(f)). Log entries are not used to build
profiles.</p>

<h2>Third parties</h2>
<p>The page links out to services we do not operate. Clicking a link sends you to that
service, which then applies its own privacy policy. This site receives no information
about which links you follow, and no third-party script or frame is embedded.</p>
<ul>
<li><strong>Google Fonts.</strong> The site loads Inter and JetBrains Mono from
<code>fonts.googleapis.com</code> and <code>fonts.gstatic.com</code>, so Google sees
your IP address whenever your browser fetches the font files. This happens on every
page load. Blocking that domain in your browser or with a content blocker prevents the
request; the page then falls back to system fonts.</li>
<li><strong>OpenRouter, Nous Portal, OpenCode Zen.</strong> Outbound links to these
providers, some carrying an attribution code so we may receive a referral commission.
The code is part of the URL we publish, is not derived from anything you do, and does
not identify you. What those providers collect is governed by their own policies and
applies from the moment you follow the link.</li>
<li><strong>RunPod and Ko-fi.</strong> The support links carry an attribution code and,
for Ko-fi, are optional. Nothing is sent unless you click.</li>
</ul>

<h2>Your rights</h2>
<p>Because no account data and no contact list are held, there is no personal data to
export or correct. For questions about the server logs you can ask what is held and
request deletion under Art. 15 and 17 GDPR, using the details on the
<a href="contact.html">contact page</a>.</p>
<p>If you are outside the EEA the same applies: logs are kept for operations only and
are not shared or sold.</p>

<h2>Changes</h2>
<p>Any material change will be reflected in the date at the top of this page.</p>
</section>
</div>"""


def render_privacy(generated_at):
    return page("Privacy Policy", "", PRIVACY_BODY, generated_at)


CONTACT_BODY = f"""<div class="page-body">
<section class="page-head">
  <span class="eyebrow">Contact</span>
  <h1>Contact</h1>
  <p class="lead">llmroster.dev is a one-person project. Route your message to the place
  that will actually get it handled.</p>
</section>

<section class="prose">
<h2>Roster corrections</h2>
<p>Open a pull request on
<a href="{esc(ROSTER_REPO)}" target="_blank" rel="noopener">github.com/cabanj/free-llm-roster</a>.
Note that the table is regenerated daily, so edits to the table itself are overwritten —
open an issue instead for corrections to source or filtering rules.</p>

<h2>Privacy requests</h2>
<p>Including access to, or deletion of, server logs: email
<a href="mailto:{esc(CONTACT_EMAIL)}">{esc(CONTACT_EMAIL)}</a>, or open an issue on
<a href="{esc(AUTOMATION_REPO)}" target="_blank" rel="noopener">the automation repository</a>.</p>

<h2>Everything else</h2>
<p><a href="mailto:{esc(CONTACT_EMAIL)}">{esc(CONTACT_EMAIL)}</a>. Replies usually take
a few days.</p>

<p>One boundary worth stating plainly: providers are not added to the roster as a
favour. Entries are decided by the data, so a request to include a specific service will
usually be declined, and that answer will not change on a second ask.</p>
</section>
</div>"""


def render_contact(generated_at):
    return page("Contact", "", CONTACT_BODY, generated_at)
