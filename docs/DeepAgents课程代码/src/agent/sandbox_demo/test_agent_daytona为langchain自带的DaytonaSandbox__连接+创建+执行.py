#
# # 2. 创建并启动沙箱（Daytona）
# # 注意：此操作会向Daytona服务发起请求，创建一个远程隔离环境
# print("步骤1: 创建远程沙箱环境...")
# try:
#     # （假设在.env文件中配置了OPENAI_API_KEY和DAYTONA_API_KEY）
#     # config = DaytonaConfig(
#     #     api_key=DAYTONA_API_KEY,
#     #     api_url=DAYTONA_BASE_URL,  # "https://app.daytona.io/api"
#     #     target="us"
#     # )
#     # sandbox = Daytona().get('9058717f-98ce-442a-991a-69fece04c2e7')  # 使用之前的docker容器作为远程沙箱
#     sandbox = Daytona().create()  # 第一次创建沙箱
#     print(f"沙箱创建成功！沙箱ID: {sandbox.id}")
# except Exception as e:
#     print(f"创建沙箱失败，请检查网络和API密钥: {e}")
#     return
#
# # 3. 将沙箱包装为Deep Agents可用的后端（Backend）
# backend = DaytonaSandbox(sandbox=sandbox)
#
# # 4. 创建Deep Agent，并授予其访问沙箱后端的能力
# # 系统提示词定义了智能体的角色和能力
# print("\n步骤2: 创建具有沙箱访问权限的智能体...")
# agent = create_deep_agent(
#     model=llm,  # 指定模型
#     backend=backend,  # 关键：传入沙箱后端
#     system_prompt="""你是一个专业的Python编码助手，拥有在一个完全隔离的沙箱环境中执行命令和操作文件的能力。
#     你可以使用`execute`工具运行任何shell命令，使用`write_file`创建和编辑文件，使用`read_file`查看文件内容。
#     请用清晰、安全的代码回应用户的请求。""",
# )
#
# # 5. 定义任务：创建一个简单的Python程序并运行
#     user_request = """请完成以下任务：
#     1. 在沙箱的 /home/daytona/ 目录下，创建一个名为 ‘test_sandbox.py’ 的Python文件。
#     2. 文件内容应打印“Hello from the secure sandbox!”以及当前工作目录。
#     3. 运行这个Python脚本，并告诉我输出结果。"""