// 通过 CDP 直连 Chrome，按段抓「淡入过程」帧序列。
// 用法：node capture_frames.js
// 产出：out/video/frames/sN_fMM.png  +  out/video/shot_times.json
// 依赖：Node >= 22（全局 WebSocket / fetch），无需 npm 包。
'use strict';

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = process.env.LTS_ROOT || path.resolve(__dirname, '..');
const CHROME = process.env.CHROME_PATH
  || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = Number(process.env.CDP_PORT || 9333);
const PROFILE = path.join(ROOT, 'out', 'video', '_chromeprof');
const OUTDIR = path.join(ROOT, 'out', 'video', 'frames');
const PAGE = 'file:///' + path.join(ROOT, 'out', 'video', 'demo.html').replace(/\\/g, '/')
  + '?sec=0';
const W = 1920, H = 1080;

// 每段的抓帧时刻（秒）—— 覆盖 CSS 淡入动画 0.2s~1.9s 的全过程
const SHOT_TIMES = [0.12, 0.35, 0.62, 0.95, 1.30, 1.70, 2.15, 2.70];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitPort(timeoutMs = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) return await r.json();
    } catch (_) { /* not up yet */ }
    await sleep(300);
  }
  throw new Error('Chrome 调试端口没起来');
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.listeners = new Map();
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { res, rej } = this.pending.get(m.id);
        this.pending.delete(m.id);
        if (m.error) rej(new Error(`${m.error.message} (${m.error.code})`));
        else res(m.result);
      } else if (m.method) {
        const key = `${m.sessionId || ''}:${m.method}`;
        const arr = this.listeners.get(key) || [];
        arr.forEach((fn) => fn(m.params));
      }
    });
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    const msg = { id, method, params };
    if (sessionId) msg.sessionId = sessionId;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify(msg));
    });
  }
  once(method, sessionId, timeoutMs = 30000) {
    const key = `${sessionId || ''}:${method}`;
    return new Promise((res, rej) => {
      const fn = (p) => {
        clearTimeout(timer);
        const arr = this.listeners.get(key) || [];
        this.listeners.set(key, arr.filter((f) => f !== fn));
        res(p);
      };
      const arr = this.listeners.get(key) || [];
      arr.push(fn);
      this.listeners.set(key, arr);
      const timer = setTimeout(() => {
        const a = this.listeners.get(key) || [];
        this.listeners.set(key, a.filter((f) => f !== fn));
        rej(new Error(`等待 ${method} 超时`));
      }, timeoutMs);
    });
  }
}

(async () => {
  fs.mkdirSync(OUTDIR, { recursive: true });
  fs.mkdirSync(PROFILE, { recursive: true });

  const chrome = spawn(CHROME, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE}`,
    `--window-size=${W},${H}`,
    '--hide-scrollbars',
    '--force-device-scale-factor=1',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-features=Translate,MediaRouter',
    'about:blank',
  ], { stdio: 'ignore', detached: false });

  let cdp;
  try {
    await waitPort();
    const ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
    const ws = new WebSocket(ver.webSocketDebuggerUrl);
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true });
      ws.addEventListener('error', () => rej(new Error('WS 连接失败')), { once: true });
    });
    cdp = new CDP(ws);

    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget',
      { targetId, flatten: true });

    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: W, height: H, deviceScaleFactor: 1, mobile: false,
    }, sessionId);

    const loaded = cdp.once('Page.loadEventFired', sessionId);
    await cdp.send('Page.navigate', { url: PAGE }, sessionId);
    await loaded;
    await sleep(1200); // 等首屏排版 + 字体

    // 校验视口真的被撑满
    const probe = await cdp.send('Runtime.evaluate', {
      expression: 'JSON.stringify({w:innerWidth,h:innerHeight,n:document.querySelectorAll("section").length})',
      returnByValue: true,
    }, sessionId);
    const vp = JSON.parse(probe.result.value);
    console.log('viewport =', JSON.stringify(vp));
    if (vp.w !== W || vp.h !== H) {
      throw new Error(`视口不对: ${vp.w}x${vp.h} != ${W}x${H}`);
    }
    if (vp.n !== 9) throw new Error(`段数不对: ${vp.n} != 9`);

    const manifest = [];
    for (let i = 0; i < vp.n; i++) {
      // 复位到该段并重放 CSS 动画
      await cdp.send('Runtime.evaluate', {
        expression: `show(${i}); (${JSON.stringify(SHOT_TIMES)}).length`,
        returnByValue: true,
      }, sessionId);
      const t0 = Date.now();
      const files = [];
      for (let k = 0; k < SHOT_TIMES.length; k++) {
        const wait = SHOT_TIMES[k] * 1000 - (Date.now() - t0);
        if (wait > 0) await sleep(wait);
        const { data } = await cdp.send('Page.captureScreenshot', {
          format: 'png', captureBeyondViewport: false, fromSurface: true,
        }, sessionId);
        const name = `s${String(i + 1).padStart(2, '0')}_f${String(k).padStart(2, '0')}.png`;
        fs.writeFileSync(path.join(OUTDIR, name), Buffer.from(data, 'base64'));
        files.push(name);
      }
      manifest.push({ sec: i + 1, files });
      console.log(`sec ${i + 1}: ${files.length} frames  (实际 ${((Date.now() - t0) / 1000).toFixed(2)}s)`);
    }

    fs.writeFileSync(
      path.join(ROOT, 'out', 'video', 'shot_times.json'),
      JSON.stringify({ shot_times: SHOT_TIMES, manifest }, null, 2),
      'utf-8');
    console.log('DONE');
  } catch (err) {
    console.error('FAILED:', err.message);
    process.exitCode = 1;
  } finally {
    try { if (cdp) cdp.ws.close(); } catch (_) {}
    try { chrome.kill(); } catch (_) {}
    await sleep(400);
  }
})();
