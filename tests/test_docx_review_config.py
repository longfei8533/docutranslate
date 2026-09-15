import logging

from pydantic import TypeAdapter

from docutranslate.core.schemas import TranslatePayload
from docutranslate.server.core import TranslationService
from docutranslate.translator.ai_translator.docx_translator import DocxTranslatorConfig
from docutranslate.translator.ai_translator.base import AiTranslator
from docutranslate.progress import ProgressTracker


def test_docx_review_option_reaches_translator_config():
    payload = TypeAdapter(TranslatePayload).validate_python({
        "workflow_type": "docx",
        "base_url": "https://example.com/v1",
        "api_key": "test",
        "model_id": "test-model",
        "translation_review_enable": True,
    })
    config = DocxTranslatorConfig(**payload.model_dump(exclude={"workflow_type"}))
    assert config.translation_review_enable is True


def test_docx_review_option_reaches_web_workflow_config():
    payload = TypeAdapter(TranslatePayload).validate_python({
        "workflow_type": "docx",
        "base_url": "https://example.com/v1",
        "api_key": "test",
        "model_id": "test-model",
        "translation_review_enable": True,
    })
    service = TranslationService()
    workflow = service._create_workflow(
        payload=payload,
        task_logger=logging.getLogger("test-docx-review-config"),
        progress_tracker=ProgressTracker(),
        build_glossary_agent_config=lambda: None,
        md2docx_engine="auto",
    )

    assert workflow.config.translator_config.translation_review_enable is True


def test_docx_review_option_defaults_to_disabled():
    payload = TypeAdapter(TranslatePayload).validate_python({
        "workflow_type": "docx",
        "base_url": "https://example.com/v1",
        "api_key": "test",
        "model_id": "test-model",
    })
    assert payload.translation_review_enable is False
    assert payload.translation_review_language == "target"


def test_review_usage_is_included_in_total_statistics():
    translation = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "request_count": 1}
    review = {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10, "request_count": 1}
    total = AiTranslator._calculate_total_stats(None, None, translation, review)
    assert total["input_tokens"] == 18
    assert total["output_tokens"] == 7
    assert total["total_tokens"] == 25
    assert total["request_count"] == 2


def test_review_language_reaches_agent_and_rejects_invalid_value():
    import pytest
    from pydantic import ValidationError
    from docutranslate.translator.ai_translator.docx_translator import DocxTranslator

    for mode in ("source", "target"):
        payload = TypeAdapter(TranslatePayload).validate_python({
            "workflow_type": "docx", "base_url": "https://example.com/v1",
            "api_key": "test", "model_id": "test", "translation_review_enable": True,
            "translation_review_language": mode,
        })
        workflow = TranslationService()._create_workflow(
            payload=payload, task_logger=logging.getLogger(__name__),
            progress_tracker=ProgressTracker(), build_glossary_agent_config=lambda: None,
            md2docx_engine="auto",
        )
        assert DocxTranslator(workflow.config.translator_config).review_agent.review_language == mode
    with pytest.raises(ValidationError):
        TypeAdapter(TranslatePayload).validate_python({
            "workflow_type": "docx", "translation_review_language": "invalid",
        })


def test_pdf_native_docx_review_language_is_preserved():
    payload = TypeAdapter(TranslatePayload).validate_python({
        "workflow_type": "pdf_native_docx", "convert_engine": "mineru",
        "base_url": "https://example.com/v1", "api_key": "test", "model_id": "test",
        "translation_review_enable": True, "translation_review_language": "source",
    })
    workflow = TranslationService()._create_workflow(
        payload=payload, task_logger=logging.getLogger(__name__), progress_tracker=ProgressTracker(),
        build_glossary_agent_config=lambda: None, md2docx_engine="auto",
    )
    assert workflow.config.docx_workflow_config.translator_config.translation_review_language == "source"
