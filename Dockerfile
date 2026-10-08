# 回放模式下的一次日报：**不需要 API key、不联网、结果确定**。
# 镜像因此可以很小：装的是默认依赖（不含浏览器与 PDF 解析两个 optional extra）。
#
# 基础镜像直接取 astral 的 uv 镜像（bookworm-slim 底），省掉"先装 uv"那一层。
# 想在镜像里跑 `--live`（要过 Cloudflare、要下 PDF）就把基础镜像换成带浏览器的
# 那一套，或者 `uv sync --extra browser --extra pdf && playwright install chromium` ——
# 刻意不做成默认：缺浏览器时代码会**明确报错**，不会静默降级成"LME 无数据"。
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    # 构建期的下载缓存有 77 MB，而它在运行时一点用都没有 —— 不写进镜像层。
    UV_NO_CACHE=1

WORKDIR /app

# 先只装依赖。源码一改，这一层就是缓存命中 —— 不必重装一遍 pydantic 与 langgraph。
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# 包源码与**录播数据**。fixtures/ 必须进来：回放模式的数据全部来自它。
COPY mining_brief/ ./mining_brief/
COPY fixtures/ ./fixtures/
RUN uv sync --frozen --no-dev

# 默认就是回放 + 零配置；`--live` 才需要密钥与网络。
ENV PATH="/app/.venv/bin:$PATH" \
    MINING_DATA_MODE=replay \
    MINING_LLM_MODE=replay \
    MINING_OUTPUT_DIR=/out

# 不是常驻服务：跑完即退，`docker compose up` 会自然结束。
# 产物落在 /out，由 compose 挂到宿主的 ./briefs/。
CMD ["mining-brief", "brief", "给我生成一份关于 Pilbara 锂矿的今日简报"]
