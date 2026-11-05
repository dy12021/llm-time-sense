# LLM 时间感实验

> 把「上一周期的生成吞吐（token/秒）」告诉 LLM，它能不能因此获得时间感？

**一句话结论**：速率是尺子，不是时钟。尺子准了，「多久」才有意义 —— 但尺子必须先测稳。

---

## 结果（本地模型，四项判据全过）

被试：`google/gemma-4-e2b` @ 本机 LM Studio（OpenAI 兼容端点）。
每轮清空上下文、**全程严格串行、不开并发**，96 次真实调用。
判据在跑数据**之前**写死（见 `local/analyze_local.py` 的 `CRITERIA`）。

| 判据 | 内容 | 阈值 | 实测 | |
|---|---|---|---|---|
| **C1** | 稳态速率波动（前提） | max/min ≤ 1.30 且 CV ≤ 0.15 | **1.15×**，CV 0.038（n=12） | ✅ |
| **C2** | 注入速率与预估值相关 | 显著负相关 | Spearman **−0.500**，log-log b **−0.158** | ✅ |
| **C3** | 事后预估跟不跟真实耗时走 | 跨轮相关 ≥ 0.5 **或** 误差显著下降 | 对数误差 0.923 → **0.121**（p=0.0088） | ✅ |
| **C4** | 长思考里边写边报时间 | 末标记/真实 ∈ [0.5, 2.0] 且斜率 ∈ [0.5, 1.6] | **0.81×**，斜率 **1.21** | ✅ |

对照：同样两项测量在云端 API 上是 Spearman **−0.033** / b **+0.043**（等于「没用」），
而云端速率波动 **2.39×**（CV 0.920）。

**为什么上一轮说「注入 TPS 无效」？** 因为那把尺子本身是坏的 —— 请求被路由到吞吐相差一倍的
不同后端轨道，量什么都不准。换到本机，稳态波动 1.15×，同一把尺子立刻显形。

---

## 一、本地模型实验（`local/`）

### 测量口径

从 SSE 流逐块打时间戳（与云端实验同口径，便于直接对比）：

```
ttft_s     = 首 token − 请求发出
gen_s      = 末 token − 首 token      # 模型能感知的生成窗口
duration_s = 末 token − 请求发出       # 用户实际等待
tps        = 总 token(含思维链) / gen_s
```

本地模型两个特殊处理：**非流式请求返回空 body**（所以只用流式）；Gemma 4 是思考模型，
`reasoning_content` 单独收集（思维链占真实时间约 26%，模型自己看不见）。

### L1 稳定性标定（18 次）

longform 12 次 + items 6 次。

| 层 | n | max/min | 请求间 CV | TPS 中位 |
|---|---|---|---|---|
| 全部 | 18 | 1.62× | 0.102 | 154.5 |
| 去掉冷启动 | 15 | 1.35× | 0.068 | — |
| **稳态**（排除加载后前两次预热） | **12** | **1.15×** | **0.038** | **154.7** |

冷启动第 1 次请求只有 **99.6 tok/s**（稳态的 64%）。

### L2 事前预估 · 剂量-反应（30 次 = 5 臂 × 6 轮）

题面不含目标秒数，只改注入的速率数字（79.3 / 158.5 / 253.7 tok/s）。

- Spearman(注入速率, 预估值) = **−0.500**，log-log 斜率 **−0.158**
  （云端同测量 −0.033 / +0.043，等于「没用」）
- 思维链自证（最硬的证据）：

  > 注入 158.5 那轮写下「At 158.5 tokens/second, the time would be around
  > $3500 / 158.5 \approx 22$ seconds」→ 答 25 秒，真实 **25.5 秒**；
  > base 臂写下「A few seconds. Let's estimate 5-10 seconds」→ 答 8 秒，真实 **26.9 秒**。

- 「思维链里真的用了注入速率」的比例：speed_low 4/6、speed_true 4/6、speed_high 2/6、base 0/6、elapsed 0/6
- 残余误差来源：模型估不准自己要写多少 token

### L2b 事后预估（18 次 = 3 臂 × 6 轮）

**故意保留上下文**，每轮长度 500 → 3000 字（真实耗时 5.0 → 16.7 秒，变化 **3.35×**）。
注意：**长度 6× ≠ 耗时 6×** —— 耗时只涨了 3.35 倍，别把两个比值混着说。

