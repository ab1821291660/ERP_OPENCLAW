import asyncio
from typing import AsyncIterator

from agent.multi_agent.main_agent import agent


def extract_content_from_token(token) -> str:
    """
    从 token 中提取文本内容。
    处理 token.content 可能是字符串、列表或其他类型的情况。
    """
    if not hasattr(token, 'content'):
        return ""

    content = token.content

    # 如果 content 是字符串，直接返回
    if isinstance(content, str):
        return content

    # 如果 content 是列表，尝试提取其中的文本
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                # 尝试从字典中提取文本
                if 'text' in item:
                    text_parts.append(item['text'])
                elif 'content' in item:
                    text_parts.append(str(item['content']))
                else:
                    # 将整个字典转换为字符串
                    text_parts.append(str(item))
            else:
                # 其他类型转换为字符串
                text_parts.append(str(item))
        return ''.join(text_parts)

    # 其他类型转换为字符串
    return str(content) if content is not None else ""


async def stream_agent_response(user_input: str) -> AsyncIterator[str]:
    """流式处理代理的响应，并实时打印各种事件。"""
    current_source_agent = "主代理"
    current_subagent_id = None
    collected_response = ""

    # 新增：记录上一条消息的标识
    last_message_source = None
    last_message_type = None
    is_inside_message = False

    print(f"\n{'=' * 50}")
    print(f"用户输入: {user_input}")
    print(f"{'=' * 50}")

    try:
        config = {"configurable": {"thread_id": 'sss', "username": "laoxiao", "age": 23}}  ##===================================##===================================
        # 关键：启用 subgraphs=True 和 version="v2" 以获取子代理的流
        async for chunk in agent.astream( # 采用流式处理的方式来执行Agent
                input={"messages": [{"role": "user", "content": user_input}]},
                config=config,
                stream_mode="messages",  # 使用 messages 模式以获取token和工具调用 ##===================================##===================================
                subgraphs=True,
                version="v2",
        ):
            # 根据文档，v2格式的chunk是一个包含type, ns, data的字典
            if chunk.get("type") != "messages":
                continue

            token, metadata = chunk["data"]
            namespace = chunk.get("ns", ())

            # 判断事件来源
            is_subagent_event = any(segment.startswith("tools:") for segment in namespace)

            # 确定当前消息的源
            current_source = None
            if is_subagent_event:
                subagent_namespace_segment = next((s for s in namespace if s.startswith("tools:")), None)
                if subagent_namespace_segment:
                    current_source = subagent_namespace_segment.replace("tools:", "子代理-")
                    current_subagent_id = current_source
                    current_source_agent = "子代理"
                else:
                    current_source = "未知代理"
            else:
                current_source = "主代理"
                current_subagent_id = None
                current_source_agent = "主代理"

            # 确定当前消息类型
            current_message_type = getattr(token, 'type', 'unknown')
            # print(f"[事件] {current_source} - {current_message_type}")
            # 检查是否开始了一条新消息
            is_new_message = False
            if (current_source != last_message_source or
                    current_message_type != last_message_type or
                    (not is_inside_message and (hasattr(token, 'type') and token.type in ['AIMessageChunk', 'tool', 'human']))):
                is_new_message = True
                is_inside_message = True

            # 如果开始新消息，先打印上一条消息的结束标记
            if is_new_message and last_message_source is not None:
                print(f"\n{current_message_type}={'=' * 50}")

            # 更新记录
            last_message_source = current_source
            last_message_type = current_message_type

            if is_subagent_event:
                # 来自子代理的事件
                if current_source != current_subagent_id:
                    if current_subagent_id:
                        print()  # 结束上一个子代理的输出行
                    print(f"\n[{current_source}] ", end="", flush=True)
                    current_subagent_id = current_source
            else:
                # 来自主代理的事件
                if current_source_agent != "主代理":
                    print()  # 结束上一个代理的输出行
                    print(f"\n[主代理] ", end="", flush=True)
                    current_source_agent = "主代理"
                    current_subagent_id = None

            # 处理工具调用
            if hasattr(token, 'tool_call_chunks') and token.tool_call_chunks:
                for tool_chunk in token.tool_call_chunks:
                    if tool_chunk.get('name'):
                        # 开始一个工具调用，打印工具名
                        source_prefix = f"[{current_subagent_id}] " if current_subagent_id else "[主代理] "
                        print(f"\n{source_prefix}正在调用工具: {tool_chunk['name']}", end="", flush=True)
                    # 工具参数可能会分块流式到达
                    if tool_chunk.get('args'):
                        args_str = tool_chunk['args']
                        if args_str and args_str.strip() not in ['{', '}', ':']:
                            print(f" 参数: {args_str}", end="", flush=True)

            # 在工具调用结束后，如果这是最后一个工具调用块，我们可以结束这条消息
            if hasattr(token, 'tool_call_chunks') and token.tool_call_chunks:
                # 标记工具调用结束
                pass

            # 处理工具执行结果
            if hasattr(token, 'type') and token.type == "tool":
                tool_name = getattr(token, 'name', '未知工具')
                result_content = getattr(token, 'content', '')
                result_str = str(result_content)[:150] if result_content else "无结果"
                source_prefix = f"[{current_subagent_id}] " if current_subagent_id else "[主代理] "
                print(f"\n{source_prefix}工具 '{tool_name}' 执行完成，结果: {result_str}...")

                # 工具执行完成后，结束这条消息
                print(f"\n{current_message_type}={'=' * 50}")
                is_inside_message = False
                last_message_source = None
                last_message_type = None

            # 处理常规的AI文本内容（模型生成的部分）
            # 使用新的函数提取内容
            content_text = extract_content_from_token(token)

            # 检查是否有内容，并且不是工具调用块
            has_tool_calls = hasattr(token, 'tool_call_chunks') and token.tool_call_chunks
            if content_text and not has_tool_calls:
                # 如果是AI消息，在开始处添加类型标记
                if hasattr(token, 'type') and token.type == "ai":
                    if not is_inside_message or (
                            current_source != last_message_source and last_message_source is not None):
                        print(f"\n[{current_source}] AIMessage: ", end="", flush=True)
                # 打印模型生成的内容
                print(content_text, end="", flush=True)
                collected_response += content_text

            # 检查是否结束了一条完整的消息
            # 在流式处理中，这很难准确判断，所以我们依赖于下一次循环开始时的检查

        # 流结束后，如果还有未结束的消息，添加分隔线
        if is_inside_message:
            print(f"\n{current_message_type}={'=' * 50}")

        # 最后添加一条分隔线表示整个响应结束
        print()

    except Exception as e:
        print(f"\n[错误] 流式处理时发生异常: {e}")
        import traceback
        traceback.print_exc()

    return collected_response


async def main():
    """主交互循环。"""
    print("Deep Agent 流式交互测试")
    print("说明: 输入您的问题，代理将流式地回复。输入 '退出' 或 'quit' 结束程序。")
    print("-" * 50)

    while True:
        try:
            # 获取用户输入
            user_input = input("\n请输入您的问题: ").strip()

            if not user_input:
                print("输入不能为空，请重新输入。")
                continue

            if user_input.lower() in ['退出', 'quit', 'exit']:
                print("感谢使用，再见！")
                break

            # 流式处理并获取响应
            final_response = await stream_agent_response(user_input)

            # 可以选择是否打印最终聚合的响应
            # if final_response:
            #     print(f"[完整响应]: {final_response}")
            # print()  # 空行分隔

        except KeyboardInterrupt:
            print("\n\n检测到中断，程序退出。")
            break
        except Exception as e:
            print(f"\n[错误] 交互过程中发生异常: {e}")


# 运行主程序
if __name__ == "__main__":
    asyncio.run(main())