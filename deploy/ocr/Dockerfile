FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/build/server
COPY server/pyproject.toml server/README.md ./
COPY server/shuxueshuo_server ./shuxueshuo_server

# 阿里云 PyPI；Paddle 仍走官方 CPU 源
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
      --trusted-host mirrors.aliyun.com \
      "setuptools==83.0.0" \
 && pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
      --trusted-host mirrors.aliyun.com \
      . \
 && pip install --no-cache-dir \
      -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
      --trusted-host www.paddlepaddle.org.cn \
      "paddlepaddle==3.3.0" \
 && pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
      --trusted-host mirrors.aliyun.com \
      "paddleocr[doc-parser]==3.7.0"

WORKDIR /opt/shuxueshuo/server
ENV PYTHONPATH=/opt/shuxueshuo/server \
    PADDLE_PDX_MODEL_SOURCE=bos \
    OMP_NUM_THREADS=1 \
    FLAGS_use_mkldnn=0
