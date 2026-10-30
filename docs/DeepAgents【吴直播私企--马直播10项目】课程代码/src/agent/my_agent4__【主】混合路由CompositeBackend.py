

##CompositeBackend (复合/路由后端)
# - 工作原理：作为后端路由器，根据文件路径的前缀，将操作定向到不同的底层后端。
# - 最佳用途：实现混合存储策略。例如，
#           临时工作文件用 StateBackend， # 默认后端，用于临时文件##===================================
#           长期记忆用 StoreBackend，##===================================
#           特定目录映射到本地磁盘。##===================================
# 定义复合后端：默认用StateBackend，但`/memories/`路径下的操作路由到StoreBackend
composite_backend = lambda rt: CompositeBackend(
    default=StateBackend(rt),  # 默认后端，用于临时文件##===================================
    routes={
        "/memories/": StoreBackend(rt),  # 持久化路径##===================================##===================================##===================================##===================================
    }
)
agent = create_deep_agent(
    model="gpt-4o",
    backend=composite_backend,
    store=InMemoryStore()##===================================
)
# 现在，Agent对`/scratch/plan.md`的读写是临时的，而对`/memories/user_pref.json`的读写是持久的。




composite_backend = lambda rt: CompositeBackend(
    default=StateBackend(rt),  # 默认临时存储 # 默认后端，用于临时文件##===================================
    routes={
        "/memories/": FilesystemBackend(root_dir="/data/agent_memories", virtual_mode=True),##===================================##===================================##===================================##===================================
        "/shared_docs/": FilesystemBackend(root_dir="/company/docs", virtual_mode=True),##===================================##===================================##===================================##===================================
    },
)
agent = create_deep_agent(backend=composite_backend)
# 路径解析：
# `/scratch/temp.txt` -> StateBackend
##
# `/memories/2025/note.md` -> 本地文件 `/data/agent_memories/2025/note.md`
# `/shared_docs/api.md` -> 本地文件 `/company/docs/api.md`
# `ls /` 命令会聚合来自所有后端的结果。