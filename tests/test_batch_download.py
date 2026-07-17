import os
import zipfile

import pytest
from fastapi import HTTPException

from docutranslate import app as app_module


def _completed_state(result_path, attachment_path=None, unresolved_errors=0):
    state = {
        "is_processing": False,
        "error_flag": False,
        "download_ready": True,
        "original_filename": "../unsafe report.pdf",
        "original_filename_stem": "../unsafe report",
        "downloadable_files": {
            "markdown": {"path": str(result_path), "filename": "../translated.md"},
        },
        "attachment_files": {},
        "statistics": {"total": {"unresolved_errors": unresolved_errors}},
    }
    if attachment_path:
        state["attachment_files"]["glossary"] = {
            "path": str(attachment_path),
            "filename": "terms.csv",
        }
    return state


def test_create_batch_download_archive_packages_results_and_attachments(tmp_path, monkeypatch):
    result = tmp_path / "translated.md"
    attachment = tmp_path / "terms.csv"
    result.write_text("translated", encoding="utf-8")
    attachment.write_text("src,dst", encoding="utf-8")
    state = _completed_state(result, attachment)
    monkeypatch.setattr(app_module.translation_service, "get_task_state", lambda task_id: state)

    archive_path = app_module._create_batch_download_archive(["task-123456", "task-123456"])
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            assert len(names) == 2
            assert all(".." not in name for name in names)
            assert names == ["translated.md", "terms.csv"]
            assert all("/" not in name for name in names)
    finally:
        os.unlink(archive_path)


@pytest.mark.parametrize("state", [None, {"download_ready": False}, {"download_ready": True, "error_flag": True}])
def test_create_batch_download_archive_rejects_invalid_tasks(state, monkeypatch):
    monkeypatch.setattr(app_module.translation_service, "get_task_state", lambda task_id: state)
    with pytest.raises(HTTPException) as exc:
        app_module._create_batch_download_archive(["bad-task"])
    assert exc.value.status_code == 409


def test_create_batch_download_archive_rejects_partial_success(tmp_path, monkeypatch):
    result = tmp_path / "translated.md"
    result.write_text("translated", encoding="utf-8")
    state = _completed_state(result, unresolved_errors=1)
    monkeypatch.setattr(app_module.translation_service, "get_task_state", lambda task_id: state)
    with pytest.raises(HTTPException) as exc:
        app_module._create_batch_download_archive(["partial-task"])
    assert exc.value.status_code == 409


def test_create_batch_download_archive_filters_file_types_and_attachments(tmp_path, monkeypatch):
    markdown = tmp_path / "translated.md"
    html = tmp_path / "translated.html"
    attachment = tmp_path / "terms.csv"
    markdown.write_text("markdown", encoding="utf-8")
    html.write_text("html", encoding="utf-8")
    attachment.write_text("src,dst", encoding="utf-8")
    state = _completed_state(markdown, attachment)
    state["downloadable_files"]["html"] = {"path": str(html), "filename": "translated.html"}
    monkeypatch.setattr(app_module.translation_service, "get_task_state", lambda task_id: state)

    archive_path = app_module._create_batch_download_archive(
        ["task-123456"], file_types=["html"], include_attachments=False
    )
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            assert len(names) == 1
            assert names[0] == "translated.html"
    finally:
        os.unlink(archive_path)


def test_create_batch_download_archive_rejects_empty_selection(tmp_path, monkeypatch):
    result = tmp_path / "translated.md"
    result.write_text("translated", encoding="utf-8")
    state = _completed_state(result)
    monkeypatch.setattr(app_module.translation_service, "get_task_state", lambda task_id: state)
    with pytest.raises(HTTPException) as exc:
        app_module._create_batch_download_archive(
            ["task-123456"], file_types=[], include_attachments=False
        )
    assert exc.value.status_code == 400


def test_create_batch_download_archive_renames_duplicate_files(tmp_path, monkeypatch):
    result = tmp_path / "translated.md"
    result.write_text("translated", encoding="utf-8")
    state = _completed_state(result)
    monkeypatch.setattr(app_module.translation_service, "get_task_state", lambda task_id: state)

    archive_path = app_module._create_batch_download_archive(["task-one", "task-two"])
    try:
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.namelist() == ["translated.md", "translated-2.md"]
    finally:
        os.unlink(archive_path)


def test_create_batch_download_archive_keeps_valid_tasks_when_one_is_invalid(tmp_path, monkeypatch):
    result = tmp_path / "translated.md"
    result.write_text("translated", encoding="utf-8")
    valid_state = _completed_state(result)
    monkeypatch.setattr(
        app_module.translation_service,
        "get_task_state",
        lambda task_id: valid_state if task_id == "valid-task" else None,
    )

    archive_path = app_module._create_batch_download_archive(["expired-task", "valid-task"])
    try:
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.namelist() == ["translated.md"]
    finally:
        os.unlink(archive_path)
