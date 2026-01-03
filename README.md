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
# 开发安装
pip install -e ".[dev]"
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
- 输出版本信息

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

# 指定分段策略和参数
audioclean-seg segment \
    --in audio.wav \
    --out output_dir \
    --strategy silence \
    --min-silence-sec 0.35 \
    --min-seg-sec 1.0 \
    --max-seg-sec 25.0 \
    --pad-sec 0.1 \
    --emit-segments \
    --emit-wav \
    --jobs 4 \
    --overwrite \
    --dry-run

# 使用日志选项
audioclean-seg segment \
    --in audio.wav \
    --out output_dir \
    --log-level DEBUG \
    --log-file segment.log
```

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
- 目前仅支持 `silence` 策略（其他策略会跳过分析）
- 需要系统安装 `ffmpeg` 和 `ffprobe`

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
- 后续版本将实现更复杂的分段策略（`energy`、`vad`）和低能量点切分功能

### 全局选项

- `--log-level`: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL），默认 INFO
- `--log-file`: 日志文件路径（可选）

## 开发

```bash
# 运行测试
pytest -q

# 运行单个测试
pytest tests/test_cli_help.py -v
```

## 版本说明

- **R1**: 项目骨架完成，CLI 可运行，占位实现
- **R2**: 实现真实的依赖检查（ffmpeg/ffprobe/silencedetect）
- **R3**: 输入解析与 Repo1 契约适配层
  - 支持多种输入形态（file/workdir/root/manifest）
  - 输出路径规划（in_place/out_root 模式）
  - dry-run 计划输出
  - 最小 seg_report.json 生成
- 后续版本将实现真实的分段算法
