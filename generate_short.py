"""Build a vertical Short for llmroster.dev: edge-tts voiceover + synced SRT + burned-in subs.

Pipeline: edge-tts (word boundaries) -> voiceover.mp3 + subtitles.srt -> ffmpeg -> short.mp4

The SRT is NOT hardcoded to fixed timestamps: caption windows are derived from the
WordBoundary offsets edge-tts reports, so subs stay locked to the actual audio.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

VOICE_CANDIDATES = ("en-US-ChristopherNeural", "en-US-GuyNeural")

# Spoken script, one sentence per line - each line maps 1:1 to a caption below.
SCRIPT = [
    "Stop paying for AI API tokens just to test your scripts and agents.",
    "LLM Roster is a live directory tracking genuinely zero-dollar endpoints, "
    "updated daily without credit card traps.",
    "It's a one-to-one drop-in replacement for OpenAI SDK: just swap the baseURL and run in Python.",
    "Filter by use case, copy model IDs in one click, and test for free.",
    "Check it out at llmroster.dev!",
]

# On-screen caption copy (short lines - the full sentence is the voiceover).
CAPTIONS = [
    "Stop paying for AI APIs just to test your code",
    "LLM Roster tracks verified $0.00 endpoints daily",
    "Drop-in replacement for OpenAI SDK in Python",
    "Filter by use case & copy model IDs in 1 click",
    "Bookmark it today: llmroster.dev",
]

ROOT = Path(__file__).parent
WORK = ROOT / "short_build"
DEMO = Path("C:/Users/caban/Videos/demo.mp4")
OUT = Path("C:/Users/caban/Videos/short.mp4")


def norm(text):
    """Letters/digits only - lets us match speech tokens to script words."""
    return "".join(c for c in text.lower() if c.isalnum())


def srt_ts(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


async def synthesize(text, voice, rate, out_mp3, out_meta, key, pitch="+0Hz", volume="+0%"):
    """Stream edge-tts, writing mp3 audio plus a boundary log."""
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%", pitch=pitch, volume=volume)
    words = []
    with open(out_mp3, "wb") as fh:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"].endswith("Boundary"):  # WordBoundary (edge-tts 6.x) or
                # SentenceBoundary (7.x endpoint) - both give offset/duration in 100ns ticks
                words.append({
                    "start": chunk["offset"] / 1e7,          # 100ns ticks -> seconds
                    "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                    "text": chunk["text"],
                })
    out_meta.write_text(json.dumps({"key": key, "words": words}, ensure_ascii=False),
                        encoding="utf-8")
    return words


def align(words, sentences):
    """Map each script sentence onto the boundary events that cover it.

    Robust to the service merging or splitting sentences: we locate every sentence
    in the concatenated speech text and take the boundaries that span it.
    """
    global_text, spans, cursor = "", [], 0
    starts = []
    for w in words:
        starts.append(len(global_text))
        global_text += norm(w["text"])

    for sentence in sentences:
        target = norm(sentence)
        if not target:
            continue
        pos = global_text.find(target, cursor)
        if pos < 0:
            raise SystemExit(f"speech does not contain: {sentence[:50]!r}")
        last = pos + len(target) - 1
        first_i = max(i for i, s in enumerate(starts) if s <= pos)
        last_i = max(i for i, s in enumerate(starts) if s <= last)
        exact = norm(words[first_i]["text"]) == target
        spans.append((words[first_i]["start"], words[last_i]["end"], exact))
        cursor = pos + len(target)
    return spans


def build_srt(spans, captions, path, tail_pad=0.0):
    lines = []
    for idx, (start, end, exact) in enumerate(spans):
        if not exact:
            print(f"  ! caption {idx + 1}: speech differs from script (timing still valid)",
                  file=sys.stderr)
        end = min(end, spans[idx + 1][0] - 0.05) if idx + 1 < len(spans) else end
        if idx == len(spans) - 1:
            end += tail_pad
        lines.append(f"{idx + 1}\n{srt_ts(start)} --> {srt_ts(end)}\n{captions[idx]}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def synth_cached(text, voice, rate, mp3, meta, pitch="+0Hz", volume="+0%", force=False):
    """Synthesize unless an identical (voice, rate, pitch) render is already on disk."""
    import asyncio

    key = {"voice": voice, "rate": rate, "pitch": pitch, "volume": volume,
           "script": hash(text)}
    if not force and mp3.exists() and meta.exists():
        try:
            cached = json.loads(meta.read_text(encoding="utf-8"))
            if cached.get("key") == key:
                print(f"  reuse cached tts rate={rate:+d}% pitch={pitch}")
                return cached["words"]
        except (json.JSONDecodeError, KeyError):
            pass
    words = asyncio.run(synthesize(text, voice, rate, mp3, meta, key, pitch, volume))
    print(f"  tts rate={rate:+d}% pitch={pitch}: {probe_duration(mp3):.2f}s "
          f"({len(words)} boundaries)")
    return words


def fit_rate(text, voice, mp3, meta, target, max_slow=25, max_fast=25,
             pitch="+0Hz", volume="+0%"):
    """Nudge the delivery rate (2% steps) to the length of the recording.

    Bidirectional on purpose: slowing a 29s script down to fill a 37s frame is what
    made the read drag. If the narration is too long we speed up instead of letting
    ffmpeg cut the last words off.
    """
    rate, spoken = 0, probe_duration_for(text, voice, mp3, meta, 0, pitch, volume)
    while spoken < target and rate > -max_slow:
        rate -= 2
        spoken = probe_duration_for(text, voice, mp3, meta, rate, pitch, volume)
    while spoken > target and rate < max_fast:
        rate += 2
        spoken = probe_duration_for(text, voice, mp3, meta, rate, pitch, volume)
    return rate, spoken


def probe_duration_for(text, voice, mp3, meta, rate, pitch="+0Hz", volume="+0%"):
    synth_cached(text, voice, rate, mp3, meta, pitch, volume)
    return probe_duration(mp3)


def render(video, audio, srt, out, font, fontsdir, font_size, margin_v, video_dur,
            brightness, saturation, contrast):
    """Burn subtitles in. cwd=WORK so the filter args have no drive-letter colon,
    which ffmpeg's filter parser would otherwise read as a filter separator.

    eq runs first: the site is a very dark UI and reads as murky on a phone screen.
    """
    grade = f"eq=brightness={brightness}:saturation={saturation}:contrast={contrast}"
    vf = (f"{grade},"
          f"subtitles={srt.name}:fontsdir={fontsdir}:force_style='FontName={font},"
          f"FontSize={font_size},PrimaryColour=&H00BFD42D,OutlineColour=&H00000000,"
          f"BorderStyle=3,Outline=2,Alignment=2,MarginV={margin_v}'")
    cmd = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
           "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "22",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "160k",
           "-t", f"{video_dur:.2f}", str(out)]
    print("  ffmpeg:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(srt.parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", type=Path, default=DEMO)
    ap.add_argument("--out", type=Path, default=OUT)
    # NOTE on FontSize: libass finds no PlayRes in a plain .srt, so it assumes
    # 384x288 and scales the script to the video height -> on-screen glyph size is
    # FontSize * 1920/288 (~6.67x) on a 1080x1920 frame. Measured with cropdetect:
    # 10 -> one line for some captions but two for others (inconsistent), 11 -> a
    # steady two-line block ~120px tall and ~60% of the frame width, 13+ -> 3 lines.
    ap.add_argument("--font", default="Inter SemiBold")
    ap.add_argument("--fontsdir", default="fonts")
    ap.add_argument("--font-size", type=int, default=11)
    ap.add_argument("--margin-v", type=int, default=40,
                    help="libass units; 40 -> ~267px above the bottom edge, clear of "
                         "the YouTube player UI")
    ap.add_argument("--brightness", type=float, default=0.06)
    ap.add_argument("--saturation", type=float, default=1.25)
    ap.add_argument("--contrast", type=float, default=1.06)
    ap.add_argument("--max-slowdown", type=int, default=15,
                    help="max %% to slow the TTS in order to span the recording")
    ap.add_argument("--max-speedup", type=int, default=25,
                    help="max %% to speed the TTS up when it overruns the recording")
    ap.add_argument("--voice", default=VOICE_CANDIDATES[0], choices=VOICE_CANDIDATES)
    ap.add_argument("--pitch", default="+5Hz", help="edge-tts pitch, e.g. +5Hz")
    ap.add_argument("--volume", default="+0%", help="edge-tts volume, e.g. +10%%")
    args = ap.parse_args()

    WORK.mkdir(exist_ok=True)
    if not args.demo.exists():
        raise SystemExit(f"missing {args.demo} - run record_demo.py first")

    text = " ".join(SCRIPT)
    video_dur = probe_duration(args.demo)
    print(f"demo.mp4: {video_dur:.2f}s")

    voice = args.voice
    mp3 = WORK / "voiceover.mp3"
    meta = WORK / "voiceover_words.json"
    t0 = time.time()

    # Match the narration's length to the recording in whichever direction is
    # cheaper - a read that drags is worse than one that runs slightly fast.
    rate, spoken = fit_rate(text, voice, mp3, meta, video_dur - 0.15, args.max_slowdown,
                            args.max_speedup, args.pitch, args.volume)
    words = synth_cached(text, voice, rate, mp3, meta, args.pitch, args.volume)
    spoken = probe_duration(mp3)
    print(f"tts[{voice}] rate={rate:+d}% pitch={args.pitch}: {spoken:.2f}s vs "
          f"{video_dur:.2f}s video "
          f"(tail {'+' if spoken < video_dur else '-'}{abs(video_dur - spoken):.2f}s)")

    spans = align(words, SCRIPT)
    if len(spans) != len(CAPTIONS):
        raise SystemExit(f"aligned {len(spans)} spans for {len(CAPTIONS)} captions")
    srt = WORK / "subtitles.srt"
    build_srt(spans, CAPTIONS, srt, tail_pad=0.0)
    print(f"srt: {srt}")
    for i, (s, e, exact) in enumerate(spans):
        print(f"  {i + 1} {srt_ts(s)} --> {srt_ts(e)}  {CAPTIONS[i]}"
              + ("" if exact else "   (boundary spans several sentences)"))
    if spoken > video_dur:
        print(f"  ! narration overruns the video by {spoken - video_dur:.2f}s; "
              f"last words will be cut - raise --max-slowdown", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    render(args.demo, mp3, srt, args.out, args.font, args.fontsdir, args.font_size,
           args.margin_v, video_dur, args.brightness, args.saturation, args.contrast)
    print(f"elapsed {time.time() - t0:.1f}s")
    print(f"OUT: {args.out}  ({probe_duration(args.out):.2f}s)")


if __name__ == "__main__":
    main()