| 臂 | 估/实际 | 对数误差 | 隐含速率 | vs base |
|---|---|---|---|---|
| base | 0.40× | 0.923 | 426.7 tok/s | — |
| speed（注入 153.4） | 1.34× | **0.295** | 123.7 | **Δ=−0.628, p=0.018** |
| elapsed（直接给秒数） | 0.89× | **0.121** | 140.6 | Δ=−0.802, p=0.0088 |

> **诚实标注**：base 臂的跨轮 Spearman 也是 1.0 —— 真正的区分在**误差量级**，不是秩相关。

### L3 长思考过程时间感 —— 失败（18 次）

让模型在一条长回复里边写边标「已用时 X 秒」，把每个标记定位到流里的**真实经过秒数**对账。

| 臂 | 标记数 | 轮内相关 | 末标记/真实 | 节拍斜率 |
|---|---|---|---|---|
| base | 12 | +1.000 | 11.3× | 15.8 |
| speed | 12 | +1.000 | 16.4× | 22.3 |
| speed_len | 12 | +1.000 | 14.9× | 21.3 |

**轮内相关全是 1.0，斜率却高达 15–22（理想 1.0）**：标记是一条完美等差数列，R² = 0.998 ——
比真实时间规律得多。它不是在测量流逝，是在**编一个看起来合理的节拍**。

### L3b 怎么修（12 次）

| 臂 | 末标记/真实 | 节拍斜率 | 截距 |
|---|---|---|---|
| **speed_unit**（速率 + 「每小节约产出 N 个 token」） | **0.81×** | **1.21** | −5.3 s |
| speed_unit_think（再补思考阶段耗时） | 2.88× | 3.91 | −13.4 s |

两点结论：

1. **速率只告诉模型「我多快」，不告诉它「写到哪了」**。补一句「每写完一个小节大约产出 N 个
   token」，模型只要会数小节，就能自己推出大概过了多久。
2. **给得更多不一定更好**。补上思考阶段耗时反而更差 —— 模型把 3.4 秒当成了**每节步长**。
   换算关系必须写成「每单元多少秒」这种无歧义形式。
3. 残余截距 −5.3 秒 = 模型看不见的思考阶段（它从 0 开始数）。

### 现场演示

`local/demo.py` 三步实时跑一遍，输出存 `out/video/demo_output.txt`：

```
步骤 3 · 长思考过程中，它能边写边报时间吗？
  模型自报      真实流逝      差
  0.0 秒        5.3 秒      -5.3 秒
  ...
  11.0 秒      15.3 秒      -4.3 秒
→ 末标记 11 秒 / 真实 15.3 秒 = 0.72×
```

---

## 二、上一轮：云端 API（MiniMax，`harness/`）

上一轮在同一台机器上做了 450 轮短任务 + 148 次长程实验，结论是「注入 TPS 无效」。
原因不是「模型不会用速率」，而是**速率本身抖动 2.39×**（请求被路由到吞吐相差一倍的
不同后端轨道）—— 尺子是坏的，量什么都不准。

四臂设计（唯一差异是 system 消息里的反馈块，任务文本逐字相同）：

| 臂 | 反馈 | 角色 |
|---|---|---|
| `base` | 无 | 基线 |
| `speed` | 上一周期速度（token/秒） | **核心假设** |
| `speed_count` | 上一周期 token 数 + 速度 | 补「分子」 |
| `elapsed` | 上一周期耗时（秒） | 阳性对照 |

长程实验：

```
Phase A  标定   harness/tps_long.py          30 秒连续生成 × 12 次，测真实吞吐
        分析   harness/analyze_tps.py        串行断言 / 滑动窗口 TPS / 方差归因
Phase B v1      harness/phase_b.py            四臂 30 秒实验（48 次）
Phase B2       harness/phase_b2.py            去 echo + 剂量-反应（40 次自持 + 60 次换算）
Phase C        harness/phase_c.py            过程时间感（短/长规格）
```

**Phase B2 的两个设计要点**（Phase B v1 的缺陷所致）：

1. **不告诉目标秒数** —— v1 把「目标 = 30 秒」写进题面，模型 100% 复述目标，预估值不可用。
2. **剂量-反应** —— 任务、措辞、条数完全相同，只改注入的速率数字（40 / 76.5 / 120 token/秒）。
   臂按**逐轮交错**顺序执行，消除顺序/漂移混淆。

