# SPDX-FileCopyrightText: 2025 QinHan
# SPDX-License-Identifier: MPL-2.0
import re
from dataclasses import dataclass

from .agent import Agent, AgentConfig
from ..glossary.glossary import Glossary
from ..quality.terminology import TerminologyReport, check_terminology


def get_original_markdown(prompt: str):
    match = re.search(r'<input>\n(.*)\n</input>', prompt, re.DOTALL)
    if match:
        return match.group(1)
    else:
        raise ValueError("无法从prompt中提取初始文本")


def get_current_translation(prompt: str) -> str:
    match = re.search(r'<current_translation>\n(.*?)\n</current_translation>', prompt, re.DOTALL)
    if not match:
        raise ValueError("无法从修复提示词中提取当前译文")
    return match.group(1)


def generate_prompt(markdown_text: str, to_lang: str):
    return f"""
Treat the text input as markdown text and translate it into {to_lang},output translation ONLY.
- NO explanations. NO notes.
- For special tags or other non-translatable elements (like codes, brand names, specific jargon), keep them in their original form.
- All formulas, regardless of length, must be represented as valid, parsable LaTeX. They must be correctly enclosed by `$`, `\\(\\)`, or `$$`. If a formula is not formatted correctly, you must fix it.
- Remove or correct any obviously abnormal characters, but without altering the original meaning.
- When citing references, strictly preserve the original text; do not translate them. Examples of reference formats are as follows:
  [1] Author A, Author B. "Original Title". Journal, 2023.
  [2] 作者C. 《中文标题》. 期刊, 2022.
- Output the translated markdown text as plain text (not in a markdown code block, with no extraneous text).

The markdown text input:
<input>
 {markdown_text}
</input>
"""


def generate_terminology_repair_prompt(
    source: str,
    current_translation: str,
    required_terms: list[tuple[str, str]],
    to_lang: str,
) -> str:
    requirements = "\n".join(f"- {source_term} => {target_term}" for source_term, target_term in required_terms)
    return f"""
Revise the current markdown translation into {to_lang} so every required glossary mapping is followed.
Preserve meaning, markdown structure, formulas, numbers, and references. Output the revised markdown only.

Required glossary mappings:
{requirements}

Current translation:
<current_translation>
{current_translation}
</current_translation>

<input>
{source}
</input>
"""


@dataclass
class MDTranslateAgentConfig(AgentConfig):
    to_lang: str
    custom_prompt: str | None = None
    glossary_dict: dict[str, str] | None = None


class MDTranslateAgent(Agent):
    def __init__(self, config: MDTranslateAgentConfig):
        super().__init__(config)
        self.to_lang = config.to_lang
        self.system_prompt = f"""
# Role
You are a professional machine translation engine.
"""
        self.custom_prompt = config.custom_prompt
        if config.custom_prompt:
            self.system_prompt += "\n# **Important rules or background** \n" + self.custom_prompt + '\nEND\n'
        self.glossary_dict = config.glossary_dict
        self.terminology_report: TerminologyReport | None = None
        self._pre_repair_stats: dict | None = None

    def _pre_send_handler(self, system_prompt, prompt):
        if self.glossary_dict:
            glossary = Glossary(glossary_dict=self.glossary_dict)
            system_prompt += glossary.append_system_prompt(prompt)
        return system_prompt, prompt

    def send_chunks(self, prompts: list[str]):
        originals = list(prompts)
        translation_prompts = [generate_prompt(prompt, self.to_lang) for prompt in originals]
        translated = super().send_prompts(prompts=translation_prompts, pre_send_handler=self._pre_send_handler,
                                          error_result_handler=lambda prompt, logger: get_original_markdown(prompt))
        return self._check_and_repair(originals, [str(item) for item in translated])

    async def send_chunks_async(self, prompts: list[str]):
        originals = list(prompts)
        translation_prompts = [generate_prompt(prompt, self.to_lang) for prompt in originals]
        translated = await super().send_prompts_async(
            prompts=translation_prompts,
            pre_send_handler=self._pre_send_handler,
            error_result_handler=lambda prompt, logger: get_original_markdown(prompt),
        )
        return await self._check_and_repair_async(originals, [str(item) for item in translated])

    def _required_terms(self, report: TerminologyReport, segment_id: str) -> list[tuple[str, str]]:
        return [
            (finding.source_term, finding.expected_target)
            for finding in report.findings
            if finding.status != "matched" and segment_id in finding.segment_ids
        ]

    def _check_and_repair(self, originals: list[str], translated: list[str]) -> list[str]:
        self._pre_repair_stats = None
        initial = check_terminology(
            [(str(index), source, translated[index]) for index, source in enumerate(originals)],
            self.glossary_dict,
        )
        self.terminology_report = initial
        if not initial.unresolved_segment_ids:
            return translated
        self._pre_repair_stats = super().get_full_stats()
        ids = list(initial.unresolved_segment_ids)
        repairs = super().send_prompts(
            prompts=[
                generate_terminology_repair_prompt(
                    originals[int(segment_id)], translated[int(segment_id)],
                    self._required_terms(initial, segment_id), self.to_lang,
                )
                for segment_id in ids
            ],
            pre_send_handler=self._pre_send_handler,
            error_result_handler=lambda prompt, logger: get_current_translation(prompt),
        )
        repaired = list(translated)
        for segment_id, value in zip(ids, repairs):
            repaired[int(segment_id)] = str(value)
        final = check_terminology(
            [(str(index), source, repaired[index]) for index, source in enumerate(originals)],
            self.glossary_dict,
        )
        self.terminology_report = initial.with_repair_result(final)
        return repaired

    async def _check_and_repair_async(self, originals: list[str], translated: list[str]) -> list[str]:
        self._pre_repair_stats = None
        initial = check_terminology(
            [(str(index), source, translated[index]) for index, source in enumerate(originals)],
            self.glossary_dict,
        )
        self.terminology_report = initial
        if not initial.unresolved_segment_ids:
            return translated
        self._pre_repair_stats = super().get_full_stats()
        ids = list(initial.unresolved_segment_ids)
        repairs = await super().send_prompts_async(
            prompts=[
                generate_terminology_repair_prompt(
                    originals[int(segment_id)], translated[int(segment_id)],
                    self._required_terms(initial, segment_id), self.to_lang,
                )
                for segment_id in ids
            ],
            pre_send_handler=self._pre_send_handler,
            error_result_handler=lambda prompt, logger: get_current_translation(prompt),
        )
        repaired = list(translated)
        for segment_id, value in zip(ids, repairs):
            repaired[int(segment_id)] = str(value)
        final = check_terminology(
            [(str(index), source, repaired[index]) for index, source in enumerate(originals)],
            self.glossary_dict,
        )
        self.terminology_report = initial.with_repair_result(final)
        return repaired

    def get_full_stats(self) -> dict:
        current = super().get_full_stats()
        if not self._pre_repair_stats:
            return current
        combined = dict(current)
        for field in ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens", "total_tokens", "request_count", "unresolved_errors"):
            combined[field] = int(self._pre_repair_stats.get(field, 0) or 0) + int(current.get(field, 0) or 0)
        combined["unresolved_error_rate"] = (
            combined["unresolved_errors"] / combined["request_count"] if combined["request_count"] else 0
        )
        return combined

    def update_glossary_dict(self, update_dict: dict | None):
        if self.glossary_dict is None:
            self.glossary_dict = {}
        if update_dict is not None:
            self.glossary_dict = self.glossary_dict | update_dict
