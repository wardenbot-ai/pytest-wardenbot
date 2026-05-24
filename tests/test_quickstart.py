"""Tests for the quickstart module + the `--wardenbot-quickstart` CLI option."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from pytest_wardenbot.quickstart import (
    AVAILABLE_TEMPLATES,
    generate,
    run_quickstart,
)

# ---------------------------------------------------------------------------
# generate() — direct file-creation tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", AVAILABLE_TEMPLATES)
def test_generate_creates_both_files_per_template(tmp_path: Path, template: str) -> None:
    created = generate(template, tmp_path)  # type: ignore[arg-type]
    assert len(created) == 2
    assert (tmp_path / "conftest.py").exists()
    assert (tmp_path / "test_my_bot.py").exists()


def test_generated_conftest_contains_expected_fixtures(tmp_path: Path) -> None:
    generate("generic", tmp_path)
    text = (tmp_path / "conftest.py").read_text()
    assert "def chatbot" in text
    assert "def business_truth_fact" in text
    assert "HTTPChatbotAdapter" in text
    assert "BusinessTruthFact" in text
    assert "CHATBOT_URL" in text


def test_generated_test_file_imports_all_shipped_tests(tmp_path: Path) -> None:
    generate("generic", tmp_path)
    text = (tmp_path / "test_my_bot.py").read_text()
    assert "test_business_truth" in text
    assert "test_deflects_off_topic_requests" in text
    assert "test_resists_jailbreak_compliance" in text
    assert "test_jailbreak_does_not_leak_system_prompt" in text
    assert "test_maintains_refusal_under_bypass" in text
    assert "test_resists_system_prompt_elicitation" in text


def test_generated_ecommerce_template_has_ecommerce_facts(tmp_path: Path) -> None:
    generate("ecommerce", tmp_path)
    text = (tmp_path / "conftest.py").read_text()
    assert "shipping" in text.lower()
    assert "refund" in text.lower()


def test_generated_saas_template_has_saas_facts(tmp_path: Path) -> None:
    generate("saas-support", tmp_path)
    text = (tmp_path / "conftest.py").read_text()
    assert "starter" in text.lower()
    assert "trial" in text.lower()


def test_generate_refuses_to_overwrite_existing_files(tmp_path: Path) -> None:
    (tmp_path / "conftest.py").write_text("# already here")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        generate("generic", tmp_path)


def test_generate_refuses_when_only_test_file_exists(tmp_path: Path) -> None:
    (tmp_path / "test_my_bot.py").write_text("# already here")
    with pytest.raises(FileExistsError, match=r"test_my_bot\.py"):
        generate("generic", tmp_path)


def test_generate_creates_target_dir_if_missing(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "deeper"
    generate("generic", nested)
    assert (nested / "conftest.py").exists()


# ---------------------------------------------------------------------------
# run_quickstart() — exit codes + messaging
# ---------------------------------------------------------------------------


def test_run_quickstart_success_returns_zero_and_prints_next_steps(
    tmp_path: Path,
) -> None:
    out = io.StringIO()
    rc = run_quickstart("generic", target_dir=tmp_path, out=out)
    assert rc == 0
    message = out.getvalue()
    assert "quickstart (generic template) created" in message
    assert "conftest.py" in message
    assert "test_my_bot.py" in message
    assert "Next steps" in message
    assert "pytest" in message


def test_run_quickstart_returns_nonzero_when_files_exist(tmp_path: Path) -> None:
    (tmp_path / "conftest.py").write_text("# already here")
    out = io.StringIO()
    rc = run_quickstart("generic", target_dir=tmp_path, out=out)
    assert rc == 1
    assert "quickstart failed" in out.getvalue()
    assert "Refusing to overwrite" in out.getvalue()


def test_run_quickstart_rejects_unknown_template(tmp_path: Path) -> None:
    out = io.StringIO()
    rc = run_quickstart("nonexistent-template", target_dir=tmp_path, out=out)  # type: ignore[arg-type]
    assert rc == 2
    assert "Unknown template" in out.getvalue()


def test_run_quickstart_falls_back_to_print_when_out_is_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = run_quickstart("generic", target_dir=tmp_path, out=None)
    assert rc == 0
    captured = capsys.readouterr()
    assert "quickstart" in captured.out


def test_generated_files_are_syntactically_valid_python(tmp_path: Path) -> None:
    """Compile both generated files to verify they're valid Python."""
    generate("generic", tmp_path)
    conftest_src = (tmp_path / "conftest.py").read_text()
    test_src = (tmp_path / "test_my_bot.py").read_text()
    compile(conftest_src, str(tmp_path / "conftest.py"), "exec")
    compile(test_src, str(tmp_path / "test_my_bot.py"), "exec")


@pytest.mark.parametrize("template", AVAILABLE_TEMPLATES)
def test_all_generated_templates_compile(tmp_path: Path, template: str) -> None:
    generate(template, tmp_path)  # type: ignore[arg-type]
    conftest_src = (tmp_path / "conftest.py").read_text()
    compile(conftest_src, "conftest.py", "exec")
