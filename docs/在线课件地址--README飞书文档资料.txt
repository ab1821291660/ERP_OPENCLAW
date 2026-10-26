


https://ocnu47uh43x2.feishu.cn/docx/Mp4Gdgexzo0d6cx8b3acaWKCnwg  从Agent到手撕OpenClaw的企业实战总结
https://my.feishu.cn/docx/WQVndx4S0odEFUxNXGKcmZSYn0c  基于Harness Engineering架构的企业实战项目
####
####
从Agent到手撕OpenClaw的企业实战
链接：https://my.feishu.cn/docx/X61gdFjdzou0tgx1NvlcHlYyn4d?from=from_copylink
密码：154&56n8




# 上下文与配置的传递
# - 自动传递：主Agent调用时的config（包含configurable、context、context_schema、metadata等）会自动传递给子Agent。这意味着子Agent及其工具可以访问主Agent会话的上下文信息（如用户ID）。
# @tool
# def personalized_search(query: str, config) -> str:
#     """根据当前用户上下文进行搜索。"""
#     user_id = config.get("context", {}).get("user_id", "anonymous")##===================================##===================================
#     return f"为用户{user_id}搜索: {query}。结果是..."
# - Agent身份标识：在流式输出或日志中，可以通过消息元数据中的lc_agent_name区分输出来自哪个Agent。



