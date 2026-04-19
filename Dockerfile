# 使用轻量级 Python 镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 安装系统依赖（如果需要编译某些包，可以取消注释）
# RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 暴露 Flask 端口
EXPOSE 5000

# 使用 Gunicorn 启动应用
# -w 4: 启动 4 个工作进程
# -b 0.0.0.0:5000: 绑定到所有接口
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
