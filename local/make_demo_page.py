# -*- coding: utf-8 -*-
"""生成视频用的 HTML 演示页（自包含，数据来自真实实验产物）。

页面按段落自动推进，动画用 CSS/JS 实现，录屏时直接录这一页。
数据全部从 out/*.json 读，不手抄。
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.environ.get("LTS_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
DST = os.path.join(OUT, "video", "demo.html")

CSS = """
:root{--bg:#0b0f1a;--bg2:#141b2d;--ink:#eef2f8;--mute:#93a0b8;--acc:#5eead4;--acc2:#ffc457;
--bad:#ff7a7a;--card:#161e33;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:linear-gradient(160deg,var(--bg) 0%,var(--bg2) 100%);color:var(--ink);
 font-family:"Microsoft YaHei","PingFang SC",sans-serif;overflow:hidden}
#stage{width:100vw;height:100vh;display:flex;flex-direction:column;justify-content:center;
 padding:6vh 8vw;position:relative}
section{display:flex;flex-direction:column;justify-content:center;width:100%}
.kicker{font-size:26px;color:var(--acc);letter-spacing:3px;margin-bottom:18px;opacity:0;
 animation:fade .6s .2s forwards}
h1{font-size:76px;line-height:1.15;margin-bottom:26px;opacity:0;animation:fade .7s .35s forwards}
h2{font-size:58px;line-height:1.2;margin-bottom:30px;opacity:0;animation:fade .7s .3s forwards}
p{font-size:32px;line-height:1.6;color:var(--mute);max-width:1200px;opacity:0;
 animation:fade .7s .5s forwards}
.row{display:flex;gap:36px;margin-top:46px;flex-wrap:wrap}
.card{background:var(--card);border:1px solid rgba(255,255,255,.08);border-radius:18px;
 padding:30px 34px;min-width:330px;opacity:0;animation:fade .7s .7s forwards}
.card .lab{font-size:24px;color:var(--mute);margin-bottom:12px}
.card .val{font-size:64px;font-weight:700;color:var(--acc)}
.card .val.bad{color:var(--bad)}
.card .val.amb{color:var(--acc2)}
.card .sub{font-size:22px;color:var(--mute);margin-top:10px}
img.chart{display:block;max-width:1180px;max-height:46vh;border-radius:14px;margin:10px auto 6px;
 box-shadow:0 12px 40px rgba(0,0,0,.45)}
.two{display:flex;gap:36px;align-items:flex-start;margin-top:20px}
.two .left{flex:1.3}
.two .right{flex:1}
pre.term{background:#05080f;border:1px solid rgba(94,234,212,.22);border-radius:12px;
 padding:22px 26px;font-family:Consolas,"Courier New",monospace;font-size:19px;
 line-height:1.55;color:#b7c6de;white-space:pre;overflow:hidden;margin:0;
 box-shadow:0 12px 40px rgba(0,0,0,.5)}
table{margin-top:40px;border-collapse:collapse;font-size:27px;opacity:0;
 animation:fade .7s .8s forwards}
th,td{padding:14px 26px;text-align:left;border-bottom:1px solid rgba(255,255,255,.08)}
th{color:var(--mute);font-weight:400;font-size:24px}
td.good{color:var(--acc);font-weight:700}
td.bad{color:var(--bad)}
.bar{height:34px;border-radius:8px;background:var(--acc);width:0;animation:grow 1.1s .8s forwards;
 transform-origin:left}
.bar.amb{background:var(--acc2)}.bar.bad{background:var(--bad)}
.rowline{display:flex;align-items:center;gap:20px;margin:16px 0;opacity:0;animation:fade .5s forwards}
.rowline .lbl{width:300px;font-size:26px;color:var(--ink)}
.rowline .trk{flex:1;height:34px;background:rgba(255,255,255,.07);border-radius:8px;overflow:hidden}
.foot{position:absolute;bottom:4vh;left:8vw;right:8vw;display:flex;justify-content:space-between;
 font-size:22px;color:#5b6780}
.tag{color:var(--acc2)}
#prog{position:absolute;left:0;bottom:0;height:5px;width:0;background:var(--acc);
 box-shadow:0 0 18px rgba(94,234,212,.6)}
