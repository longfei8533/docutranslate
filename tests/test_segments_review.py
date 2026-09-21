import json
import logging

import httpx
import pytest

from docutranslate.agents.agent import Agent, AgentConfig, AgentResultError
from docutranslate.agents.markdown_agent import MDTranslateAgent, MDTranslateAgentConfig
from docutranslate.agents.segments_agent import (
    SegmentsTranslateAgent,
    SegmentsTranslateAgentConfig,
    generate_terminology_repair_prompt,
)
from docutranslate.quality.terminology import check_terminology


class FakeReviewer:
    def __init__(self, events):
        self.events = events

    def prepare_batch(self, total_chunks, shared_rate_limiter):
        self.events.append(("prepare", total_chunks))

    def review_chunk(self, client, original_chunk, translated_chunk):
        segment_id = next(iter(original_chunk))
        self.events.append(("review", segment_id, translated_chunk[segment_id]))
        return {segment_id: f"comment-{segment_id}"}


def make_agent():
    return SegmentsTranslateAgent(SegmentsTranslateAgentConfig(
        base_url="https://example.com/v1",
        api_key="test",
        model_id="test-model",
        to_lang="中文",
        concurrent=2,
        logger=logging.getLogger(__name__),
    ))


def make_glossary_agent():
    return SegmentsTranslateAgent(SegmentsTranslateAgentConfig(
        base_url="https://example.com/v1",
        api_key="test",
        model_id="test-model",
        to_lang="中文",
        concurrent=2,
        logger=logging.getLogger(__name__),
        glossary_dict={"adverse event": "不良事件"},
    ))


def test_each_translation_chunk_is_reviewed_before_its_worker_completes(monkeypatch):
    events = []

    def fake_send_prompts(self, prompts, completion_callback=None, **kwargs):
        results = [{"0": "译文一"}, {"1": "译文二"}]
        for index, result in enumerate(results):
            events.append(("translate", index))
            completion_callback(index, prompts[index], result, object())
            events.append(("complete", index))
        return results

    monkeypatch.setattr(Agent, "send_prompts", fake_send_prompts)
    translated, reviews = make_agent().send_segments_with_review(
        ["原文一", "原文二"], 20, FakeReviewer(events)
    )

    assert translated == ["译文一", "译文二"]
    assert reviews == {0: "comment-0", 1: "comment-1"}
    assert events.index(("review", "0", "译文一")) < events.index(("complete", 0))
    assert events.index(("review", "1", "译文二")) < events.index(("complete", 1))


def test_split_segment_review_comments_are_merged_back_to_original_segment():
    comments = SegmentsTranslateAgent._merge_review_comments(
        {0: {"0": "first"}, 1: {"1": "second"}, 2: {"2": "third"}},
        original_count=2,
        expanded_count=3,
        merged_indices_list=[(0, 2)],
    )
    assert comments == {0: "first\n\nsecond", 1: "third"}


def test_missing_glossary_translation_is_repaired_and_rechecked(monkeypatch):
    calls = []

    def fake_send_prompts(self, prompts, **kwargs):
        calls.append(prompts)
        return [{"0": "出现了一次不良反应。"}] if len(calls) == 1 else [{"0": "出现了一次不良事件。"}]

    monkeypatch.setattr(Agent, "send_prompts", fake_send_prompts)
    agent = make_glossary_agent()
    translated = agent.send_segments(["An adverse event occurred."], 100)

    assert translated == ["出现了一次不良事件。"]
    assert len(calls) == 2
    assert "adverse event => 不良事件" in calls[1][0]
    assert agent.terminology_report is not None
    assert agent.terminology_report.repair_attempted is True
    assert agent.terminology_report.repaired_terms == 1
    assert agent.terminology_report.missing_terms == 0


