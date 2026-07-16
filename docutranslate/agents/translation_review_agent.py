# SPDX-FileCopyrightText: 2025 QinHan
# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import re
from logging import Logger
from typing import Any

import httpx

from docutranslate.agents.agent import Agent, AgentConfig, AgentResultError, MAX_REQUESTS_PER_ERROR
from docutranslate.glossary.glossary import Glossary
from docutranslate.utils.json_utils import parse_json_response


REVIEW_CATEGORIES = ("意义错误", "内容增漏", "关键信息错误", "语言或格式错误")
REVIEW_SEVERITIES = ("严重", "一般")


def generate_review_prompt(original_chunk: dict[str, str], translated_chunk: dict[str, str], to_lang: str) -> str:
    return f"""
请对照检查下面同一批次的原文和{to_lang}译文。只报告确实存在的翻译错误；不要评价文风、个人措辞偏好，也不要直接改写文档。

错误分类（category 只能选择一项）：
- 意义错误：错译、语义不一致、否定反转、逻辑关系错误、主体或责任方错误、语气或法律效力变化。
- 内容增漏：漏译、增译、重复翻译。
- 关键信息错误：数字、金额、日期、期限、单位、人名、机构、型号、专有名词、指代或条款引用错误。
- 语言或格式错误：术语不当或前后不一致、未翻译、译文不可理解，以及公式、变量、代码、链接、标签、占位符或文档结构损坏。

严重程度（severity 只能选择一项）：
- 严重：改变核心含义，或者可能影响责任、安全、合规、金额、期限、操作结果或重要结论。
- 一般：确有翻译或格式问题，但不改变核心含义，也不会造成上述重大影响。

<original_chunk>
{json.dumps(original_chunk, ensure_ascii=False)}
</original_chunk>
<translated_chunk>
{json.dumps(translated_chunk, ensure_ascii=False)}
</translated_chunk>

仅返回以下 JSON 对象，不要包含其他内容：
{{"issues":[{{"id":"原文中的ID","category":"意义错误|内容增漏|关键信息错误|语言或格式错误","severity":"严重|一般","description":"简体中文问题说明","suggestion":"简体中文修改建议"}}]}}

规则：
- 没有问题时返回 {{"issues":[]}}。
- 每个 ID 最多返回一项；同一段有多个问题时合并说明。
- 只能使用 original_chunk 中已有的 ID。
- description 和 suggestion 必须使用简体中文。
""".strip()


