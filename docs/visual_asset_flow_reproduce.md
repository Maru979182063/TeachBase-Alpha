# 题目配图资产流程复现说明

这份说明用于在另一台 Windows 机器上复现“题目图片识别、裁图、相对路径入库结构、HTML 审核页”流程。

## 1. 准备

先把整个 `教研基建` 项目目录复制到目标机器。

目标机器需要：

- 能访问火山 Ark 接口。
- 有 Python。优先使用 Codex bundled Python；没有的话脚本会尝试系统 `python`。
- 设置环境变量 `ARK_API_KEY`。

PowerShell 示例：

```powershell
cd C:\path\to\教研基建
$env:ARK_API_KEY = "你的 ark key"
```

不要把 key 写进代码或 JSON 文件。

## 2. 跑内置 case_140 样例

这个样例用于验证 option-image 分支：A/B/C/D 每个选项各有一张函数图。

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_question_image_asset_flow.ps1 `
  -SourceJson .\docs\repro_samples\case140\source.json `
  -OutDir .\outputs\visual_transcription_v0.1\boss_repro_case140 `
  -OpenReport
```

成功后重点看：

- `asset_bundle\question_asset_review.html`
- `asset_bundle\question_asset_manifest_v0.1.json`
- `asset_bundle\question_assets\...`

预期结果：

- A、B、C、D 四张 option 图都存在。
- 审核页按 `A. + 图 / B. + 图 / C. + 图 / D. + 图` 展示。
- 不应混入红色解析文字。
- 不应额外重复展示一组 public stem 图。

## 3. 跑自己的题目图片

准备一个 source JSON，结构如下：

```json
{
  "schema_version": "question_image_asset_source.v1",
  "questions": [
    {
      "question_id": "your_case_id",
      "local_number": "1",
      "question_type": "choice",
      "question_image": "relative/or/absolute/path/to/question.png",
      "stem_text": "题干文本，可含 A. B. C. D.",
      "answer_text": "",
      "analysis_text": "",
      "stem_requires_image": true,
      "analysis_requires_image": false
    }
  ]
}
```

然后运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_question_image_asset_flow.ps1 `
  -SourceJson .\your_source.json `
  -OutDir .\outputs\visual_transcription_v0.1\your_run_name `
  -OpenReport
```

## 4. 输出怎么理解

正式看这两个文件：

- `question_asset_review.html`：给人看的审核页，包含题目文字、渲染后的图片插入结果、原始证据图。
- `question_asset_manifest_v0.1.json`：给数据库或后续链路看的结构化结果。

图片路径在 manifest 中使用相对 `storage_key`，例如：

```json
"storage_key": "question_assets/case_140/options/A/001.png"
```

部署时可以把 `asset_bundle` 整包上传或迁移，数据库只保存相对路径/存储 key。

## 5. 当前流程节点

```text
source.json
→ prepare_option_visual_source.py
  → option-image 检测
  → public figure 检测
  → 豆包 1000 坐标归一化
  → option 图优先，抑制重复 public 图
→ assetize_question_images.py
  → 裁图落盘
  → 生成 asset manifest
  → 生成可审核 HTML
```

## 6. 常见失败

- 没有设置 `ARK_API_KEY`：脚本会直接报错，不会走伪结果。
- 图片路径不存在：会生成缺失资产或失败资产。
- 选项图裁得脏：看 manifest 里的 `review_flags`，常见是 `bbox_audit_suspect`。
- 如果 A/B/C/D 缺图，优先检查 option-image 分支坐标和物化状态，不要先怀疑 HTML。
