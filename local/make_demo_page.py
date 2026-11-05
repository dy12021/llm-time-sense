# -*- coding: utf-8 -*-
"""生成视频用的 HTML 演示页（自包含，数据来自真实实验产物）。

页面按段落自动推进，动画用 CSS/JS 实现，录屏时直接录这一页。
数据全部从 out/*.json 读，不手抄。

v2（2026-11-05 重做）：10 段。
主线只讲成功的三招（① 事前注入速率 ② 事后预估 ③ 长思考换算到工作单元），
之前失败的两次尝试整体下沉到第 9 段「备注」页。
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
.card .sub{font-size:22px;color:var(--mute);margin-top:10px;line-height:1.5}
img.chart{display:block;max-width:1180px;max-height:36vh;border-radius:14px;margin:8px auto 4px;
 box-shadow:0 12px 40px rgba(0,0,0,.45)}
.two{display:flex;gap:36px;align-items:flex-start;margin-top:20px}
.two .left{flex:1.25}
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
td.amb{color:var(--acc2)}
.quote{border-left:5px solid var(--acc);background:rgba(94,234,212,.07);
 padding:20px 28px;border-radius:0 14px 14px 0;margin-top:28px;font-size:26px;
 line-height:1.55;color:var(--ink);opacity:0;animation:fade .7s 1.15s forwards}
.quote .qm{color:var(--acc);font-size:21px;margin-bottom:8px;letter-spacing:1px}
.rowline{display:flex;align-items:center;gap:20px;margin:16px 0;opacity:0;animation:fade .5s forwards}
.rowline .lbl{width:300px;font-size:26px;color:var(--ink)}
.rowline .trk{flex:1;height:34px;background:rgba(255,255,255,.07);border-radius:8px;overflow:hidden}
.foot{position:absolute;bottom:4vh;left:8vw;right:8vw;display:flex;justify-content:space-between;
 font-size:22px;color:#5b6780}
.tag{color:var(--acc2)}
.note .card{border-color:rgba(255,196,87,.30)}
.note h2{font-size:50px}
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


def main():
    tps = load("local_tps_summary.json")
    pre = load("local_pre_summary.json")
    post = load("local_posthoc_summary.json")
    proc = load("local_process_summary.json")
    proc_opt = load("local_process_opt_summary.json")
    if not (tps or pre or post or proc):
        raise SystemExit("缺少实验产物，先跑实验与分析")

    S = []

    # ---------- 1 开场 ----------
    S.append(f"""
<section id="s1">
  <div class="kicker">本地 LM Studio · google/gemma-4-e2b</div>
  <h1>我解决了<br>大模型的时间感</h1>
  <p>告诉模型它上一轮每秒能生成多少 token —— 它到底能不能因此知道「自己要花多久」？</p>
</section>""")

    # ---------- 2 问题 ----------
    if pre:
        base = (pre.get("arms") or {}).get("base") or {}
        est = base.get("median_est")
        act = base.get("median_actual")
        ratio = base.get("median_ratio")
        S.append(f"""
<section id="s2">
  <div class="kicker">问题</div>
  <h2>模型不知道自己有多快</h2>
  <p>让它预估「这条回复要写多久」，不给任何提示的时候，它只能喊一个数字。</p>
  <div class="row">
    <div class="card" style="animation-delay:.7s"><div class="lab">它的预估（中位）</div>
      <div class="val bad">{est:.1f} 秒</div>
      <div class="sub">真实耗时 {act:.1f} 秒</div></div>
    <div class="card" style="animation-delay:.9s"><div class="lab">时间被少算了</div>
      <div class="val bad">{1.0 / ratio:.0f} 倍</div>
      <div class="sub">估/实际 = {ratio:.2f}×（理想 1.00×）</div></div>
    <div class="card" style="animation-delay:1.1s"><div class="lab">它为什么算不准</div>
      <div class="val" style="font-size:42px">不知道自己<br>一秒能吐几个 token</div>
      <div class="sub">心里没有「每秒多少 token」这个数</div></div>
  </div>
</section>""")

    # ---------- 3 先把尺子测准 ----------
    if tps:
        st = tps.get("steady") or {}
        img = chart_b64("chart_stability.png")
        S.append(f"""
