"""Explicit Doubao transport for controlled extraction experiments only.

Reuse the tested non-streaming chat transport and complete-image validation.
The production factory remains DeepSeek-only, with no fallback.
"""

from dataclasses import dataclass
from typing import ClassVar

from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DeepSeekMultimodalExtractionProvider,
    _DeepSeekChatProvider,
)
from shuxueshuo_server.solver.runtime.config import DEFAULT_DOUBAO_MODEL


@dataclass
class DoubaoComparisonProvider(_DeepSeekChatProvider):
    provider_name: ClassVar[str] = "doubao"
    supports_images: ClassVar[bool] = True
    preserve_original_images: ClassVar[bool] = True
    model: str = DEFAULT_DOUBAO_MODEL
    max_output_tokens: int = 16384

    def prepare_request(self, request):
        # This method validates image bytes and sets transport policy using
        # self.model; it performs no network call or provider selection.
        return DeepSeekMultimodalExtractionProvider.prepare_request(self, request)
