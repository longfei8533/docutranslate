import logging

from docutranslate.agents.agent import Agent, AgentConfig
from docutranslate.agents.segments_agent import SegmentsTranslateAgent, SegmentsTranslateAgentConfig


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
