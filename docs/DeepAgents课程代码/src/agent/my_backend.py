from deepagents.backends.protocol import BackendProtocol, WriteResult, EditResult
from deepagents.backends.utils import FileInfo, GrepMatch
from datetime import datetime
import re

class DictBackend(BackendProtocol):
    """一个将文件存储在内存字典中的简单后端。"""
    def __init__(self):
        self.files = {}  # 路径 -> 内容
        self.metadata = {} # 路径 -> 元数据（大小，修改时间）

    def ls_info(self, path: str) -> list[FileInfo]:
        # 列出以`path`为前缀的“文件”和“目录”
        print('正在调用我自定义的文件后端')
        result = []
        seen_dirs = set()
        for file_path in self.files.keys():
            if file_path.startswith(path):
                # 处理目录项
                remaining = file_path[len(path):]
                if '/' in remaining:
                    dir_name = path + remaining.split('/')[0] + '/'
                    if dir_name not in seen_dirs:
                        seen_dirs.add(dir_name)
                        result.append(FileInfo(path=dir_name, is_dir=True))
                else:
                    # 文件项
                    meta = self.metadata.get(file_path, {})
                    result.append(FileInfo(
                        path=file_path,
                        is_dir=False,
                        size=meta.get('size', 0),
                        modified_at=meta.get('modified_at')
                    ))
        # result.sort(key=lambda x: x.path)
        return result

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        if file_path not in self.files:
            return f"Error: File '{file_path}' not found"
        content = self.files[file_path]
        # 简单模拟分页：按行处理
        lines = content.splitlines(keepends=True)
        start_line = offset
        end_line = start_line + limit if limit > 0 else len(lines)
        selected_lines = lines[start_line:end_line]
        result = ''.join(f"{start_line + i + 1}: {line}" for i, line in enumerate(selected_lines))
        return result if result else "(end of file)"

    def write(self, file_path: str, content: str) -> WriteResult:
        if file_path in self.files:
            return WriteResult(error=f"File '{file_path}' already exists (create-only).")
        self.files[file_path] = content
        self.metadata[file_path] = {
            'size': len(content),
            'modified_at': datetime.now().isoformat()
        }
        # 对于自定义后端，files_update 通常为 None
        return WriteResult(path=file_path, files_update=None)

    # 注意：为简洁起见，省略了 grep_raw, glob_info, edit 的完整实现。
    # 一个完整的实现需要填充这些方法。
    def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None) -> list[GrepMatch] | str:
        # 简化实现：仅在全文件搜索
        try:
            re.compile(pattern)
        except re.error as e:
            return f"Invalid regex pattern: {e}"
        matches = []
        for file_path, content in self.files.items():
            for i, line in enumerate(content.splitlines()):
                if re.search(pattern, line):
                    matches.append(GrepMatch(path=file_path, line=i+1, text=line))
        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        # 简化实现：使用 fnmatch
        import fnmatch
        all_files = [FileInfo(path=p, is_dir=False, size=self.metadata[p]['size'], modified_at=self.metadata[p]['modified_at']) for p in self.files.keys() if p.startswith(path)]
        matched = [fi for fi in all_files if fnmatch.fnmatch(fi.path, path.rstrip('/') + '/' + pattern)]
        return matched

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        if file_path not in self.files:
            return EditResult(error=f"File '{file_path}' not found")
        content = self.files[file_path]
        if replace_all:
            new_content = content.replace(old_string, new_string)
            occurrences = content.count(old_string)
        else:
            if content.count(old_string) != 1:
                return EditResult(error=f"Found {content.count(old_string)} occurrences of '{old_string}'. For safety, edit requires exactly one match unless replace_all=True.")
            new_content = content.replace(old_string, new_string, 1)
            occurrences = 1
        if new_content == content:
            return EditResult(error=f"String '{old_string}' not found.")
        self.files[file_path] = new_content
        self.metadata[file_path]['size'] = len(new_content)
        self.metadata[file_path]['modified_at'] = datetime.now().isoformat()
        return EditResult(path=file_path, files_update=None, occurrences=occurrences)
