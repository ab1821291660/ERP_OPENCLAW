# -*- coding: utf-8 -*-
from datetime import datetime

# 获取当前系统时间
now = datetime.now()

# 格式化为中文格式
chinese_time = now.strftime("%Y年%m月%d日 %H时%M分%S秒")

# 打印当前时间
print("当前系统时间：", chinese_time)