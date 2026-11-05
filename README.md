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

## 补充交付：CosyVoice 3 迁移与 7249b5a 纠偏

本节是对上文的追加说明。上文的“7 个文件”“未调用真实 ASR/TTS”“不变更依赖”等结论继续描述原热词交付包；本节及 [cosyvoice3-7249b5a/](cosyvoice3-7249b5a/) 描述另一批本地 TTS 迁移与纠偏改动。两批材料的来源和验证范围不同。本仓库仍是供已有完整项目审阅、合并的变更包集合，不能直接启动应用。

### 两条提交历史之间的关系

原应用的本地提交顺序为：

~~~text
既有四节点架构、语音取消与部署基础
  → 02fb57e  扩展航空术语配置及配置测试
  → 86b2308  保存 CosyVoice 替换前分析、计划和回滚资料
  → fa69255  首轮将 Edge TTS 替换为本地 CosyVoice 3
  → 7249b5a  修复首轮替换的调度、取消、依赖与验收记录偏差
~~~

本仓库原有历史为：

~~~text
3bcc018  独立导出热词与 Qwen prompt 透传修复包
  → d178d79  固定 LF 换行并校准变更包内容校验值
  → 本次追加的 CosyVoice 说明与独立交付目录
~~~

这两条历史没有共同祖先。本仓库不是原应用的完整镜像；下表的原应用提交 ID 是来源标识，不代表它们已经作为 Git 提交存在于本仓库。此次没有把原应用 main 分支合并、推送或覆盖到本仓库。

| 原应用提交 | 直接父提交 | 实际范围与作用 |
| --- | --- | --- |
| 02fb57e | abfd48e | 修改 3 个语音配置及 test_voice_settings.py，共 4 个路径。包含热词扩充，也含后来由原热词包纠正的 Whisper 误切和推断式替换；不能把它当成上文独立包的最终正确内容。 |
| 86b2308 | 02fb57e | 66 个路径：64 个新增、2 个修改。主要是分析、实施计划、上游代码参考、回滚备份、.gitignore 和状态日志；没有实现 CosyVoice 生产调用。 |
| fa69255 | 86b2308 | 42 个路径：新增本地服务、Provider、配置和测试，注册 cosyvoice、调整启动/部署检查，移除 Edge 生产实现及其测试，并切换默认配置。这才是首次实际替换。 |
| 7249b5a | fa69255 | 在已经替换的实现上纠偏。应以 fa69255..7249b5a 判断它自身的改动；86b2308..7249b5a 同时包含首次替换与后续修复，不能混称为单次修复。 |

86b2308 之前的四节点架构合并、回答/RAG/记忆机制及既有语音取消能力属于前置工程基础，不是 7249b5a 新增的功能。02fb57e 只提交了配置和配置测试；原应用这些提交中没有纳入 src/voice/qwen_asr.py。原工作区另有未跟踪 Qwen 模块和测试，因此历史通过数据不能解释为“任意干净检出该提交即可独立复现全部测试”。已有完整项目合并时应保留上文包中已经修正的 Qwen prompt 透传、38 个热词和规范化规则。

### 7249b5a 的范围、目的与关键差异

按关闭重命名识别、逐路径统计，7249b5a 涉及 **152 个路径：18 个修改、133 个新增、1 个删除**。Git 默认显示 151 个变更，是因为把原服务 requirements 文件与证据备份识别为一次移动。实际生产路径 services/cosyvoice/requirements.txt 已删除；证据目录中的同名备份不承担安装职责。

其中 **20 个路径位于应用代码、依赖、测试或现行说明中，其余 132 个是 R03 计划、备份、报告和测试音频等归档**。大量新增行主要来自备份和报告，不代表重写了同等规模的业务逻辑。完整逐路径清单及导出/排除原因见 [history.json](cosyvoice3-7249b5a/history.json)。

