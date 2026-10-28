---
name: office-parser
description: 解析 Word 等 Office 文档，提取标题层级、段落、列表、表格和修订线索。用户上传 DOCX 并要求总结、审阅或结构化整理时使用。
metadata:
  label: Office 文档解析
  icon: file-word
  category: 文件
---

# Office 文档解析

## 适用范围

- 当前扩展名：`.docx`
- MIME：`application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- 输入对象来自 MinIO；本技能只负责解析，不负责上传、登录、权限或对象存储。

## 输出要求

1. 文件名、文档标题、段落数量、表格数量。
2. 提取标题层级，生成文档大纲。
3. 保留列表、表格表头、关键备注和上下文页码/章节位置。
4. 输出摘要、行动项、待确认问题和可能冲突的条款。
5. 对修订、批注或痕迹保留状态进行提示；无法读取时明确说明。

## 失败与边界

- 加密文档、临时文件或损坏文件必须返回无法解析的原因。
- 旧版 `.doc`、WPS 专有格式和嵌入对象当前不承诺完整解析。
- 不得把模板示例、批注假设或外部常识写成文件中的事实。