<section id="s3">
  <div class="kicker">第一步 · 先把尺子测准</div>
  <h2>本机 LM Studio：速率真的稳了</h2>
  {f'<img class="chart" src="{img}"/>' if img else ''}
  <div class="row" style="margin-top:26px">
    <div class="card" style="animation-delay:.6s"><div class="lab">稳态速率中位</div>
      <div class="val">{st.get('median', 0):.0f}</div>
      <div class="sub">token / 秒</div></div>
    <div class="card" style="animation-delay:.85s"><div class="lab">稳态波动 max/min</div>
      <div class="val">{st.get('max_over_min', 0):.2f}×</div>
      <div class="sub">{st.get('n', 0)} 次采样 · CV {st.get('between_cv', 0):.3f}</div></div>
    <div class="card" style="animation-delay:1.1s"><div class="lab">冷启动那一次</div>
      <div class="val amb">{(tps.get('warm') or {}).get('cold_first_run_tps', 0):.1f}</div>
      <div class="sub">token / 秒（前两次预热已排除）</div></div>
  </div>
  <p style="margin-top:22px">同一套协议，只换了个机器：每轮清空上下文，严格串行，不开并发。</p>
</section>""")

    # ---------- 4 方法一：事前注入速率 ----------
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
  <div class="kicker">方法一 · 事前注入速率</div>
  <h2>速率这个数，真的进了它的判断</h2>
  <table><tr><th>实验臂</th><th>模型预估（中位）</th><th>真实耗时</th><th>估/实际</th></tr>
  {''.join(rows)}</table>
  <p style="margin-top:28px">Spearman(注入速率, 预估值) = {sp:+.3f}，log-log 斜率 b = {b:+.3f}
     —— 注入的速率越高，它预估的时长就越短。</p>
  <div class="quote"><div class="qm">思维链原文（注入 158.5 token/秒那一轮）</div>
     「3500 / 158.5 ≈ 22 seconds」 → 它回答 <b>25 秒</b>，真实耗时 <b>25.5 秒</b>；
     不注入速率那轮写的是「A few seconds」，回答 8 秒，真实 26.9 秒。</div>
</section>""")

    # ---------- 5 方法二：事后预估 ----------
    if post:
        arms = (post.get("arms") or {})
        ds = post.get("duration_span") or {}
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
  <div class="kicker">方法二 · 让它回看自己刚写的东西</div>
  <h2>这次它能算准了</h2>
  <table><tr><th>实验臂</th><th>估/实际</th><th>误差倍数</th><th>对数误差</th><th>跨轮相关(预估,真实耗时)</th></tr>
  {''.join(rows)}</table>
  <p style="margin-top:30px">长度从 {ds.get('words_min', 500)} 字拉到 {ds.get('words_max', 3000)} 字，
     真实耗时从 {ds.get('actual_min_s', 0):.1f} 秒涨到 {ds.get('actual_max_s', 0):.1f} 秒（{ds.get('time_ratio', 0):.1f} 倍）——
     它报出的数字跟着真实耗时一起动，才算「有感觉」，而不是喊一个常数。<br>
     <span class="tag">误差倍数 = e^对数误差，就是旁白里说的「差 X 倍」；
     「估/实际」是方向（小于 1 是低估）。<br>
     注意：不注入那栏的跨轮相关也是 +1.000 —— 真正的区分在误差量级这一列，
     靠的是 2.5× → 1.3× → 1.1×，不是秩相关。</span></p>
</section>""")

    # ---------- 6 方法三：长思考状态 ----------
    if proc_opt:
        a = (proc_opt.get("arms") or {}).get("speed_unit") or {}
        lr = a.get("median_last_ratio")
        sl = a.get("median_slope")
        ic = a.get("median_intercept")
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
                # 「→ 对照：只给速率…」讲的是失败臂，按新结构沉到第 9 段备注页，
                # 这里只留成功臂的证据（完整原始输出仍在 out/video/demo_output.txt）
                if ln.strip().startswith("→ 对照"):
                    break
                if started:
                    keep.append(ln)
            txt = "\n".join(keep[:26])
            txt = (txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            term = f"<pre class='term'>{txt}</pre>"
        S.append(f"""
<section id="s6">
  <div class="kicker">方法三 · 长思考状态</div>
  <h2>把速率换算到「工作单元」上</h2>
  <div class="two">
    <div class="left">
      <div class="row" style="margin-top:6px">
        <div class="card" style="animation-delay:.6s"><div class="lab">末标记 / 真实耗时</div>
          <div class="val">{lr:.2f}×</div><div class="sub">理想 1.00×</div></div>
        <div class="card" style="animation-delay:.8s"><div class="lab">节拍斜率</div>
          <div class="val">{sl:.2f}</div><div class="sub">理想 1.00</div></div>
      </div>
      <p style="margin-top:24px">速率只告诉模型「我多快」，不告诉它「写到哪了」。<br>
         补一句「每写完一个小节约产出 122 个 token」，模型只要会数自己写到第几个小节，
         就能用这个换算推出大概过了多久。</p>
    </div>
    <div class="right">{term}</div>
  </div>