def test_failed_segment_repair_preserves_first_pass_translation(monkeypatch):
    calls = 0

    def fake_send_prompts(self, prompts, error_result_handler=None, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [{"0": "出现了一次不良反应。"}]
        return [error_result_handler(prompts[0], logging.getLogger(__name__))]

    monkeypatch.setattr(Agent, "send_prompts", fake_send_prompts)
    agent = make_glossary_agent()

    assert agent.send_segments(["An adverse event occurred."], 100) == ["出现了一次不良反应。"]
    assert agent.terminology_report is not None
    assert agent.terminology_report.repair_attempted is True
    assert agent.terminology_report.missing_terms == 1


def test_missing_id_in_repair_response_preserves_first_pass_translation():
    class MissingIdClient:
        def post(self, url, **kwargs):
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                request=request,
                json={
                    "choices": [{
                        "finish_reason": "stop",
                        "message": {"content": '[{"t":"出现了一次不良事件。"}]'},
                    }],
                    "usage": {},
                },
            )

    agent = make_glossary_agent()
    prompt = generate_terminology_repair_prompt(
        "0",
        "An adverse event occurred.",
        "出现了一次不良反应。",
        [("adverse event", "不良事件")],
        "中文",
    )

    repaired = agent.send(
        MissingIdClient(),
        prompt,
        result_handler=agent._result_handler,
        error_result_handler=agent._repair_error_result_handler,
    )

    assert repaired == {"0": "出现了一次不良反应。"}