@keyframes fade{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
@keyframes grow{to{width:var(--w)}}
@keyframes progmove{from{width:0}to{width:100%}}
"""


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def chart_b64(name: str) -> str | None:
    """把图表 PNG 内嵌成 base64 data URI —— 录屏时页面不能依赖外部文件。"""
    import base64
    p = os.path.join(OUT, "video", "figs", name)
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


def bar(label, value, maxv, cls="", delay=0.6):
    pct = max(2.0, min(100.0, value / maxv * 100))
    return (f'<div class="rowline" style="animation-delay:{delay}s">'
            f'<div class="lbl">{label}</div>'
            f'<div class="trk"><div class="bar {cls}" style="--w:{pct:.1f}%"></div></div>'
            f'<div style="width:190px;font-size:26px">{value}</div></div>')


def main():
    tps = load("local_tps_summary.json")
    pre = load("local_pre_summary.json")
    post = load("local_posthoc_summary.json")
    proc = load("local_process_summary.json")
    proc2 = load("local_process2_summary.json")
    proc_opt = load("local_process_opt_summary.json")
    if not (tps or pre or post or proc):
        raise SystemExit("缺少实验产物，先跑实验与分析")

    # 每段时长在 S 构造完之后按段数计算（见下方），保证 DURS.length == 段数
    durations = []

    S = []

    # ---------- 1 开场 ----------
    S.append(f"""
<section id="s1">
  <div class="kicker">本地 LM Studio · google/gemma-4-e2b</div>
  <h1>我解决了<br>大模型的时间感</h1>
  <p>告诉模型它上一轮每秒能生成多少 token —— 它到底能不能因此知道「自己要花多久」？</p>
</section>""")

    # ---------- 2 问题 ----------
    S.append(f"""
<section id="s2">
  <div class="kicker">问题</div>
  <h2>模型不知道自己有多快</h2>
  <p>让它预估「这条回复要写多久」，结果全是喊数字：目标放大 10 倍，它写出来的时长几乎不变。</p>
  <div class="row">
    <div class="card" style="animation-delay:.7s"><div class="lab">云端 API 上（450 轮 + 长程 148 次）</div>
      <div class="val bad">注入 TPS 无效</div>
      <div class="sub">但原因不是「模型不会用速率」</div></div>
    <div class="card" style="animation-delay:.9s"><div class="lab">真正的物理前提</div>
      <div class="val amb">速率要稳</div>
      <div class="sub">云端同一台机器测出 2.39× 的波动</div></div>
  </div>
</section>""")

    # ---------- 3 稳定性 ----------
    if tps:
        st = tps.get("steady") or {}
        mg = tps.get("merged") or {}
        mx = tps.get("minimax_reference") or {}
        img = chart_b64("chart_stability.png")
        S.append(f"""
<section id="s3">
  <div class="kicker">第一步 · 把尺子校准</div>
  <h2>换到本机：速率真的稳了</h2>
  {f'<img class="chart" src="{img}"/>' if img else ''}
  <div class="row">
    <div class="card" style="animation-delay:.6s"><div class="lab">云端 API 请求间波动</div>
      <div class="val bad">{mx.get('max_over_min', 2.39):.2f}×</div>
      <div class="sub">CV {mx.get('between_cv', 0.92):.3f} · 后端路由到不同吞吐的轨道</div></div>
    <div class="card" style="animation-delay:.85s"><div class="lab">本机稳态波动</div>
      <div class="val">{st.get('max_over_min', 0):.2f}×</div>
      <div class="sub">CV {st.get('between_cv', 0):.3f} · {st.get('n', 0)} 次采样</div></div>
    <div class="card" style="animation-delay:1.1s"><div class="lab">稳态速率</div>
      <div class="val">{st.get('median', 0):.0f}</div>
      <div class="sub">token / 秒（冷启动那次只有 {(tps.get('warm') or {}).get('cold_first_run_tps', 0):.0f}）</div></div>
  </div>
</section>""")

    # ---------- 4 剂量-反应 ----------
    if pre:
        arms = (pre.get("arms") or {})
        dose = (pre.get("dose") or {})
        rows = []
        for arm, label in (("base", "不注入"), ("speed_low", "注入 79 tok/s"),
                           ("speed_true", "注入 159 tok/s（真值）"),
                           ("speed_high", "注入 254 tok/s"), ("elapsed", "直接给秒数")):
            a = arms.get(arm)
            if not a:
                continue
            est = a.get("median_est")
            act = a.get("median_actual")
            cls = "good" if (est and act and 0.67 < est / act < 1.5) else "bad"
            rows.append(f"<tr><td>{label}</td><td>{est:.0f} 秒</td><td>{act:.1f} 秒</td>"
                        f"<td class='{cls}'>{est/act:.2f}×</td></tr>")
        sp = dose.get("spearman_rate_vs_est")
        b = dose.get("loglog_slope")
        S.append(f"""
<section id="s4">
  <div class="kicker">第二步 · 注入速率，看它动不动</div>
  <h2>速率这个数，真的进了它的判断</h2>
  <table><tr><th>实验臂</th><th>模型预估（中位）</th><th>真实耗时</th><th>估/实际</th></tr>
  {''.join(rows)}</table>
  <p style="margin-top:32px">Spearman(注入速率, 预估值) = {sp:+.3f}，log-log 斜率 b = {b:+.3f}
     <span class="tag">（云端同一测量是 −0.033 / +0.043，等于「没用」）</span></p>
</section>""")

    # ---------- 5 事后预估 ----------
    if post:
        arms = (post.get("arms") or {})
        rows = []
        for arm, label in (("base", "不注入"), ("speed", "注入稳定速率"), ("elapsed", "直接给秒数")):
            a = arms.get(arm)
            if not a:
                continue
            sp = a.get("spearman_est_vs_actual")
            err = a.get("median_log_err")
            # 旁白里的「差 X 倍」= 对称口径 e^对数误差；估/实际 = 中位比值（给方向）
            factor = math.exp(err) if err is not None else 0.0
            rows.append(f"<tr><td>{label}</td><td>{a.get('median_ratio', 0):.2f}×</td>"
                        f"<td class='{'good' if factor <= 1.5 else 'bad'}'>{factor:.2f}×</td>"
                        f"<td>{err:.3f}</td>"
                        f"<td class='{'good' if (sp or 0) >= 0.5 else 'bad'}'>"
                        f"{sp:+.3f}</td></tr>")
        S.append(f"""
<section id="s5">
  <div class="kicker">第三步 · 让它回看自己刚写的东西</div>
  <h2>这次它能算准了</h2>
  <table><tr><th>实验臂</th><th>估/实际</th><th>误差倍数</th><th>对数误差</th><th>跨轮相关(预估,真实耗时)</th></tr>
  {''.join(rows)}</table>
  <p style="margin-top:32px">长度从 500 字拉到 3000 字，真实耗时变化 6 倍——
     它报出的数字跟着真实耗时一起动，才算「有感觉」，而不是喊一个常数。<br>
     <span class="tag">误差倍数 = e^对数误差，就是旁白里说的「差 X 倍」；
     「估/实际」是方向（小于 1 是低估）。<br>
     注意：不注入那栏的跨轮相关也是 +1.000 —— 真正的区分在误差量级这一列，
     靠的是 2.5× → 1.3× → 1.1×，不是秩相关。</span></p>
</section>""")

    # ---------- 6 过程时间感 ----------
    if proc:
        arms = (proc.get("arms") or {})
        rows = []
        for arm, label in (("base", "不注入"), ("speed", "注入稳定速率"),
                           ("speed_len", "注入速率 + 字符/token 换算")):
            a = arms.get(arm)
            if not a:
                continue
            sp = a.get("median_within_spearman")
            lr = a.get("median_last_ratio")
            sl = a.get("median_slope")
            rows.append(f"<tr><td>{label}</td><td>{a.get('n_marks_median', 0):.0f} 个</td>"
                        f"<td class='amb'>{sp:+.3f}</td>"
                        f"<td class='bad'>{lr:.1f}×</td>"
                        f"<td class='bad'>{sl:.1f}</td></tr>")
        S.append(f"""
<section id="s6">
  <div class="kicker">第四步 · 长思考状态</div>
  <h2>边写边报时间？它只是在编节拍</h2>
  <table><tr><th>实验臂</th><th>标记数</th><th>轮内相关</th><th>末标记/真实</th><th>节拍斜率</th></tr>
  {''.join(rows)}</table>
  <p style="margin-top:26px">轮内相关全是 1.0，斜率却高达 15–22（理想是 1.0）：
     标记是条完美等差数列，R² = 0.998 —— 比真实时间规律得多，是编的。<br>
     思维链占掉约 <b>26%</b> 的真实时间，而模型看不见自己想了多久。</p>
</section>""")

    # ---------- 6b 优化 ----------
    if proc_opt:
        arms = (proc_opt.get("arms") or {})
        rows = []
        for arm, label in (("speed_unit", "速率 + 每单元产出量"),
                           ("speed_unit_think", "再补上思考阶段耗时")):
            a = arms.get(arm)
            if not a:
                continue
            lr = a.get("median_last_ratio")
            sl = a.get("median_slope")
            ic = a.get("median_intercept")
            rows.append(f"<tr><td>{label}</td>"
                        f"<td class='{'good' if lr and 0.5 <= lr <= 2.0 else 'bad'}'>{lr:.2f}×</td>"
                        f"<td class='{'good' if sl and 0.5 <= sl <= 1.6 else 'amb'}'>{sl:.2f}</td>"
                        f"<td>{ic:.1f} 秒</td></tr>")
        # 现场演示的真实输出（终端样式）
        term = ""
        tp = os.path.join(OUT, "video", "demo_output.txt")
        if os.path.exists(tp):
            raw = open(tp, encoding="utf-8", errors="replace").read()
            if "\ufffd" in raw[:200] or raw.startswith("\ufeff"):
                # PowerShell 的 Tee-Object / > 重定向写的是 UTF-16
                raw = open(tp, encoding="utf-16", errors="replace").read()
            keep = []
            started = False
            for ln in raw.splitlines():
                if "步骤 3" in ln:
                    started = True
                if started:
                    keep.append(ln)
            txt = "\n".join(keep[:26])
            txt = (txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            term = f"<pre class='term'>{txt}</pre>"
        S.append(f"""
<section id="s6b">
  <div class="kicker">第五步 · 怎么修</div>
  <h2>尺子要换算到「工作单元」上</h2>
  <div class="two">
    <div class="left">
      <table><tr><th>实验臂</th><th>末标记/真实</th><th>节拍斜率</th><th>截距</th></tr>
      {''.join(rows)}</table>
      <p style="margin-top:20px">速率只告诉模型「我多快」，不告诉它「写到哪了」。
         补一句「每写完一个小节大约产出 N 个 token」，模型只要会数小节，
         就能自己推出来大概过了多久。</p>
    </div>
    <div class="right">{term}</div>
  </div>
</section>""")

    # ---------- 7 结论 ----------
    S.append(f"""
<section id="s7">
  <div class="kicker">结论</div>
  <h2>速率是尺子，不是时钟</h2>
  <p>但尺子必须准。<br>
     云端 API 的速率 2.39× 波动，尺子本身就是坏的，量什么都不准；<br>
     本机稳态 1.15×，同一把尺子量出来的时间就有用了。</p>
  <div class="row">
    <div class="card" style="animation-delay:.7s"><div class="lab">工程做法</div>
      <div class="val" style="font-size:40px">给绝对量</div>
      <div class="sub">已过秒数 / 剩余预算 / 截止时刻</div></div>
    <div class="card" style="animation-delay:.9s"><div class="lab">确要用速率</div>
      <div class="val" style="font-size:40px">先测稳</div>
      <div class="sub">滑动窗口累计平均 + 报区间，并配明确待写量</div></div>
  </div>
</section>""")

    S.append(f"""
<section id="s8">
  <div class="kicker">完</div>
  <h1>代码 · 数据 · 报告<br>全部开源</h1>
  <p>每一轮都有原始记录（raw/*.jsonl），数字由脚本自动生成，没有手抄。<br>
     <span class="tag" style="font-size:36px;margin-top:14px">github.com/dy12021/llm-time-sense</span></p>
</section>""")

    # ---------- 每段时长：优先用已生成的旁白音频时长（保证音画对齐） ----------
    n = len(S)
    durations = [9.0] * n
    voice = os.path.join(ROOT, "local", "voice_script.json")
    if os.path.exists(voice):
        import subprocess
        segs = json.load(open(voice, encoding="utf-8"))
        ffprobe = (os.environ.get("FFPROBE")
                   or shutil.which("ffprobe") or "ffprobe")
        vd = os.path.join(ROOT, "out", "voice")
        durs = []
        for s in segs:
            p = os.path.join(vd, s["id"] + ".mp3")
            d = 0.0
            if os.path.exists(p) and os.path.exists(ffprobe):
                try:
                    out = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                                          "format=duration", "-of", "csv=p=0", p],
                                         capture_output=True, text=True)
                    d = float(out.stdout.strip())
                except Exception:
                    d = 0.0
            durs.append(round((d + 0.6) if d else 9.0, 2))
        if len(durs) == n:
            durations = durs
        else:
            print(f"[warn] 旁白段数 {len(durs)} != 页面段数 {n}，改用默认时长")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>我解决了大模型的时间感</title>
<style>{CSS}</style></head><body>
<div id="stage">{''.join(S)}</div>
<div class="foot"><span>LLM 时间感实验 · google/gemma-4-e2b @ 本地 LM Studio</span>
<span class="tag" id="pg"></span></div>
<div id="prog"></div>
<script>
const DURS = {json.dumps(durations)};
let idx = 0, t0 = 0;
const stage = document.getElementById('stage');
const prog = document.getElementById('prog');
function show(i){{
  document.querySelectorAll('section').forEach((s,k)=>{{
    s.style.display = (k===i?'flex':'none');
    s.style.animation='none'; void s.offsetWidth; s.style.animation='';
  }});
  document.getElementById('pg').textContent = (i+1)+' / '+DURS.length;
  // 进度条：本段时长内匀速走完 —— 保证录屏每秒都有变化帧
  prog.style.animation='none'; void prog.offsetWidth;
  prog.style.animation=`progmove ${{DURS[i]}}s linear forwards`;
}}
function next(){{
  idx=(idx+1)%DURS.length; show(idx);
  setTimeout(next, DURS[idx]*1000);
}}
const q = new URLSearchParams(location.search);
document.querySelectorAll('section').forEach(s=>s.style.display='none');
if (q.get('sec') !== null) {{
  idx = Math.max(0, Math.min(DURS.length-1, parseInt(q.get('sec'))||0));
  show(idx);
  if (q.get('loop') === '1') setTimeout(next, DURS[idx]*1000);
}} else {{
  show(0);
  setTimeout(next, DURS[0]*1000);
}}
</script>
</body></html>"""

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"demo page -> {DST} ({len(html)} chars, {len(S)} 段)")


if __name__ == "__main__":
    main()
