# onepass-audioclean-seg

Repo2 分段模块：将长音频切成候选片段（segments）

## 定位与边界

### 包含范围
- 将长音频文件分割成候选片段（segments）
- 支持多种分段策略（silence、energy、vad）
- 本地离线处理，无需网络连接
- 面向 Repo1 的输出格式（`audio.wav` + `meta.json`）

### 不包含范围
- ❌ ASR（语音识别）
- ❌ 口误检测
- ❌ 音频剪辑/编辑功能
- ❌ 在线服务依赖
- ❌ 模型权重下载

## 安装

```bash
# 开发安装（仅 silence 和 energy 策略）
pip install -e ".[dev]"

# 启用 VAD 策略（需要 webrtcvad）
pip install -e ".[dev,vad]"
```

## 用法

### 检查依赖

Repo2 默认分段策略依赖 ffmpeg 的 `silencedetect` 滤镜，因此需要系统安装 ffmpeg 和 ffprobe。

```bash
# 基本用法
audioclean-seg check-deps

# JSON 格式输出
audioclean-seg check-deps --json

# 详细输出
audioclean-seg check-deps --verbose
```

`check-deps` 会检查以下内容：
- `ffmpeg` 是否存在（PATH 可找到）且可执行
- `ffprobe` 是否存在（PATH 可找到）且可执行
- `ffmpeg` 是否支持 `silencedetect` 滤镜
- `webrtcvad` 是否已安装（可选依赖，默认缺失不视为失败）
- 输出版本信息

**严格模式**（R9 新增）：
```bash
# 使用 --strict 模式，webrtcvad 缺失也会导致检查失败
audioclean-seg check-deps --strict
```

#### 安装 ffmpeg

如果依赖检查失败，请根据操作系统安装 ffmpeg：