def test_repair_that_still_omits_required_term_preserves_first_pass_translation(monkeypatch):
    calls = 0

    def fake_send_prompts(self, prompts, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [{"0": "出现了一次不良反应。"}]
        return [{"0": "An adverse event occurred."}]

    monkeypatch.setattr(Agent, "send_prompts", fake_send_prompts)
    agent = make_glossary_agent()

    translated = agent.send_segments(["An adverse event occurred."], 100)

    assert translated == ["出现了一次不良反应。"]
    assert agent.terminology_report is not None
    assert agent.terminology_report.missing_terms == 1


def test_unchanged_english_segment_is_retranslated_for_chinese_target(monkeypatch):
    source = "The committee reviewed the available safety data and issued its recommendation."
    calls = 0

    def fake_send_prompts(self, prompts, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [kwargs["error_result_handler"](prompts[0], logging.getLogger(__name__))]
        return [{"0": "委员会审阅了可用的安全性数据并提出建议。"}]

    monkeypatch.setattr(Agent, "send_prompts", fake_send_prompts)
    agent = make_glossary_agent()

    assert agent.send_segments([source], 100) == ["委员会审阅了可用的安全性数据并提出建议。"]
    assert calls == 2


def test_unchanged_english_segment_fails_closed_after_targeted_retry(monkeypatch):
    source = "The committee reviewed the available safety data and issued its recommendation."

    monkeypatch.setattr(
        Agent,
        "send_prompts",
        lambda self, prompts, **kwargs: [
            kwargs["error_result_handler"](prompts[0], logging.getLogger(__name__))
        ],
    )
    agent = make_glossary_agent()

    with pytest.raises(AgentResultError, match="1 个片段在定向重试后仍与原文相同"):
        agent.send_segments([source], 100)


def test_explicitly_returned_unchanged_segment_can_follow_preservation_requirement(monkeypatch):
    source = "The cited reference title must remain in its original published language."
    calls = 0

    def fake_send_prompts(self, prompts, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [kwargs["error_result_handler"](prompts[0], logging.getLogger(__name__))]
        response = f'[{json.dumps({"id": "0", "t": source})}]'
        return [kwargs["result_handler"](response, prompts[0], logging.getLogger(__name__))]

    monkeypatch.setattr(Agent, "send_prompts", fake_send_prompts)
    agent = make_glossary_agent()

    assert agent.send_segments([source], 100) == [source]
    assert calls == 2


def test_repaired_segment_replaces_review_of_the_stale_translation(monkeypatch):
    events = []
    calls = 0

    class RepairAwareReviewer(FakeReviewer):
        def rereview_pairs(self, pairs):
            self.events.append(("rereview", pairs))
            return {pairs[0][0]: "comment-after-repair"}

    def fake_send_prompts(self, prompts, completion_callback=None, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            result = {"0": "出现了一次不良反应。"}
            completion_callback(0, prompts[0], result, object())
            return [result]
        return [{"0": "出现了一次不良事件。"}]

    monkeypatch.setattr(Agent, "send_prompts", fake_send_prompts)
    translated, reviews = make_glossary_agent().send_segments_with_review(
        ["An adverse event occurred."], 100, RepairAwareReviewer(events)
    )

    assert translated == ["出现了一次不良事件。"]
    assert reviews == {0: "comment-after-repair"}
    assert any(event[0] == "rereview" for event in events)


def test_terminology_check_is_aligned_normalized_and_language_aware():
    report = check_terminology(
        [
            ("0", "The ADVERSE   EVENT was recorded.", "记录了不良事件。"),
            ("1", "A study drug was administered twice: study drug.", "给予了试验药物。"),
            ("2", "Retrials are unrelated.", "复审无关。"),
        ],
        {"adverse event": "不良事件", "study drug": "试验药物", "trial": "临床试验"},
    )

    assert report.applicable_terms == 2
    assert report.matched_terms == 1
    assert report.partial_terms == 1
    assert report.missing_terms == 0
    assert report.coverage_percent == 66.7
    assert report.unresolved_segment_ids == ("1",)


def test_terminology_check_does_not_accept_target_from_an_unrelated_segment():
    report = check_terminology(
        [("0", "adverse event", "不良反应"), ("1", "another sentence", "不良事件")],
        {"adverse event": "不良事件"},
    )

    assert report.missing_terms == 1
    assert report.matched_occurrences == 0
    assert report.findings[0].segment_ids == ("0",)


def test_terminology_check_matches_chinese_term_with_latin_acronym_inside_sentence():
    report = check_terminology(
        [(
            "0",
            "The electronic case report form (eCRF) was reviewed.",
            "已审阅数据库中的电子病例报告表（eCRF）。",
        )],
        {"electronic case report form (eCRF)": "电子病例报告表（eCRF）"},
    )

    assert report.matched_terms == 1
    assert report.matched_occurrences == 1
    assert report.coverage_percent == 100.0


def test_terminology_report_records_a_targeted_repair_result():
    initial = check_terminology([("0", "study drug", "研究药物")], {"study drug": "试验药物"})
    repaired = check_terminology([("0", "study drug", "试验药物")], {"study drug": "试验药物"})

    final = initial.with_repair_result(repaired)
    assert final.repair_attempted is True
    assert final.repaired_terms == 1
    assert final.as_dict()["status"] == "passed"


def test_markdown_translation_repairs_only_the_failed_chunk(monkeypatch):
    calls: list[list[str]] = []

    def fake_send_prompts(self, prompts, **kwargs):
        calls.append(prompts)
        if len(calls) == 1:
            return ["记录了不良反应。", "本段没有术语。"]
        return ["记录了不良事件。"]

    monkeypatch.setattr(Agent, "send_prompts", fake_send_prompts)
    agent = MDTranslateAgent(MDTranslateAgentConfig(
        base_url="https://example.com/v1",
        api_key="test",
        model_id="test-model",
        to_lang="中文",
        logger=logging.getLogger(__name__),
        glossary_dict={"adverse event": "不良事件"},
    ))

    translated = agent.send_chunks(["An adverse event occurred.", "No terminology here."])

    assert translated == ["记录了不良事件。", "本段没有术语。"]
    assert len(calls) == 2
    assert len(calls[1]) == 1
    assert agent.terminology_report is not None
    assert agent.terminology_report.repaired_terms == 1


def test_failed_markdown_repair_preserves_first_pass_translation(monkeypatch):
    calls = 0

    def fake_send_prompts(self, prompts, error_result_handler=None, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ["记录了不良反应。"]
        return [error_result_handler(prompts[0], logging.getLogger(__name__))]

    monkeypatch.setattr(Agent, "send_prompts", fake_send_prompts)
    agent = MDTranslateAgent(MDTranslateAgentConfig(
        base_url="https://example.com/v1",
        api_key="test",
        model_id="test-model",
        to_lang="中文",
        logger=logging.getLogger(__name__),
        glossary_dict={"adverse event": "不良事件"},
    ))

    assert agent.send_chunks(["An adverse event occurred."]) == ["记录了不良反应。"]
    assert agent.terminology_report is not None
    assert agent.terminology_report.missing_terms == 1
