# 航空科普语音热词增强与 Qwen3-ASR 透传修复

本仓库仅交付本轮变更包：可应用补丁、7 个受影响文件的结果快照、知识库术语来源和离线验证证据。按用户指定范围独立提交，不包含完整项目或原项目的 Git 历史。快照用于审阅和手工合并，本仓库本身不能启动完整应用。

## 修复的问题

`QwenASRProvider` 原来读取了 `asr_config.context` 并保存到 `self.context`，但 `_transcribe_sync()` 调用处理器时只传音频和语言。因此仅修改 YAML 热词不会将热词送入模型输入。

本机安装的 Transformers **5.22.1** 中，`Qwen3ASRProcessor.apply_transcription_request(audio, language=None, prompt=None, **kwargs)` 明确使用 `prompt` 接收上下文和热词。此次补齐：

```python
inputs = processor.apply_transcription_request(
    audio_array,
    language=self.language,
    prompt=self.context,
)
```

配置到处理器的路径为：`voice.yaml → VoiceSettings.asr_config → QwenASRProvider.context → apply_transcription_request(prompt=...)`。保留原有 `context` 优先、`initial_prompt` 兼容、缺省上下文的选择顺序。

## 配置与术语变化

- 恢复本轮操作前的 Qwen3-ASR 配置：`qwen3_asr`、`./models/Qwen3-ASR-0.6B-hf`、`cuda:0`、`bfloat16`、`Chinese` 和预热。前轮操作曾误切到 Whisper，本交付已纠正；不通过切换识别模型来迁就旧测试。
- 热词由原来 9 个扩充到 **38 个**，新增 29 个，覆盖 C919、歼-20、运-20、直-20，以及涵道比、翼梢小翼、DSI进气道、主旋翼等。保留原有通用词；33 个知识库候选直接匹配 `canonical_name` 或 `aliases`，与原 9 词去重后得到 38 词。逐词路径见 `evidence/term_sources.json`。
- `voice_terminology.yaml` 保留原有 4 条规则，增加 12 条明确机型读法：如“歼 二十”“歼二十”“歼20”“J20”统一为“歼-20”，运-20、直-20同理。
- 移除前轮尚未验证或会改变含义的规则，例如“全动尾翼→全动垂尾”“T形尾→T型垂尾”“神雕直升机→直-20”“利普发动机→LEAP-1C”；保留“C919客机”的原文。未新增未经核对的科普定义，`simplifications` 保持原有内容。
- TTS 增加 14 条机型/缩写读法；`APU`、`DSI`、`AESA`、`AoA`、`IMA` 使用字母拼读，机型转成中文读法。音色和语速不变。

## 文件与内容

| 项目 | 说明 |
| --- | --- |
| `voice-hotwords.patch` | 本轮最终净改动，含适配器、三个配置文件、配置测试、AC02登记和新增回归 |
| `snapshots/` | 上述 7 个文件的最终内容，便于审阅或手工合并 |
| `manifest.json` | 每个文件修改前/后按 LF 归一化的 SHA-256，注明基线与范围 |
| `evidence/verification.json` | 修复前失败、修复后通过、隔离守卫验证摘要 |
| `evidence/term_sources.json` | 知识库热词与来源文件的对应关系 |
| `evidence/processor_api.json` | 已安装处理器版本、签名与热词参数 |
| `SHA256SUMS` | 本变更包各交付文件的内容校验值 |

## 验证结果

全部 pytest 通过项目既有 AC02 固定入口运行，使用临时配置、Mock 服务及原网络/数据库隔离守卫。仅向语音固定集合登记 `test_voice_hotwords.py` 与已有 `test_qwen_asr.py`，未放宽守卫。

| 运行 | 结果 |
| --- | --- |
| 修复前语音回归 RED | 339 项：330 通过、9 失败；失败分别复现缺少 prompt、Qwen配置误切及错误归一化 |
| 修复后语音回归 GREEN | **339/339 通过，退出码 0** |
| AC02 隔离守卫 | **29/29 通过，退出码 0** |
| `git diff --check` | 涉及已跟踪文件检查通过 |

新增的 10 项回归覆盖四种上下文来源（显式 context、旧 initial_prompt、二者同时存在、默认值）、仓库Qwen配置，以及机型规范化和正确文本不被误改。模拟处理器检查了实际 `_transcribe_sync()` 请求参数，并验证音频和识别结果仍按原方式处理。

```powershell
.venv/Scripts/python.exe -X utf8 -I -B tests/helpers/ac02_offline.py --voice-answer-stream-tests
.venv/Scripts/python.exe -X utf8 -I -B tests/helpers/ac02_offline.py --guard-tests
```

已验证的是配置与处理器请求的接线、文本规则及相关离线兼容性。此次未下载/加载真实模型、调用真实 ASR/TTS、访问业务数据库或执行部署；未进行录音对照实验，因此不声称识别率或时延已经提升。若运行环境的处理器不支持 `prompt`，需先核对安装版本；本次未变更依赖。

## 合并到已有项目

补丁基线是本次会话开始前、已具备 Qwen 适配器和 AC02 入口的工作区；其中部分既有迁移尚未提交，所以不能将其解释为任意干净 Git commit。`02fb57e` 是前轮本地历史记录，其中的误切配置和推断替换已由本交付纠正，请以本包最终补丁为准。

先将本包下载到项目之外，在目标项目根目录检查补丁：

```powershell
git apply --check 'D:/path/to/change-package/voice-hotwords.patch'
git apply 'D:/path/to/change-package/voice-hotwords.patch'
```

检查通过后再应用，并执行上述离线验证。若已应用前轮改动或基线不同，按补丁和快照手工合并；尤其不要直接用整个测试入口快照覆盖已有治理变动。运行完整测试还要求目标项目保留既有 `tests/unit/voice/test_qwen_asr.py`、相应语音模块和依赖。

本包未导出模型权重、知识库全文、数据库、密钥、其他业务模块改动或项目历史；术语来源仅列项目内路径。
