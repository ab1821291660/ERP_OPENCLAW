from datetime import datetime

# 获取当前时间
now = datetime.now()

# 按照 yyyy-mmm-dd 格式打印
formatted_date = now.strftime("%Y-%b-%d")
print(formatted_date)