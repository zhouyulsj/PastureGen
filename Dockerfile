FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 依赖层单独缓存：仅当 pyproject.toml 变化时才重装
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir ".[edge]"

# 运行期数据目录（由卷挂载覆盖），整体交给非 root 用户，避免容器逃逸后拿到 root
RUN useradd --create-home --uid 10001 pasture \
    && mkdir -p /app/data \
    && chown -R pasture:pasture /app
USER pasture

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
