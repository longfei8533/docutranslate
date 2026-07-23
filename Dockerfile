# 国内镜像默认值可在构建时通过 --build-arg 覆盖
ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
ARG PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian

# 阶段1: 构建阶段
FROM ${PYTHON_IMAGE} AS builder

ARG PYPI_INDEX_URL

ENV UV_HTTP_TIMEOUT=300 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_DEFAULT_INDEX=${PYPI_INDEX_URL} \
    PIP_INDEX_URL=${PYPI_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=300

WORKDIR /app

# 安装 uv
RUN pip install --no-cache-dir uv

# 创建虚拟环境并安装依赖
COPY pyproject.toml uv.lock ./
COPY docutranslate ./docutranslate
RUN uv venv && uv sync --frozen --extra mcp

# 阶段2: 运行阶段
FROM ${PYTHON_IMAGE}

ARG DEBIAN_MIRROR

LABEL authors="xunbu"

ENV PATH="/app/.venv/bin:$PATH" \
    DOCUTRANSLATE_PORT=8010

WORKDIR /app

# 只安装运行时必需的系统依赖
RUN sed -i \
        -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        -e "s|https://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    pandoc \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* /root/.cache

# 从构建阶段复制虚拟环境
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/docutranslate /app/docutranslate

# 创建挂载点
RUN mkdir -p /app/output

EXPOSE 8010

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${DOCUTRANSLATE_PORT}/service/meta || exit 1

# 启动命令
ENTRYPOINT ["docutranslate", "-i", "--with-mcp"]

# docker build -t xunbu/docutranslate:latest .
# docker push xunbu/docutranslate:latest
# docker run -d -p 8010:8010 xunbu/docutranslate:latest
# Web UI: http://127.0.0.1:8010
# MCP SSE: http://127.0.0.1:8010/mcp/sse
