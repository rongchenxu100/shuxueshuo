"""FastAPI：微信 JS-SDK 签名接口。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

from shuxueshuo_server.wechat_jssdk import WeChatJsSdkSigner

# 本地开发：加载 server/.env
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing environment variable: {name}")
    return v


app = FastAPI(title="数学说 API", version="0.1.0")

_signer: WeChatJsSdkSigner | None = None


def get_signer() -> WeChatJsSdkSigner:
    global _signer
    if _signer is None:
        _signer = WeChatJsSdkSigner(
            _require_env("WECHAT_MP_APP_ID"),
            _require_env("WECHAT_MP_APP_SECRET"),
            allowed_origin=_require_env("PUBLIC_SITE_ORIGIN"),
        )
    return _signer


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/wechat/jssdk-config")
async def wechat_jssdk_config(
    url: str = Query(..., description="当前页完整 URL，不含 hash"),
) -> dict[str, str | int]:
    """返回前端 wx.config 所需字段。"""
    try:
        signer = get_signer()
        cfg = await signer.build_config(url)
        return cfg
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        logger.warning("wechat jssdk-config failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="微信侧服务暂时不可用，请稍后重试",
        ) from e