class TranslationReviewAgent(Agent):
    """Review a translated JSON chunk against its source chunk."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        to_lang: str,
        custom_prompt: str | None = None,
        glossary_dict: dict[str, str] | None = None,
    ):
        super().__init__(config)
        self.to_lang = to_lang
        self.force_json = config.force_json
        self.glossary_dict = glossary_dict
        self.system_prompt = (
            "你是严谨的双语翻译审校员。你的任务是发现译文相对原文的实质性翻译问题，"
            "所有审校意见必须使用简体中文。"
        )
        if custom_prompt:
            self.system_prompt += f"\n翻译时采用了以下附加要求，审校也必须遵守：\n{custom_prompt}"

    def prepare_batch(self, total_chunks: int, shared_rate_limiter: Any) -> None:
        self.rate_limiter = shared_rate_limiter
        self.total_error_counter.max_errors_count = total_chunks // MAX_REQUESTS_PER_ERROR
        self.unresolved_error_count = 0
        self.token_counter.reset()
        self._request_count = total_chunks

    def _pre_send_handler(self, system_prompt: str, prompt: str) -> tuple[str, str]:
        if self.glossary_dict:
            system_prompt += Glossary(glossary_dict=self.glossary_dict).append_system_prompt(prompt)
        return system_prompt, prompt

    @staticmethod
    def _valid_ids_from_prompt(prompt: str) -> set[str]:
        match = re.search(r"<original_chunk>\s*(.*?)\s*</original_chunk>", prompt, re.DOTALL)
        if not match:
            raise AgentResultError("无法从审校 prompt 中读取原文 chunk")
        try:
            original = json.loads(match.group(1))
        except (TypeError, ValueError) as exc:
            raise AgentResultError(f"审校原文 chunk 不是有效 JSON: {exc}") from exc
        if not isinstance(original, dict):
            raise AgentResultError("审校原文 chunk 必须是 JSON 对象")
        return {str(key) for key in original}

    @staticmethod
    def _normalize_category(value: Any) -> str:
        category = str(value or "").strip()
        if category in REVIEW_CATEGORIES:
            return category
        if any(keyword in category for keyword in ("漏", "增", "重复")):
            return "内容增漏"
        if any(keyword in category for keyword in (
            "数字", "金额", "日期", "期限", "单位", "人名", "机构", "型号", "专有名词", "指代", "引用"
        )):
            return "关键信息错误"
        if any(keyword in category for keyword in (
            "术语", "格式", "未翻译", "可读", "语法", "公式", "变量", "代码", "链接", "标签", "占位符", "结构"
        )):
            return "语言或格式错误"
        return "意义错误"

    @staticmethod
    def _normalize_severity(value: Any) -> str:
        severity = str(value or "").strip().lower()
        if severity in {"严重", "critical", "high", "重大"}:
            return "严重"
        return "一般"

    @classmethod
    def _result_handler(cls, result: str, origin_prompt: str, logger: Logger) -> dict[str, str]:
        parsed = parse_json_response(result)
        if isinstance(parsed, list):
            issues = parsed
        elif isinstance(parsed, dict):
            issues = parsed.get("issues", [])
        else:
            raise AgentResultError("审校结果必须是 JSON 对象或数组")
        if not isinstance(issues, list):
            raise AgentResultError("审校结果中的 issues 必须是数组")

        valid_ids = cls._valid_ids_from_prompt(origin_prompt)
        comments: dict[str, list[str]] = {}
        for item in issues:
            if not isinstance(item, dict):
                continue
            segment_id = str(item.get("id", ""))
            if segment_id not in valid_ids:
                logger.warning(f"审校结果包含未知 ID，已忽略: {segment_id!r}")
                continue
            category = cls._normalize_category(item.get("category") or item.get("type"))
            severity = cls._normalize_severity(item.get("severity"))
            description = str(item.get("description") or item.get("comment") or "").strip()
            suggestion = str(item.get("suggestion") or "").strip()
            if not description:
                continue
            text = f"【{category}｜{severity}】{description}"
            if suggestion:
                text += f"\n建议：{suggestion}"
            comments.setdefault(segment_id, []).append(text)

        return {segment_id: "\n\n".join(items) for segment_id, items in comments.items()}

    @staticmethod
    def _error_result_handler(origin_prompt: str, logger: Logger) -> dict[str, str]:
        logger.warning("该 chunk 的 AI 审校失败，将继续生成译文且不插入审校评论。")
        return {}

    def review_chunk(
        self,
        client: httpx.Client,
        original_chunk: dict[str, str],
        translated_chunk: dict[str, str],
    ) -> dict[str, str]:
        prompt = generate_review_prompt(original_chunk, translated_chunk, self.to_lang)
        return self.send(
            client,
            prompt,
            force_json=self.force_json,
            pre_send_handler=self._pre_send_handler,
            result_handler=self._result_handler,
            error_result_handler=self._error_result_handler,
        )

    async def review_chunk_async(
        self,
        client: httpx.AsyncClient,
        original_chunk: dict[str, str],
        translated_chunk: dict[str, str],
    ) -> dict[str, str]:
        prompt = generate_review_prompt(original_chunk, translated_chunk, self.to_lang)
        return await self.send_async(
            client,
            prompt,
            force_json=self.force_json,
            pre_send_handler=self._pre_send_handler,
            result_handler=self._result_handler,
            error_result_handler=self._error_result_handler,
        )
