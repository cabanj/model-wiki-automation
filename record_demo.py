"""Record a mobile-viewport demo of llmroster.dev with Playwright.

Viewport 430x932 (iPhone 15 Pro). Video -> output_video/*.webm.
Selectors were verified against the live site:
  - copy button  : [data-copy-value] / .copy-button  (no .copy-id-btn exists)
  - models table : .model-table on comparisons-free-models-ranking.html
  - quick start  : .quickstart on the index page
"""

import argparse
import pathlib
from pathlib import Path
import subprocess

from playwright.sync_api import sync_playwright

URL = "https://llmroster.dev"
RANKING = f"{URL}/comparisons-free-models-ranking.html"
OUT_DIR = pathlib.Path(__file__).parent / "output_video"


def smooth_scroll(page, selector, seconds=3.0):
    """Scroll window down to the first match of `selector` over `seconds`, eased."""
    el = page.query_selector(selector)
    if el is None:
        raise SystemExit(f"selector not found: {selector}")
    start = page.evaluate("window.scrollY")
    end = el.evaluate("el => el.getBoundingClientRect().top + window.scrollY - 80")
    steps = max(1, int(seconds * 20))
    for i in range(1, steps + 1):
        t = i / steps
        eased = 1 - (1 - t) ** 3  # ease-out cubic
        page.evaluate("y => window.scrollTo(0, y)", start + (end - start) * eased)
        page.wait_for_timeout(50)


def main():
    ap = argparse.ArgumentParser()
    # Default preset: true 9:16 for YouTube Shorts / Reels. A 405x720 CSS viewport at
    # DPR 3 renders 1215x2160 and is downscaled to 1080x1920, so the pixels are real
    # detail rather than an upscale. For a native-9:16 look, keep width/height at 9:16
    # - padding a 430x932 (0.461) capture to 1080x1920 (0.5625) would pillarbox it.
    ap.add_argument("--width", type=int, default=405)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--scale", type=int, default=3, help="device_scale_factor")
    ap.add_argument("--record-width", type=int, default=1080)
    ap.add_argument("--record-height", type=int, default=1920)
    # Pacing: the short's energy comes from a tight cut. These waits used to total
    # ~15.7s of dead air around ~21s of content, which forced the narration down to
    # -22% to fill the frame. Tighter defaults let the voice run at a natural or
    # brisk rate instead.
    ap.add_argument("--scroll", type=float, default=2.0, help="seconds per scroll")
    ap.add_argument("--hold", type=int, default=2100, help="hold on the snippet panel, ms")
    ap.add_argument("--copied-hold", type=int, default=1300,
                    help="hold on the 'Copied!' state, ms (site resets it at 1500)")
    ap.add_argument("--mp4", type=Path, default=Path("C:/Users/caban/Videos/demo.mp4"),
                    help="also transcode the webm to H.264 here (empty string to skip)")
    args = ap.parse_args()

    viewport = {"width": args.width, "height": args.height}
    record_size = {"width": args.record_width, "height": args.record_height}
    OUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=[f"--force-device-scale-factor={args.scale}"])

        # Warm the HTTP cache in a throwaway, unrecorded context: the first ever
        # load costs DNS+TLS and paints ~4s of black into the recording.
        warm = browser.new_context(viewport=viewport, color_scheme="dark")
        warm_page = warm.new_page()
        warm_page.goto(URL, wait_until="networkidle")
        warm_page.goto(RANKING, wait_until="networkidle")
        warm.close()

        context = browser.new_context(
            viewport=viewport,
            device_scale_factor=args.scale,
            is_mobile=True,
            has_touch=True,
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            record_video_dir=str(OUT_DIR),
            record_video_size=record_size,
            # The site ships a dark palette in :root and swaps to a light one under
            # (prefers-color-scheme: light); headless Chromium reports light by default.
            color_scheme="dark",
            permissions=["clipboard-read", "clipboard-write"],
        )
        page = context.new_page()

        # 1. Landing page: hero + quick start
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(500)
        smooth_scroll(page, ".quickstart", seconds=args.scroll)
        page.wait_for_timeout(400)

        # The site sets html{scroll-behavior:smooth}, which makes Playwright's
        # pre-click auto-scroll race the click. Turn it off for the scripted clicks.
        page.add_style_tag(content="html{scroll-behavior:auto !important}")

        # Quick start is a collapsed <details> - open it, then switch snippet tab
        page.click(".quickstart summary")
        page.wait_for_timeout(450)
        if not page.locator(".quickstart[open]").count():  # toggle can be swallowed by a race
            page.click(".quickstart summary")
            page.wait_for_timeout(450)
        if not page.locator(".quickstart[open]").count():
            raise SystemExit("quick start <details> did not open")
        page.click(".quickstart-tabs label:nth-of-type(2)")
        page.wait_for_timeout(300)
        if not page.locator(".quickstart-panel:visible").count():
            raise SystemExit("no quick start snippet panel visible")
        page.wait_for_timeout(args.hold)

        # 2. Free models page: roster table + copy feedback
        page.goto(RANKING, wait_until="networkidle")
        page.wait_for_timeout(500)
        smooth_scroll(page, ".model-table", seconds=args.scroll)
        page.wait_for_timeout(400)

        # First *visible* copy button (rows hidden by the role filter must be skipped)
        copy_btn = page.locator(".model-table [data-copy-value]:visible").first
        if copy_btn.count() == 0:
            raise SystemExit("no visible copy button in model table")
        copy_btn.evaluate("el => el.scrollIntoView({block: 'center'})")
        page.wait_for_timeout(500)
        print("COPY BUTTON:", copy_btn.get_attribute("data-copy-value"))
        copy_btn.click()
        page.wait_for_timeout(300)
        # Site resets the label after 1500ms - assert the feedback state really fired
        state = copy_btn.text_content()
        print("COPY FEEDBACK:", state)
        if state.strip() != "Copied!":
            raise SystemExit(f"copy feedback not shown, got: {state!r}")
        page.wait_for_timeout(args.copied_hold)  # hold the "Copied!" state on screen

        page.wait_for_timeout(600)
        video = page.video
        context.close()
        browser.close()
        webm = Path(video.path())
        print("VIDEO:", webm)

        if args.mp4:
            args.mp4.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(webm),
                            "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                            str(args.mp4)], check=True)
            print("MP4:", args.mp4)


if __name__ == "__main__":
    main()
