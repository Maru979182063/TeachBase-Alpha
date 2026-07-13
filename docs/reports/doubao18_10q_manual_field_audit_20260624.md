# Doubao 1.8V 10题人工字段审查

审查对象：

- `C:\Users\EDY\Documents\教研基建\outputs\visual_transcription_v0.1\teacher_handout_visual_testset10_doubao18_metrics_20260624\visual_transcription_results.json`
- 对照题图：`C:\Users\EDY\Documents\教研基建\tmp\doubao18_audit_images\`

审查口径：

- 逐题核查 `stem_text_md / question_image / answer_text_md / analysis_text_md / analysis_image`
- 题图为真值来源
- 只按“能否直接入库”判断，不按“勉强能看懂”放宽

## 总结

- 可直接入库：7 / 10
- 需要拦截后修复：3 / 10
- `stem_text_md` 可用：9 / 10
- `answer_text_md` 可用：10 / 10
- `analysis_text_md` 可用：7 / 10
- 图片归属字段整体正常，主要问题集中在文本层，不在视觉切块层

## 逐题结论

| record_id | stem_text_md | question_image | answer_text_md | analysis_text_md | analysis_image | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `senior_tq_002` | 通过 | 通过 | 通过 | 通过 | 不需要 | 可入库 |
| `senior_tq_003` | 通过 | 通过 | 通过 | 通过 | 不需要 | 可入库 |
| `senior_tq_010` | 通过 | 通过 | 通过 | 通过 | 不需要 | 可入库 |
| `senior_tq_018` | 通过 | 通过 | 通过 | 通过（有 LaTeX 排版规范化空间） | 不需要 | 可入库 |
| `senior_tq_025` | 通过 | 通过 | 通过 | 不通过：`△ABC周长` 被写成 `△AC周长` | 不需要 | 需修复 |
| `junior_tq_002` | 不通过：落盘后 `\triangle` 损坏 | 通过 | 通过 | 不通过：`\\because / \\therefore / \\triangle / \\begin` 落盘后损坏 | 通过 | 需修复 |
| `junior_tq_004` | 通过 | 通过 | 通过 | 不通过：漏掉题图中的独立 `[分析]` 信息块，只保留了 `[解答]` | 通过 | 需修复 |
| `junior_tq_009` | 通过 | 通过 | 通过 | 通过 | 通过 | 可入库 |
| `junior_tq_021` | 通过 | 通过 | 通过（证明题空答案可接受） | 通过 | 通过 | 可入库 |
| `junior_tq_030` | 通过 | 通过 | 通过 | 通过 | 通过 | 可入库 |

## 关键问题

### 1. 落盘解析污染 LaTeX 控制词

最突出样本：`junior_tq_002`

原始模型回包是正确的，例如：

- `\triangle`
- `\because`
- `\therefore`
- `\begin{cases}`

但最终结果文件中，这些前缀会被 JSON 转义解释成控制字符：

- `\t...` -> tab
- `\b...` -> backspace

因此这是“结果解析问题”，不是“视觉模型看错题图”。

### 2. 解析字段没有覆盖全部教师说明块

最突出样本：`junior_tq_004`

题图中同时存在：

- `[分析]`
- `[解答]`

当前 `analysis_text_md` 只保留了 `[解答]`，漏掉了 `[分析]`。  
这类题如果直接入库，会丢掉教师版的重要提示信息。

### 3. 长解析题存在局部语义滑落

最突出样本：`senior_tq_025`

模型整体推理链条正确，但末句把：

- `△ABC周长的最大值`

写成了：

- `△AC周长的最大值`

这类错误不是整段崩坏，而是局部关键名词掉字，必须字段级拦截。

## 修复优先级

1. 先修“落盘解析污染 LaTeX”  
   这会把本来正确的字段也打坏，优先级最高。

2. 再修提示词，强制 `analysis_text_md` 吞并所有教师说明块  
   至少要覆盖：`分析 / 解答 / 证明 / 思路 / 点评 / 结论`

3. 最后加“局部高风险 span 二次精修”  
   仅对模型自己标出的 `uncertain_spans` 或规则命中的高风险片段补录，不重跑整题。

## 对 runtime 的直接结论

- 视觉切块层：这 10 题里没有看到明显的题目归属错配，当前主问题不在切块
- 文本转录层：已经具备可用能力，但还不具备“无审查直入库”
- 当前更像是：
  - 高中三角题：接近可用
  - 初中几何题：图文归属没问题，但 LaTeX 落盘和说明块覆盖还不稳

## 当场修复与回归

已在 `C:\Users\EDY\Documents\教研基建\tools\teacher_handout_visual_transcribe_doubao.py` 落了两轮修复：

1. 落盘前恢复 LaTeX 控制前缀  
   把被 JSON 解释成控制字符的 `\t / \b / \f` 恢复为字面量反斜杠前缀。

2. 宽松解析时转义字符串内的裸换行  
   解决 `\begin{cases}` 一类多行公式块把 JSON 字符串直接打断的问题。

3. 强化 prompt  
   明确要求 `analysis_text_md` 必须吞并所有教师说明块，不得只留 `解答` 丢掉 `分析`。

回归结果：

- 两题烟雾回归：`junior_tq_002`、`junior_tq_004` 均通过
- 其中：
  - `junior_tq_002` 的 `\triangle / \because / \therefore / \begin` 已恢复正常
  - `junior_tq_004` 的 `【分析】 + 【解答】` 已同时保留到 `analysis_text_md`
- 修复后整批 10 题复跑一次：`9/10 ok`
- 剩余 `1/10` 失败样本仍是 `junior_tq_002`，但已进一步定位并用第二轮 parser 修复后单题复跑通过

因此，当前剩余的主问题已经从“文本层经常结构性损坏”收缩为“少量局部语义错字/漏字仍需字段级拦截”。