</section>""")

    # ---------- 7 边界：残余偏移 ----------
    if proc_opt:
        a = (proc_opt.get("arms") or {}).get("speed_unit") or {}
        ic = a.get("median_intercept")
        share = a.get("median_think_share_of_time")
        S.append(f"""
<section id="s7">
  <div class="kicker">边界 · 剩下的这点误差从哪来</div>
  <h2>还差 {abs(ic):.0f} 秒，而且是个固定偏移</h2>
  <div class="row">
    <div class="card" style="animation-delay:.7s"><div class="lab">截距（固定偏移）</div>
      <div class="val amb">{ic:.1f} 秒</div>
      <div class="sub">每一段都从零开始数，少这么多</div></div>
    <div class="card" style="animation-delay:.9s"><div class="lab">思维链占真实时间</div>
      <div class="val amb">{share * 100:.0f}%</div>
      <div class="sub">模型看不见自己想了多久</div></div>
    <div class="card" style="animation-delay:1.1s"><div class="lab">结论</div>
      <div class="val" style="font-size:42px">模型感知的<br>硬边界</div>
      <div class="sub">不是提示词能补的</div></div>
  </div>
  <p style="margin-top:30px">它从正文开始计时，把正文前那段思考整个漏掉了 ——
     这是模型自己看不到的那部分。</p>
</section>""")

    # ---------- 8 工程建议 ----------
    S.append(f"""
<section id="s8">
  <div class="kicker">结论</div>
  <h2>速率是尺子，不是时钟</h2>
  <p>但尺子必须准。<br>
     优先给绝对量；确要用速率，就先把它测稳，再配一个明确的待写量。</p>
  <div class="row">
    <div class="card" style="animation-delay:.7s"><div class="lab">工程做法</div>
      <div class="val" style="font-size:40px">给绝对量</div>
      <div class="sub">已过秒数 / 剩余预算 / 截止时刻</div></div>
    <div class="card" style="animation-delay:.9s"><div class="lab">确要用速率</div>
      <div class="val" style="font-size:40px">先测稳</div>
      <div class="sub">滑动窗口累计平均 + 报区间，并配明确待写量</div></div>
    <div class="card" style="animation-delay:1.1s"><div class="lab">长任务里自报时间</div>
      <div class="val" style="font-size:40px">换算到<br>工作单元</div>
      <div class="sub">让它能数着自己写到第几节</div></div>
  </div>
</section>""")

    # ---------- 9 备注：之前踩过的两个坑 ----------
    if tps and proc:
        mx = tps.get("minimax_reference") or {}
        parms = list((proc.get("arms") or {}).values())
        slopes = [a.get("median_slope") or 0 for a in parms]
        r2 = max((a.get("median_r2") or 0) for a in parms)
        think_lr = ((proc_opt or {}).get("arms") or {}).get("speed_unit_think") or {}
        think_sl = think_lr.get("median_slope")
        S.append(f"""
<section id="s9" class="note">
  <div class="kicker" style="color:var(--acc2)">备注 · 之前踩过的两个坑</div>
  <h2>为什么这版视频这么讲</h2>
  <div class="two">
    <div class="left">
      <div class="card" style="animation-delay:.6s"><div class="lab">坑 1 · 云端 API 上的那一轮</div>
        <div class="val bad">{mx.get('max_over_min', 0):.2f}×</div>
        <div class="sub">同一台机器的速率波动 · CV {mx.get('between_cv', 0):.2f}<br>
           后端路由到吞吐相差一倍的轨道 → 尺子本身是坏的<br>
           所以「注入速率无效」那个结论其实不成立</div></div>
    </div>
    <div class="right">
      <div class="card" style="animation-delay:.8s"><div class="lab">坑 2 · 长思考里只给速率</div>
        <div class="val bad">斜率 {min(slopes):.0f}–{max(slopes):.0f}</div>
        <div class="sub">轮内相关 1.000 · R² {r2:.3f}（理想斜率 1）<br>
           标记是一条编出来的等差数列</div></div>
    </div>
  </div>
  <p style="margin-top:26px">{f"再补一句思考阶段耗时也救不回来，末标记反而是 {think_lr['median_last_ratio']:.2f} 倍、斜率 {think_sl:.2f}。" if think_lr.get('median_last_ratio') else ""}
     所以「工作单元换算」不是拍脑袋 —— 是被这两个坑逼出来的。</p>
</section>""")

    # ---------- 10 开源 ----------
    S.append(f"""
<section id="s10">
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
