# -*- coding: utf-8 -*-
"""合成最终视频。

流程（每段独立成 clip，最后 concat）：
  1) burst  : 8 张淡入过程帧，用 concat 滤镜按真实时刻精确铺开
  2) still  : 该段最后一帧 + zoompan 慢推（定格但画面仍在缓慢动）
  3) 9 段 clip concat 成无声画面
  4) 9 段旁白 mp3 按 0.35s 留白拼成 audio.wav
  5) 画面 + 音频 mux 成 out/video/final.mp4

所有时长来自 out/video/plan.json（由 ffprobe 读真实音频得出），不手抄。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
import shutil

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "video")
FDIR = os.path.join(OUT, "frames")
WORK = os.path.join(OUT, "_work")
FF = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("FFPROBE") or shutil.which("ffprobe") or "ffprobe"

FPS = 30
ZOOM_END = 1.08          # 定格慢推的最终倍率
VOPTS = ["-c:v", "libx264", "-preset", "fast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", "60",
         "-profile:v", "high", "-level", "4.1", "-an",
         "-threads", "2", "-filter_complex_threads", "1"]


def run(args, label):
    p = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"{label} 失败:\n{p.stderr[-3000:]}")
    return p


def dur_of(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def nframes_of(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path],
        capture_output=True, text=True)
    try:
        return int(out.stdout.strip())
    except Exception:
        return -1


def build_burst(sec, files, shot_times, reveal, out_path):
    """把淡入过程帧按真实时刻铺开成一段 clip。

    最后一帧（完全淡入后的那张）留给 still 段，所以 burst 只用前 n 张。
    用 concat 滤镜（不是 concat demuxer）—— demuxer 对 PNG 的时间戳不可靠。
    """
    n = len(files) - 1
    durs = [round(shot_times[i + 1] - shot_times[i], 3) for i in range(n - 1)]
    durs.append(round(reveal - sum(durs), 3))

    cmd = [FF, "-y", "-hide_banner", "-loglevel", "error"]
    for i in range(n):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{durs[i]:.3f}",
                "-i", os.path.join(FDIR, files[i])]
    fc = "".join(f"[{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-r", str(FPS)] + VOPTS + [out_path]
    run(cmd, f"burst {sec}")
    return sum(durs)


def build_still(sec, last_frame, still_dur, out_path):
    """定格帧 + zoompan 慢推。"""
    if still_dur <= 0.05:
        run([FF, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=black:s=1920x1080:r=30",
             "-t", "0.05"] + VOPTS + [out_path], f"still {sec}")
        return
    nframes = max(2, int(round(still_dur * FPS)))
    inc = (ZOOM_END - 1.0) / nframes
    # 单帧输入 + d=nframes（不要 -loop 1：那样 zoom 每帧会被重置，表现为不动）
    vf = (f"zoompan=z='min(zoom+{inc:.9f},{ZOOM_END})':d={nframes}:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
          f"s=1920x1080:fps={FPS},format=yuv420p")
    run([FF, "-y", "-hide_banner", "-loglevel", "error",
         "-i", os.path.join(FDIR, last_frame),
         "-t", str(still_dur), "-vf", vf] + VOPTS + [out_path], f"still {sec}")


def build_audio(plan, out_wav):
    """9 段 mp3 按段间留白拼成一个 wav（PCM，精确到采样）。"""
    tmpdir = os.path.join(WORK, "wav")
    os.makedirs(tmpdir, exist_ok=True)
    chunks = []
    rate = nch = None
    for seg in plan:
        w = os.path.join(tmpdir, f"{seg['id']}.wav")
        run([FF, "-y", "-hide_banner", "-loglevel", "error",
             "-i", seg["mp3"], "-ar", "44100", "-ac", "2",
             "-c:a", "pcm_s16le", w], f"wav {seg['id']}")
        with wave.open(w, "rb") as fh:
            rate, nch = fh.getframerate(), fh.getnchannels()
            sw = fh.getsampwidth()
            chunks.append(fh.readframes(fh.getnframes()))
        if seg["gap"] > 0:
            # 字节数 = 帧数 × 声道 × 每采样字节数（s16 = 2）
            nbytes = int(round(seg["gap"] * rate)) * nch * sw
            chunks.append(b"\x00" * nbytes)
    with wave.open(out_wav, "wb") as fh:
        fh.setnchannels(nch)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        for c in chunks:
            fh.writeframes(c)
    return dur_of(out_wav)


def main():
    os.makedirs(WORK, exist_ok=True)
    planj = json.load(open(os.path.join(OUT, "plan.json"), encoding="utf-8"))
    plan = planj["plan"]
    reveal = planj["reveal"]
    st = json.load(open(os.path.join(OUT, "shot_times.json"), encoding="utf-8"))
    shot_times = st["shot_times"]
    manifest = st["manifest"]

    clips = []
    for i, seg in enumerate(plan):
        sec = seg["sec"]
        files = manifest[i]["files"]
        b = os.path.join(WORK, f"burst_{sec:02d}.mp4")
        s = os.path.join(WORK, f"still_{sec:02d}.mp4")
        build_burst(sec, files, shot_times, reveal, b)
        bactual = dur_of(b)
        bframes = nframes_of(b)
        # 用实测 burst 时长反推 still 时长，保证本段总长 = 旁白 + 留白
        still_actual = round(seg["clip_dur"] - bactual, 3)
        build_still(sec, files[-1], still_actual, s)
        sd = dur_of(s)
        print(f"  sec{sec}: burst {bactual:.2f}s ({bframes} 帧) + still {sd:.2f}s"
              f"  = {bactual + sd:.2f}s / 目标 {seg['clip_dur']:.2f}s")
        clips += [b, s]

    clist = os.path.join(WORK, "clips.txt")
    with open(clist, "w", encoding="utf-8") as fh:
        for c in clips:
            fh.write(f"file '{c}'\n")
    silent = os.path.join(WORK, "silent.mp4")
    run([FF, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", clist,
         "-c", "copy", silent], "concat clips")
    print(f"silent video: {dur_of(silent):.2f}s")

    audio = os.path.join(WORK, "audio.wav")
    adur = build_audio(plan, audio)
    print(f"audio: {adur:.2f}s")

    final = os.path.join(OUT, "final.mp4")
    run([FF, "-y", "-hide_banner", "-loglevel", "error",
         "-i", silent, "-i", audio,
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
         "-ac", "2", "-shortest", "-movflags", "+faststart", final], "mux")
    print(f"FINAL -> {final}  {os.path.getsize(final) / 1e6:.1f} MB  "
          f"{dur_of(final):.2f}s")


if __name__ == "__main__":
    main()