串行性证据：每次调用记录 `[t_request, t_last]`，分析脚本断言排序后的区间互不重叠。

**Phase C 踩出来的工程要点**：

1. **锚点必须是模型数得动的结构**。三种标记方式实测：「每 N 字标一次」→ 标记全堆在文末；
   「每 N 段标一次」→ **0 个标记**（指令被无视）；「每 N 个**连续编号**小节标一次」→ 12/12 全部 inline。
2. **措辞歧义会毁掉长规格** —— 「每写完第 1 个小节」会被读成「只在小节 1 后面标」，
   必须写成「每写完**一个小节**……全文共 N 个……**不是只在小节 1 后面标**」。

---

## 视频

《我解决了大模型的时间感》（1920×1080，5 分 10 秒 / 310.2 秒，H.264 + AAC）：

- 成片 `out/video/final.mp4` —— **不入库**（体积大），本地脚本可完全复现
- 幻灯片 `out/video/demo.html` —— 自包含单文件（图表内嵌 base64），可直接打开
- 封面 `out/video/cover.png`、元数据 `out/video/meta.json`

**结构（10 段）**：主线只讲**成功的三招** —— ① 事前注入速率 ② 事后预估
③ 长思考状态换算到「工作单元」。之前失败的两次尝试（云端速率抖动导致
「注入速率无效」；长思考里模型编等差数列）整体下沉到第 9 段「备注」页，
只留数字与一句「不是拍脑袋，是被这两个坑逼出来的」。

```powershell
# 旁白 → 排期（时长按解码后的 PCM 实际长度算，不按容器时长）
python  local\make_voice_script.py      # 旁白脚本（数字全部从 out/*.json 取）
python  local\tts.py --script local\voice_script.json --outdir out\voice
python  local\make_video_plan.py

# 幻灯片
python  local\make_demo_page.py

# 视频：抓帧(CDP 直连 Chrome) → 分段合成 → 拼旁白 → 响度标准化
node    local\capture_frames.js
python  local\build_final.py
python  local\normalize_audio.py
python  local\verify_video.py     # 逐段抽帧目检 + 慢推检测
```

---

## 目录

```
local/          本地 LM Studio 实验（视频主体）
  lclient.py            流式客户端（OpenAI 兼容；逐块时刻/字符数全量落盘）
  calib.py              L1 稳定性标定
  exp_time_sense.py     pre | posthoc | process | process_opt
  analyze_local.py      分析 + CRITERIA 判据 → out/local_summary.json
  analyze_tps.py        标定分析（merged/warm/steady 三层）
  analyze_used_rate.py  思维链「有没有真的用速率」
  demo.py               现场演示
  make_charts.py        4 张图 → out/video/figs/（本机稳定性 / 云端抖动 / 剂量反应 / 过程时间感）
  make_demo_page.py     演示页 → out/video/demo.html
  make_voice_script.py  旁白脚本 → local/voice_script.json（唯一真源，别手改 json）
  callcount.py          调用次数统计（全项目共用一份口径）
  make_video_plan.py    逐段时长排期 → out/video/plan.json
  tts.py                MiniMax TTS（speech-02-hd）
  capture_frames.js     CDP 直连 Chrome 抓帧（Node ≥ 22，零依赖）
  build_final.py        分段合成 → out/video/final.mp4
  make_cover.py         封面 + 元数据
  verify_video.py       成片终检
harness/        上一轮云端 API 实验
raw/             逐轮原始记录 JSONL（可审计）
out/             summary.json / 图 / 报告
scripts/         scan_sensitive.py（开源前脱敏扫描）
REPORT_LOCAL.md  本地实验报告
REPORT_LONGRUN.md 长程实验报告（Phase A/B/B2/C）
```

## 跑