- **macOS**: `brew install ffmpeg`
- **Ubuntu/Debian**: `sudo apt-get install ffmpeg`
- **CentOS/RHEL**: `sudo yum install ffmpeg`
- **Windows**: 从 [ffmpeg.org](https://ffmpeg.org) 下载并加入 PATH

### 音频分段

#### 输入类型（R3）

`segment` 命令支持多种输入形态：

- **单个音频文件** (`--in audio.wav`): 直接指定音频文件路径
- **工作目录** (`--in workdir/`): 包含 `audio.wav` 的目录（可选 `meta.json`）
- **批处理根目录** (`--in root_dir/`): 递归扫描所有 `audio.wav` 文件
- **清单文件** (`--in manifest.jsonl`): Repo1 输出的清单文件，自动解析成功项

#### 输出模式（R3）

- `--out-mode in_place`（默认）: 如果 job 有 workdir，输出到 `workdir/seg`；否则输出到 `out_root/<name>/seg`
- `--out-mode out_root`: 全部输出到 `out_root` 下镜像目录（即使有 workdir 也不写回）

#### 分段策略选择（R8/R9）

R9 版本支持多种分段策略，通过 `--strategy` 参数选择：

- **`silence`**（默认）：基于 ffmpeg silencedetect 的静音检测
  - 依赖 ffmpeg 和 ffprobe
  - 适用于静音明显的录音
  - 参数：`--silence-threshold-db`、`--min-silence-sec`

- **`energy`**：基于 RMS 能量的语音/非语音检测（纯 Python）
  - 不依赖 ffmpeg，适合噪声底高、静音不明显的录音
  - 参数：`--energy-frame-ms`、`--energy-hop-ms`、`--energy-smooth-ms`、`--energy-threshold-rms`、`--energy-min-speech-sec`

- **`vad`**（R9 新增）：基于 webrtcvad 的语音活动检测
  - 需要安装 webrtcvad：`pip install -e ".[vad]"` 或 `pip install webrtcvad>=2.0.10`
  - 更贴近经典 VAD 算法，适合需要稳定离线 VAD 的场景
  - 输入要求：PCM16 mono，采样率 8000/16000/32000/48000（推荐 16000）
  - 若音频格式不符，策略会尝试使用 ffmpeg 自动重采样（如果 ffmpeg 可用）
  - 参数：
    - `--vad-aggressiveness`：攻击性级别 0..3（默认 2）
    - `--vad-frame-ms`：帧长度 10/20/30（默认 30）
    - `--vad-sample-rate`：目标采样率 8000/16000/32000/48000（默认 16000）
    - `--vad-min-speech-sec`：最小语音长度（默认 0.20）

**适用场景建议**：
- 静音明显：使用 `silence` 策略（默认）
- 噪声底高/静音不明显：尝试 `energy` 策略，并调整 `--energy-threshold-rms`（默认 0.02，可尝试 0.01-0.05）
- 需要稳定 VAD：使用 `vad` 策略，推荐在 Repo1 ingest 阶段设置 `sample_rate=16000, channels=1` 以避免重采样开销

#### 自动策略选择（Auto-strategy，R9 新增）

R9 版本新增 `--auto-strategy` 功能，按顺序尝试多个策略，自动选择第一个通过质量门槛的策略：

```bash
# 启用 auto-strategy
audioclean-seg segment --in workdir --out out_root --out-mode out_root --auto-strategy --emit-segments
```

**默认行为**：
- 策略尝试顺序：`silence,vad,energy`（可通过 `--auto-strategy-order` 自定义）
- 质量门槛：
  - 最小片段数：`--auto-strategy-min-segments`（默认 2）
  - 最小总语音时长：`--auto-strategy-min-speech-total-sec`（默认 3.0 秒）
  - 避免覆盖几乎全长（speech_total_sec / duration < 0.98）

**适用场景**：
- 噪声底高/静音不明显时，启用 `--auto-strategy` 可自动降级到更合适的策略
- 不确定使用哪个策略时，让系统自动选择

#### R11 新功能：配置文件支持

R11 版本新增了配置文件支持，避免每次敲一堆 CLI 参数：

**配置文件格式**（支持 JSON 和 YAML）：

```json
{
  "strategy": {
    "name": "energy",
    "auto": {
      "enabled": false,
      "order": ["silence", "vad", "energy"],
      "min_segments": 2,
      "min_speech_total_sec": 3.0
    }
  },
  "silence": {
    "threshold_db": -35.0,
    "min_silence_sec": 0.35
  },
  "energy": {
    "threshold_rms": 0.02,
    "frame_ms": 30.0,
    "hop_ms": 10.0,
    "smooth_ms": 100.0,
    "min_speech_sec": 0.20
  },
  "vad": {
    "aggressiveness": 2,
    "frame_ms": 30,
    "sample_rate": 16000,
    "min_speech_sec": 0.20
  },
  "postprocess": {
    "min_seg_sec": 1.0,
    "max_seg_sec": 25.0,
    "pad_sec": 0.1
  },
  "exports": {
    "timeline": false,
    "csv": false,
    "mask": "none",
    "mask_bin_ms": 50.0
  },
  "runtime": {
    "jobs": 1,
    "overwrite": false,
    "out_mode": "in_place"
  },
  "validate": {
    "enabled": false,
    "strict": false
  }
}
```

**使用配置文件**：

```bash
# 使用 JSON 配置文件
audioclean-seg segment --config config.json --in audio.wav --out output_dir --emit-segments

# 使用 YAML 配置文件（需要安装 pyyaml: pip install -e ".[yaml]"）
audioclean-seg segment --config config.yaml --in audio.wav --out output_dir --emit-segments

# 使用 --set 覆盖配置项（可多次使用）
audioclean-seg segment \
    --config config.json \
    --set strategy.name=energy \
    --set postprocess.min_seg_sec=2.0 \
    --in audio.wav \
    --out output_dir \
    --emit-segments

# 打印合并后的最终配置并退出（不执行分段）
audioclean-seg segment --config config.json --dump-effective-config
```

**配置合并优先级**（从低到高）：
1. 默认值（defaults）
2. 配置文件（config file）
3. `--set` 覆盖
4. 显式 CLI 参数（命令行直接提供的参数）

**YAML 支持**：
- YAML 为可选依赖，需要安装：`pip install -e ".[yaml]"`
- 如果使用 `.yaml` 或 `.yml` 配置文件但未安装 pyyaml，会返回退出码 2 并提示安装

#### 基本用法

```bash
# 单个音频文件（dry-run 模式，只打印计划）
audioclean-seg segment --in audio.wav --out output_dir --dry-run

# 工作目录（in_place 模式，输出到 workdir/seg）
audioclean-seg segment --in workdir/ --out output_dir --out-mode in_place

# 批处理根目录（out_root 模式，镜像目录结构）
audioclean-seg segment --in root_dir/ --out output_dir --out-mode out_root --dry-run

# manifest.jsonl 文件
audioclean-seg segment --in manifest.jsonl --out output_dir --dry-run

# 使用 silence 策略（默认）
audioclean-seg segment \
    --in audio.wav \
    --out output_dir \
    --strategy silence \
    --min-silence-sec 0.35 \
    --silence-threshold-db -35 \
    --min-seg-sec 1.0 \
    --max-seg-sec 25.0 \
    --pad-sec 0.1 \
    --emit-segments \
    --emit-wav \
    --jobs 4 \
    --overwrite

# 使用 energy 策略（纯 Python，不依赖 ffmpeg）
audioclean-seg segment \
    --in audio.wav \
    --out output_dir \
    --out-mode out_root \
    --strategy energy \
    --energy-threshold-rms 0.02 \
    --energy-min-speech-sec 0.20 \
    --min-seg-sec 1.0 \
    --max-seg-sec 25.0 \
    --pad-sec 0.1 \
    --emit-segments

# 使用日志选项
audioclean-seg segment \
    --in audio.wav \
    --out output_dir \
    --log-level DEBUG \
    --log-file segment.log
```

#### R8 新功能：Energy 策略 + 统一策略接口

R8 版本新增了 `energy` 策略和统一的策略接口：

1. **Energy 策略**：
   - 基于短帧 RMS（能量）判定语音/非语音
   - 纯 Python 实现，不依赖 ffmpeg
   - 支持平滑、滞回、最小静音约束
   - 适用于噪声底高、静音不明显的录音

2. **统一策略接口**：
   - 所有策略实现 `SegmentStrategy.analyze()` 接口
   - 返回统一的 `AnalysisResult` 对象
   - 便于后续扩展新策略（如 R9 的 webrtcvad）

**Energy 策略参数**：
- `--energy-frame-ms`（默认 30）：帧长度（毫秒）
- `--energy-hop-ms`（默认 10）：帧移（毫秒）
- `--energy-smooth-ms`（默认 100）：平滑窗口长度（毫秒）
- `--energy-threshold-rms`（默认 0.02）：RMS 阈值（归一化到 [0, 1]）
- `--energy-min-speech-sec`（默认 0.20）：最小语音长度（秒，用于硬过滤极短语音岛）

**输出文件**：
- `energy.json`：Energy 策略的中间产物，包含 RMS 序列、语音段等信息
- `segments.jsonl`：每个 segment 包含 `strategy` 字段（"silence" 或 "energy"）

#### R3 新参数

- `--pattern`: 扫描根目录时使用的文件名模式（默认: `audio.wav`）
- `--out-mode`: 输出模式，`in_place` 或 `out_root`（默认: `in_place`）
- `--dry-run`: dry-run 模式，只打印计划不写入文件（默认: `False`）

#### R4 新功能：静音分析

R4 版本引入 `--analyze` 参数，可以对音频运行 `ffmpeg silencedetect` 分析并输出静音区间中间文件。

**基本用法**:

```bash
# 运行静音分析（需要关闭 --dry-run）
audioclean-seg segment --in <workdir> --out <out_root> --out-mode out_root --analyze

# 指定静音检测阈值
audioclean-seg segment \
    --in audio.wav \
    --out output_dir \
    --analyze \
    --silence-threshold-db -40 \
    --min-silence-sec 0.35
```

**输出文件**:

- `<out_dir>/silences.json`: 静音区间列表（JSON 格式）
- `<out_dir>/seg_report.json`: 更新 `analysis.silence` 字段，包含分析摘要

**注意**:
- `--analyze` 需要关闭 `--dry-run`（两者不能同时使用）
- `silence` 策略需要系统安装 `ffmpeg` 和 `ffprobe`
- `energy` 策略不依赖 ffmpeg，纯 Python 实现

#### R5 新功能：生成语音片段

R5 版本引入 `--emit-segments` 参数，可以从静音区间生成语音片段并输出 `segments.jsonl`。

#### R6 新功能：MVP 规整增强 + 能量特征 + 可选切片导出

R6 版本实现了真正的 MVP 规整功能，包括：

1. **规整算法增强**：
   - 自动合并重叠/粘连的段（pad 后可能产生）
   - 短段不再直接丢弃，而是确定性地向邻段合并（减少碎片）
   - 超长段按等长策略切分（保证后续 ASR 可控）

2. **能量特征计算**：
   - 自动计算每个片段的 RMS（Root Mean Square）值
   - 可选计算 energy_db（分贝值）
   - 使用 Python wave 库读取 PCM 数据，无需额外依赖

3. **可选 WAV 切片导出**：
   - 使用 `--emit-wav` 参数可将每个片段导出为独立的 WAV 文件
   - 输出到 `<out_dir>/segments/` 目录下

**基本用法**:

```bash
# 从已有的 silences.json 生成 segments.jsonl（需要先运行 --analyze 或自动触发分析）
audioclean-seg segment --in <workdir> --out <out_root> --out-mode out_root --emit-segments

# 一次性运行分析并生成片段（推荐）
audioclean-seg segment \
    --in audio.wav \
    --out output_dir \
    --emit-segments \
    --strategy silence \
    --min-seg-sec 1.0 \
    --max-seg-sec 25.0 \
    --pad-sec 0.1

# 生成片段并导出 WAV 文件
audioclean-seg segment \
    --in audio.wav \
    --out output_dir \
    --emit-segments \
    --emit-wav \
    --min-seg-sec 1.0 \
    --max-seg-sec 25.0 \
    --pad-sec 0.1

# 分步运行（先分析，再生成片段）
audioclean-seg segment --in <workdir> --out <out_root> --out-mode out_root --analyze
audioclean-seg segment --in <workdir> --out <out_root> --out-mode out_root --emit-segments --min-seg-sec 1.0 --max-seg-sec 25.0 --pad-sec 0.1
```

**输出文件**:

- `<out_dir>/segments.jsonl`: 语音片段列表（JSONL 格式，一行一个片段）
- `<out_dir>/segments/seg_*.wav`: 每个片段的 WAV 文件（如果启用 `--emit-wav`）
- `<out_dir>/seg_report.json`: 更新 `segments` 字段，包含片段统计信息

#### R10 新功能：可视化/调参友好输出

R10 版本新增了可视化友好的导出功能和片段元数据扩充：

1. **片段 flags/source/quality 字段**（R10 新增）：
   - `flags`: 标志列表，如 `["split_from_long", "merged_short", "edge_clipped", "low_energy"]`
   - `source`: 来源信息（策略、是否 auto-chosen、原始索引等）
   - `quality`: 质量信息（rms、energy_db、confidence_hint 占位）

2. **可视化友好导出**：
   - `--export-timeline`: 导出 `timeline.json`（单文件，供前端直接加载）
   - `--export-csv`: 导出 `segments.csv`（表格友好）
   - `--export-mask`: 导出 `mask.json`（降采样帧级信息，支持 `none|energy|vad|auto`）
   - `--mask-bin-ms`: mask 降采样 bin 大小（默认 50 毫秒）
   - `--low-energy-rms-threshold`: 低能量 RMS 阈值（默认 0.01）

3. **summarize 命令**：
   - 快速浏览 segments.jsonl 摘要
   - 支持文件、目录或 out_root 输入
   - 支持 `--json` 格式输出

**基本用法**:

```bash
# 生成片段并导出可视化文件
audioclean-seg segment \
    --in audio.wav \
    --out output_dir \
    --emit-segments \
    --export-timeline \
    --export-csv \
    --export-mask auto \
    --mask-bin-ms 50 \
    --low-energy-rms-threshold 0.01

# 快速浏览摘要
audioclean-seg summarize --in output_dir

# JSON 格式输出
audioclean-seg summarize --in output_dir --json --top 10
```

**输出文件**:

- `<out_dir>/timeline.json`: 时间轴数据（供前端渲染）
- `<out_dir>/segments.csv`: 表格格式的片段列表
- `<out_dir>/mask.json`: 降采样帧级信息（用于绘制语音概率/能量条）

**Repo6 集成说明**：

Repo6 可以直接加载 `timeline.json` + `mask.json` 做三轨道渲染的 Track2（Auto）基础。`timeline.json` 包含前端渲染需要的子集字段，`mask.json` 提供降采样后的帧级信息用于绘制可视化图表。

**segments.jsonl 格式（R6 增强）**:

每行是一个 JSON 对象，包含以下字段：

- `id`: 片段 ID（如 `"seg_000001"`，按 start 升序编号）
- `start_sec`: 片段开始时间（秒，round(3)）
- `end_sec`: 片段结束时间（秒，round(3)）
- `duration_sec`: 片段时长（秒，round(3)）
- `source_audio`: 源音频文件路径（绝对路径）
- `pre_silence_sec`: 该片段前一个静音区间的时长（秒，若没有则为 0，round(3)）
- `post_silence_sec`: 该片段后一个静音区间的时长（秒，若没有则为 0，round(3)）
- `is_speech`: 是否为语音片段（`true`）
- `strategy`: 分段策略（`"silence"`）
- `rms`: RMS 值（归一化到 [0, 1]，round(6)，R6 新增）
- `energy_db`: 能量 dB 值（round(2)，R6 新增，可选）
- `notes`: 额外信息（如 `{"split_reason":"max_len"}` 或 `{"merged_from":2}`，R6 新增，可选）
- `flags`: 标志列表（R10 新增），如 `["split_from_long", "merged_short", "edge_clipped", "low_energy"]`
- `source`: 来源信息（R10 新增），包含策略、是否 auto-chosen、原始索引等
- `quality`: 质量信息（R10 新增），包含 rms、energy_db、confidence_hint 等

所有时间字段统一保留 3 位小数，RMS 保留 6 位小数，energy_db 保留 2 位小数。

**默认参数（R6 更新）**:

- `--min-silence-sec`: 0.35（秒）
- `--min-seg-sec`: 1.0（秒）
- `--max-seg-sec`: 25.0（秒）
- `--pad-sec`: 0.10（秒）
- `--silence-threshold-db`: -35.0（dB）

**注意**:

- `--emit-segments` 需要关闭 `--dry-run`（两者不能同时使用）
- 如果 `silences.json` 不存在，`--emit-segments` 会自动触发分析（方案1，推荐）
- 目前仅支持 `silence` 策略（其他策略会跳过并打印 SKIP-EMIT）
- 如果 `segments.jsonl` 已存在且 `--overwrite=false`，会跳过该 job
- `--emit-wav` 需要系统安装 `ffmpeg`，如果未找到会记录 warning 但不会导致整个 job 失败
- 规整算法保证确定性：所有操作（合并、切分）都是可复现的
- 超长段切分使用等长策略（`split_strategy="equal"`），保证可复现性

**版本说明**:

- **R3**: 输入解析与计划输出，会生成 `seg_report.json` 但不会实际分段
- **R4**: 实现了 `silencedetect` 静音分析功能，可以输出静音区间中间文件
- **R5**: 实现了从静音区间生成语音片段的功能，可以输出 `segments.jsonl`
- **R6**: 实现了 MVP 规整增强（merge/split）+ 能量特征 + 可选切片导出
- **R7**: 协议固化与输出验证（validate）+ 批处理汇总（run_summary.json）
- **R8-R10**: 实现了更复杂的分段策略（`energy`、`vad`）和可视化友好输出
- **R11**: 配置系统 + 可复现实验快照 + 回归基准（golden）+ 错误分级与退出码规范

#### R7 新功能：输出验证与批处理汇总

R7 版本引入了输出验证功能和批处理汇总报告。

**输出验证**:

```bash
# 验证单个 segments.jsonl 文件
audioclean-seg validate --in segments.jsonl

# 验证目录（递归扫描所有 segments.jsonl）
audioclean-seg validate --in out_root/

# 严格模式（将 warnings 视为 errors）
audioclean-seg validate --in out_root/ --strict

# JSON 格式输出
audioclean-seg validate --in out_root/ --json
```

`validate` 命令会检查：
- `segments.jsonl` 的格式和字段完整性
- 数值约束（start_sec >= 0, end_sec > start_sec, duration_sec 一致性等）
- ID 连续性和格式（seg_000001, seg_000002, ...）
- 片段排序和重叠检查
- 与 `seg_report.json` 和 `silences.json` 的一致性

**--validate-output 选项**:

在 `segment` 命令中，可以使用 `--validate-output` 选项在生成 `segments.jsonl` 后立即验证：

```bash
audioclean-seg segment \
    --in audio.wav \
    --out output_dir \
    --emit-segments \
    --validate-output
```

如果验证失败，该 job 会被标记为 FAIL，但会继续处理其他 job。

**run_summary.json**:

每次运行 `segment` 命令（包括 dry-run）后，会在输出根目录下生成 `run_summary.json`，包含：

- `run_id`: 运行唯一标识符
- `started_at` / `finished_at`: 开始和结束时间
- `cli_args`: 完整参数快照
- `counts`: 任务统计（jobs_total, jobs_planned, jobs_analyzed, jobs_emitted, jobs_failed, jobs_skipped）
- `totals`: 总时长统计（speech_total_sec, silences_total_sec）
- `failures`: 失败任务列表
- `dry_run`: 是否为 dry-run 模式

**run_manifest.json**（R11 新增）:

每次运行 `segment` 命令（非 dry-run）后，会在输出根目录下生成 `run_manifest.json`，包含可复现实验快照：

- `tool`: 工具名称（"onepass-audioclean-seg"）
- `version`: 包版本号
- `git`: Git commit（可选，从环境变量 GIT_COMMIT 或 .git 读取）
- `started_at` / `finished_at`: 开始和结束时间
- `command`: 完整命令行参数（argv）
- `effective_config`: 合并后的最终配置（与 `--dump-effective-config` 一致）
- `environment`: 环境信息
  - `python_version`: Python 版本
  - `platform`: 平台信息
  - `deps`: 依赖版本（ffmpeg_version, ffprobe_version, webrtcvad_version, pyyaml_version）
- `jobs`: 任务列表，每个任务包含：
  - `job_id`: 任务 ID
  - `audio_path`: 音频文件路径
  - `out_dir`: 输出目录
  - `status`: 状态（analyzed, emitted, failed, skipped 等）
  - `chosen_strategy`: 使用的策略
  - `segments_count`: 片段数量
  - `speech_total_sec`: 总语音时长
  - `errors_count` / `warnings_count`: 错误/警告数量

**seg_report.json 元数据**（R11 新增）:

每个 job 的 `seg_report.json` 现在包含：

- `tool`: 工具信息（name, version）
- `config_hash`: 配置哈希值（用于可复现性）
- `audio_fingerprint`: 音频指纹（轻量级标识，格式：sha256[:16]:sr x ch:frames）

**协议文档（schemas/）**:

仓库中的 `schemas/` 目录包含三个 JSON Schema 文件（仅作为文档，运行时不需要 jsonschema 库）：

- `segments.v1.schema.json`: segments.jsonl 格式定义
- `silences.v1.schema.json`: silences.json 格式定义
- `seg_report.v1.schema.json`: seg_report.json 格式定义

这些 schema 文件用于：
- 协议文档和参考
- 后续版本兼容性保证（v1 固定后，新增字段只能作为 optional）
- 外部工具集成参考

### 全局选项

- `--log-level`: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL），默认 INFO
- `--log-file`: 日志文件路径（可选）

### 错误退出码（R11）

R11 版本统一了错误类型与退出码规范，便于流水线自动化：

- **退出码 0**: 成功
- **退出码 1**: 运行时处理错误（分析失败、生成片段失败等）
- **退出码 2**: 用户参数错误/依赖缺失/输入文件不存在/配置错误/验证失败

**错误类型**：

- `ConfigError`: 配置文件格式错误、无法解析等 -> exit 2
- `ArgError`: CLI 参数无效、冲突等 -> exit 2
- `DependencyMissingError`: 必需依赖未安装（如 pyyaml 缺失但使用了 .yaml 配置）-> exit 2
- `InputNotFoundError`: 输入文件不存在 -> exit 2
- `RuntimeProcessingError`: 运行时处理错误 -> exit 1
- `ValidationError`: validate 命令发现的问题 -> exit 2

**示例**：

```bash
# 输入文件不存在 -> exit 2
audioclean-seg segment --in /nonexistent/audio.wav --out output_dir
echo $?  # 输出 2

# 配置文件不存在 -> exit 2
audioclean-seg segment --config /nonexistent/config.json --in audio.wav --out output_dir
echo $?  # 输出 2

# YAML 配置但 pyyaml 未安装 -> exit 2
audioclean-seg segment --config config.yaml --in audio.wav --out output_dir
echo $?  # 输出 2
```

## 开发

```bash
# 运行测试
pytest -q

# 运行单个测试
pytest tests/test_cli_help.py -v

# 运行 golden 测试（R11）
pytest tests/test_golden_segments_output.py -v
```

### 回归基准测试（Golden Tests，R11）

R11 版本引入了回归基准测试，确保给定固定输入与配置时，输出 segments.jsonl 必须稳定。

**Golden 测试目录结构**：

```
tests/golden/
├── config.json              # 固定配置
├── expected_segments.jsonl  # 期望输出（文本文件，可提交）
└── assets/                  # 测试音频文件（由测试运行时生成）
```

**更新期望输出**：

如果算法改进导致输出变化，需要更新 `tests/golden/expected_segments.jsonl`：

1. 运行 golden 测试（会失败并打印实际输出）
2. 将实际输出复制到 `tests/golden/expected_segments.jsonl`
3. 重新运行测试验证

**Golden 测试比较规则**：

- 只比较关键字段：`id`, `start_sec`, `end_sec`, `duration_sec`, `flags`, `strategy`
- 不比较 `rms` 和 `energy_db`（浮点值可能有小误差）
- `source_audio` 路径会被归一化为 `<AUDIO>`

## 版本说明

- **R1**: 项目骨架完成，CLI 可运行，占位实现
- **R2**: 实现真实的依赖检查（ffmpeg/ffprobe/silencedetect）
- **R3**: 输入解析与 Repo1 契约适配层
  - 支持多种输入形态（file/workdir/root/manifest）
  - 输出路径规划（in_place/out_root 模式）
  - dry-run 计划输出
  - 最小 seg_report.json 生成
- **R4**: 实现 `silencedetect` 静音分析功能
- **R5**: 实现从静音区间生成语音片段的功能
- **R6**: 实现 MVP 规整增强（merge/split）+ 能量特征 + 可选切片导出
- **R7**: 协议固化与输出验证（validate）+ 批处理汇总（run_summary.json）
  - 新增 `validate` 子命令，支持离线验证输出文件
  - `segment` 命令新增 `--validate-output` 选项
  - 自动生成 `run_summary.json` 批处理汇总报告
  - 新增 `schemas/` 目录，包含协议文档（JSON Schema）
- **R8**: 实现 Energy 策略（基于 RMS 能量的语音/非语音检测）
- **R9**: 实现 VAD 策略（基于 webrtcvad）+ Auto-strategy（自动策略选择）
- **R10**: 可视化/调参友好输出（debug exports）+ summarize 命令 + 片段 notes/flags
  - 片段扩充 flags/source/quality 字段，便于前端高亮
  - 导出 timeline.json、segments.csv、mask.json 等可视化友好文件
  - 新增 `summarize` 子命令，快速浏览 segments.jsonl 摘要
  - 在 seg_report.json 和 run_summary.json 中记录 exports 统计
- **R11**: 配置系统 + 可复现实验快照 + 回归基准（golden）+ 错误分级与退出码规范
  - 支持配置文件（JSON/YAML），避免每次敲一堆 CLI 参数
  - 每次运行写 `run_manifest.json`（参数快照 + 代码版本 + 环境依赖版本），保证可复现
  - 引入 golden 基准测试：给定固定输入与配置，输出 segments.jsonl 必须稳定
  - 错误分级：用户参数错误/依赖缺失/运行时失败要有一致退出码与清晰信息
