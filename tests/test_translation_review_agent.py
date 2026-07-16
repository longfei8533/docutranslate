import json
import logging

from docutranslate.agents.translation_review_agent import (
    TranslationReviewAgent,
    generate_review_prompt,
)


def test_review_result_is_filtered_and_formatted_in_chinese():
    prompt = generate_review_prompt({"0": "source", "1": "other"}, {"0": "target", "1": "other"}, "中文")
    result = json.dumps({
        "issues": [
            {"id": "0", "category": "意义错误", "severity": "严重", "description": "含义相反。", "suggestion": "改为正确含义。"},
            {"id": "99", "category": "内容增漏", "severity": "一般", "description": "未知段落。", "suggestion": "忽略。"},
        ]
    }, ensure_ascii=False)

    comments = TranslationReviewAgent._result_handler(result, prompt, logging.getLogger(__name__))

    assert comments == {"0": "【意义错误｜严重】含义相反。\n建议：改为正确含义。"}


def test_review_result_with_no_issues_returns_empty_mapping():
    prompt = generate_review_prompt({"0": "source"}, {"0": "target"}, "中文")
    comments = TranslationReviewAgent._result_handler(
        '{"issues": []}', prompt, logging.getLogger(__name__)
    )
    assert comments == {}


def test_legacy_or_unexpected_labels_are_normalized_to_compact_taxonomy():
    prompt = generate_review_prompt({"0": "source", "1": "other"}, {"0": "target", "1": "other"}, "中文")
    result = json.dumps({
        "issues": [
            {"id": "0", "category": "数字或单位错误", "severity": "critical", "description": "数字错误。"},
            {"id": "1", "category": "术语不当", "description": "术语错误。"},
        ]
    }, ensure_ascii=False)

    comments = TranslationReviewAgent._result_handler(result, prompt, logging.getLogger(__name__))

    assert comments == {
        "0": "【关键信息错误｜严重】数字错误。",
        "1": "【语言或格式错误｜一般】术语错误。",
    }