```powershell
# 本地实验（需要 LM Studio 加载好模型，默认 http://127.0.0.1:1234/v1）
$env:LMSTUDIO_BASE = "http://127.0.0.1:1234/v1"
python local\calib.py            --repeats 12 --mode longform --words 3500 --fresh
python local\exp_time_sense.py   pre     --repeats 6
python local\exp_time_sense.py   posthoc --repeats 6
python local\exp_time_sense.py   process --repeats 6 --words 1800
python local\exp_time_sense.py   process_opt --repeats 6 --words 1800

# 分析（判据写死在 analyze_local.py 里）
python local\analyze_tps.py
python local\analyze_local.py
python local\analyze_used_rate.py
python local\make_report_local.py     # → REPORT_LOCAL.md

# 上一轮云端实验（需要 api.minimax.cn 额度）
$env:MINIMAX_CONFIG = "C:\path\to\config.toml"
python harness\runner.py --mock --repeats 2 --out raw\mock_records.jsonl --fresh
```

### 环境变量

所有本机路径与端点都可覆盖，仓库里不留任何绝对路径：

| 变量 | 含义 | 默认 |
|---|---|---|
| `LTS_ROOT` | 仓库根目录 | 由脚本自身位置推导 |
| `LMSTUDIO_BASE` | LM Studio 端点 | `http://127.0.0.1:1234/v1` |
| `LMSTUDIO_MODEL` | 模型名 | `google/gemma-4-e2b` |
| `MINIMAX_CONFIG` | MiniMax 配置（含 api_key） | 必填 |
| `FFMPEG` / `FFPROBE` | ffmpeg 可执行文件 | 从 PATH 查找 |
| `CHROME_PATH` | Chrome 可执行文件 | 常见安装路径 |

## 注意事项

- MiniMax M3.1 强制开启思维链，`reasoning_effort` 只调档；`max_tokens` 要用 `max_completion_tokens`。
- 直连 `api.minimax.cn` 走 Token Plan，额度触顶时返回 429（错误码 **2056**），不是普通限流，退避重试无效。
- 答案解析必须按标记位（`预计耗时：` / `回复耗时秒数：` / `已过秒数：`）取值，
  否则正文里的数字会被误当成时间估计。
- 标记正则里「秒」要写成**可选**（模型会写成「〔已用时 15〕」而不带单位）。
- **判断长思考时间感不能只看轮内相关** —— 编出来的等差数列轮内相关同样是 1.0，
  必须同时看「末标记/真实倍数」与「节拍斜率」。
- 开源前跑 `python scripts\scan_sensitive.py --staged`，**0 命中**才算干净。
  ⚠️ **扫描器按 UTF-8 读**：UTF-16 文件（Windows 产物）会读成乱码 → **正则一条都匹配不到 → 假阴性**。
  本项目就踩过：`out/video/demo_output.txt` 一直是 UTF-16，扫描器长期报「0 命中」，
  转成 UTF-8 后立刻命中里面的私有网段地址。**扫之前先确认每个文件能被正确解码。**
- **TTS 旁白要过一遍读音自检**：同一引擎合成候选说法 → 转写回来 → 比对。
  `local\tts_probe.py` 负责合成那半边（转写那半边走 STT）。本项目实测：
  - MiniMax TTS 对 `Gemma 4 E2B` **真的念成「412B」**（两条独立 ASR 链路一致）→ 改成说「Google Gemma 4 这个模型」；
  - 对「待写量」发音含糊（一条链路听成「代谢量」、另一条听成「带血量」）→ 改成「一个明确的目标，比如还要写多少字」；
  - **同音字会被 TTS 换掉**：本项目实测「也**救不回来**」被念成「也**就补回来**」——
    「救不 / 就补」同音，语义正好相反，转写回来才发现。改用没有歧义的「**也不管用**」。
  - **上游 ASR 的过滤器会误伤整段音频**：44 秒的一整段旁白丢给两条链路都被截断并回
    「blocked by filters」，**拆成两半分别测就都正常** —— 遇到这种情况先分段复测，
    不要直接判定音频坏了，更不要因此重做视频。
  - **反过来，STT 也会造字**：转写链路会把「Gemma 4」补成「Gemma 4B」、把「根因」写成「原因」、
    把「尺子」写成「池子」、「秒数」写成「描述」。
    这类是**转写端假阳性**，不是音频错了 —— 判定时**必须用第二条独立链路仲裁**
    （`connector__matrix__audios_understand`，音频问答而非转写），
    并做「真含该字」/「不含该字」两组对照；**同一链路的重试不能拿来仲裁**，它的偏差会自洽。
    本项目就靠这一步确认成片里的「Gemma 4」没有多念一个 B。

---

## License

[MIT](LICENSE) © 2026 DONG YANG