| 涉及文件 | fa69255 时的行为 | 7249b5a 的修正及影响 |
| --- | --- | --- |
| services/cosyvoice/server.py | async 端点直接执行同步模型推理和 FFmpeg，阻塞事件循环 | 合成端点改为普通 def，复用 FastAPI 原生线程池；health 可在合成中响应，并发合成按现有单锁返回 503。锁在推理和编码真正结束后释放。 |
| src/voice/cosyvoice_tts.py | 创建 HTTP 请求任务与取消等待任务，finally 只 cancel、不等待内部清理 | 删除两项子任务和 asyncio.wait，在 PlaybackHandle 所管理的任务内直接 await HTTP；保留 20 秒整段超时、I/O 超时和原错误映射，取消能等待客户端资源清理。 |
| pyproject.toml、uv.lock | CosyVoice/GPU 运行包主要靠手工安装，标准同步可能卸载它们 | 根锁统一实际运行依赖；torch/torchaudio 使用显式 CUDA 12.6 索引，验证组合为 2.11.0+cu126；pyarrow 固定 18.1.0 兼容 NumPy 1.26，openai-whisper 使用包级 setuptools<81 构建依赖。 |
| services/cosyvoice/setup.ps1 | Config/revision 未实际用于模型准备，且不检查外部命令退出码 | 只使用已有 .venv；读取配置路径，执行根锁同步，固定上游提交，下载时传入模型 revision；每个外部命令失败后立即退出，且恢复调用者目录。 |
| services/cosyvoice/requirements.txt | 第二套服务依赖清单 | 从生产路径删除，由根 pyproject/uv.lock 取代。 |
| tests/unit/voice/test_cosyvoice_server.py | 没有服务事件循环/锁边界测试 | 新增 health/busy、并发 503、取消后锁保持与异常释放测试，使用假模型，不加载 GPU。 |
| tests/unit/voice/test_cosyvoice_tts.py | 未验证取消返回时 HTTP handler 已清理 | 增加活动请求取消、无后续句段和无残留任务断言。 |
| tests/integration/voice_loop/test_tts_failure_degradation.py | 覆写编码函数制造失败，可能绕过真实 Provider | 用真实 Provider 与 MockTransport 注入 503/连接失败，断言实际 HTTP 请求一次、文字保留、无音频、回答管线不重跑；同时修正原夹具支持解释不足的问题。 |
| tests/unit/voice/test_run_voice.py、tests/helpers/ac02_offline.py | 缺服务就绪检查覆盖不足，未登记新服务测试 | 补充就绪、不可达、非 CosyVoice 不请求测试，并登记新增服务测试；没有放宽隔离守卫。 |
| README、HANDOFF、接口文档、NOTICE、4 个总控文档与 STATUS | 部分仍使用 Edge/10 秒描述或过强的历史通过结论 | 补安装顺序、更正本地服务/20 秒/完整 MP3 口径，披露运行时兼容适配，并记录未通过与待验收项。原应用文档差异不直接套用到本仓库旧 README；本仓库通过本节追加说明。 |

本次纠偏没有新增取消 API、任务队列、自动重试或引擎回退；保留 /health、/inference_zero_shot、TTSProvider、PlaybackHandle、tts.frame 与完整 MP3 传输。客户端取消只结束等待，不能强制中止已经开始的模型运算；模型工作期间的预期 503 是单模型设计的一部分。该服务依赖本地 GPU、FFmpeg、固定上游源码及权重，不能把当前 Windows/Python 3.11 的验证推广成所有平台均已可用。

### 本次材料及合并顺序

| 路径 | 用途 |
| --- | --- |
| [stage-1-fa69255.patch](cosyvoice3-7249b5a/stage-1-fa69255.patch) | 原应用 86b2308→fa69255 的生产代码、配置、依赖及测试差异，用于明确纠偏的前置迁移；不包含原应用历史备份或 README。 |
| [stage-2-7249b5a.patch](cosyvoice3-7249b5a/stage-2-7249b5a.patch) | fa69255→7249b5a 的 12 个运行实现/依赖/测试/NOTICE 路径净差异，含 requirements 删除。 |
| [snapshots/](cosyvoice3-7249b5a/snapshots/) | 第二阶段涉及的 11 个仍存在文件的原提交结果快照；不是整套应用。 |
| [manifest.json](cosyvoice3-7249b5a/manifest.json) | 两阶段精确基线、路径、增改删状态、Git blob 与原始字节 SHA-256。 |
| [evidence/verification.json](cosyvoice3-7249b5a/evidence/verification.json) | 从历史报告重新统计的唯一用例数与证据范围；本次打包未重新运行 GPU/完整应用测试。 |
| [evidence/](cosyvoice3-7249b5a/evidence/) | 有效测速与全量解码记录、语料、取消、WS、缺服务及显存摘要。 |
| [repository-baseline.json](cosyvoice3-7249b5a/repository-baseline.json) | 本仓库原有全部文件的 Git blob 与 SHA-256，以及追加前 README 的字节数与校验值。 |
| [SHA256SUMS](cosyvoice3-7249b5a/SHA256SUMS) | 新目录内材料的原始字节校验值；根 SHA256SUMS 同步更新 README 校验值并追加新目录条目。 |

这些补丁用于已有完整应用，不能在本变更包仓库根直接应用。目标应用恰为 fa69255 且未应用纠偏时，仅检查并应用第二阶段；若恰为 86b2308，先检查并应用第一阶段，再应用第二阶段。示例在目标应用根目录执行：

~~~powershell
git apply --check 'D:/path/to/ChangeChallenge/cosyvoice3-7249b5a/stage-1-fa69255.patch'
git apply 'D:/path/to/ChangeChallenge/cosyvoice3-7249b5a/stage-1-fa69255.patch'
git apply --check 'D:/path/to/ChangeChallenge/cosyvoice3-7249b5a/stage-2-7249b5a.patch'
git apply 'D:/path/to/ChangeChallenge/cosyvoice3-7249b5a/stage-2-7249b5a.patch'
~~~

