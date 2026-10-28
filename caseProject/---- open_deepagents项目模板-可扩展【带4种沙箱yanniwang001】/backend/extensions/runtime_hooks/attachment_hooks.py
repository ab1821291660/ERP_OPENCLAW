from __future__ import annotations

from deepagents_integration.run_hooks import RunInputHookContext, UploadHookContext ##===================================

# 运行时钩子通过扩展入口配置。如果 hook specs 留空，上传文件仍会落盘并绑定到消息， 但不会注入附件 prompt，也不会做上传元数据增强。默认起点是：
# DEEPAGENTS_RUN_INPUT_HOOK_SPECS=extensions.runtime_hooks:RUN_INPUT_HOOKS
# DEEPAGENTS_UPLOAD_HOOK_SPECS=extensions.runtime_hooks:UPLOAD_HOOKS
# 然后编辑 backend/extensions/runtime_hooks 下的模板。
# ----Run input hook 会拿到当前消息和已解析的附件元数据，可以替换传给 DeepAgents 的 content；
# ----upload hook 会在文件落盘后运行，可以把自定义元数据写入 UploadRecord.extra。
def inject_attachment_brief(context: RunInputHookContext) -> str | None:
    """Default run-input hook for attachment prompt shaping."""

    if context.role != "user" \
            or not context.attachments:##===================================
        return None

    if context.is_current_run:##===================================
        lines = [context.content, "", "Current user attachments:"]
        guidance = (
            "These files are already uploaded and available to the runtime. "
            "If sandbox_path is provided, use it directly with filesystem tools. "
            "Do not rediscover the file by searching the workspace first."
        )
    else:
        lines = [context.content, "", "Historical attachments for this earlier user message:"]
        guidance = (
            "These files were attached to an earlier user message. "
            "Reuse them only when the current request explicitly refers back to them."
        )

    for attachment in context.attachments:##===================================
        name = attachment.get("name") or attachment.get("id") or "attachment"
        details = [str(name)]

        sandbox_path = str(attachment.get("sandbox_path") or "").strip()
        upload_path = str(attachment.get("upload_path") or "").strip()
        storage_key = str(attachment.get("storage_key") or "").strip()
        content_type = str(attachment.get("content_type") or "").strip()
        size_bytes = int(attachment.get("size_bytes") or attachment.get("size") or 0)

        if sandbox_path:
            details.append(f"sandbox_path={sandbox_path}")
        if upload_path:
            details.append(f"upload_path={upload_path}")
        if storage_key:
            details.append(f"storage_key={storage_key}")
        if content_type:
            details.append(f"type={content_type}")
        if size_bytes > 0:
            details.append(f"size={size_bytes} bytes")

        lines.append(f"- {' | '.join(details)}")

    lines.extend(
        [
            guidance,
            "When the user asks about an uploaded file, open the provided path directly and answer from its contents.",
        ]
    )
    return "\n".join(lines)



def tag_uploaded_file(context: UploadHookContext) -> dict[str, object]:
    """Example upload hook for adding searchable metadata to UploadRecord.extra."""
    return {
        "runtime_hook": "extensions.runtime_hooks.tag_uploaded_file",
        "original_filename": context.filename,
        "upload_path": context.upload_path,
    }



RUN_INPUT_HOOKS = [inject_attachment_brief]##===================================
UPLOAD_HOOKS = [tag_uploaded_file]##===================================