如果目标应用已有原热词包或其他更新，基线检查可能失败，应逐文件合并，不强制覆盖。重点保留：

- src/voice/qwen_asr.py 的 prompt=self.context 和既有热词/规范化修正；7249b5a 没有重新实现 ASR。
- configs/voice.yaml 中已有 Qwen 模型、上下文及热词；切换 CosyVoice 需要合并 tts_provider 和 tts_config，不能把旧 Whisper 配置带回。
- tests/helpers/ac02_offline.py 中已有治理与测试登记；应合并新增测试行，不用整个快照覆盖更新后的入口。
- 完整项目中已有的其他语音、测试与配置文件；本包没有导出原工作区全部未跟踪依赖，不能承诺仅应用两个补丁后干净检出即可启动。

本次只导出与迁移/纠偏直接有关的差异、选定快照和证据。没有导出原应用 Git 历史、模型权重、知识库全文、数据库、密钥、测试音频或整套历史回滚副本；旧的热词补丁、快照、manifest 和 evidence 全部保留。

### 验证结果与审查结论

下列为原应用工作区的历史结果及本次对原始记录的重新核算，不能与上文热词包 339 项测试直接相减来推断新增测试数量，也不代表本仓库能够独立运行这些测试。

| 检查 | 记录与判断 |
| --- | --- |
| 固定离线回归 | guard 29/29、voice_answer_stream 353/353、all 1348/1348 唯一 nodeid；全量报告含 4044 条 setup/call/teardown 阶段记录。 |
| 依赖一致性 | 原工作区 uv pip check 通过、uv lock --check 通过、标准同步后二次 dry-run 无变化；CUDA 可用，临时 Edge 依赖已移除。 |
| 24 条完整语料 | 31 个分段合成/解码成功，TTS-022 的 5 段均送入模型；尚无逐条人工听判，不能据此宣称型号、数字和内容全部正确。 |
| 有效热态 8×3 | 两次不计分预热后 24/24 成功；整条 RTF 最近秩 P95=1.081，未达到 <1.0；首段完整 MP3 就绪 P95=4.703 秒，未达到绝对 3.5 秒门槛。 |
| 首段时间含义 | 测量起点是首段 HTTP 合成请求，终点是完整 MP3 响应；不包含 ASR/LLM 时间，也没有直接测量浏览器何时真正发声。P95 是这 24 次样本的统计量，不是对未来请求的保证。 |
| Edge 同分段对照 | 24 次均 HTTP 403，成功样本为 0；相对 +1.5 秒规则不可判定，不能借旧的不同分段数据判通过。 |
| 取消与恢复 | 真实 HTTP 合成中取消后仍 busy，故意并发请求 503；模型自然结束后新请求 200。WS 十轮中 5 次首段交付后取消均被接受，另 5 轮完整下发；这不等于浏览器真实停播验收。 |
| 显存 | 纯 TTS 3257 次采样最大 5344 MiB；ASR/TTS 共驻的另一次两轮采样 596 次、最大 6959 MiB，平均间隔约109 ms，无 OOM。该数值是采样最大值，不是算子绝对峰值或十轮全程峰值。 |
| 缺服务回退 | 默认配置、真实 ASR、受信 fixture 回答：停止 TTS 后保留文字，发出 VOICE_TTS_ERROR，回答管线调用一次；没有据此验证真实付费 LLM 或正式知识库。 |

还需保留以下限制：

1. setup 对已有模型仅检查 5 个核心文件是否存在，没有绑定 revision 的权重摘要；辅助模型/分词器文件完整性也没有穷尽检查。下载分支没有限定推理文件集合，可能下载额外文件。安装入口修复不等于模型来源和完整性验收全部闭合。
2. manifest 的自检验证了 spoken_segments 自身哈希，没有独立保证 segments 拼接与原文完全一致；TTS-023 增加了末尾句号，TTS-024 末尾变成“？。”。两组新对照使用同一 manifest，但“原文逐字不变”仍不成立。
3. 统计 P95、逐段解码和失败计数的主要口径已修正；失败分母的专门自检、原文独立哈希仍有缺口。测速时保存的脚本哈希与最终格式化快照有一个末尾换行差异，本次已核验该差异，不把它视为新的测速成绩。
4. 浏览器真实播放停止/清队列、旧 playback 与新轮首包的完整隔离、逐条听判及 Unity/PICO 验收尚未完成。性能门槛也没有达到，不以自动测试通过替代。
5. 本次发布是对原有代码差异的整理与分析，没有修复上述残余事项；它们应另按明确范围处理。

结论：7249b5a 的主要价值是让已替换的本地 TTS 在事件循环调度、HTTP 取消清理、依赖锁与故障回退方面更可靠。原工作区有成功运行和离线回归证据，但代码、模型来源、内容质量与交互性能的完整验收仍未闭合。本仓库新增材料用于可审阅地合并这些改动，并完整保留原热词交付信息。
