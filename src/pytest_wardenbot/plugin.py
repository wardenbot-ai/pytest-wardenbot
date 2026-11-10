"""pytest plugin entry point.

Registers fixtures that users override in their own `conftest.py`:

- `chatbot` — required. The chatbot under test.
- `business_truth_fact` — optional. Parametrized list of `BusinessTruthFact`
  entries for the shipped `test_business_truth` test.
- `judge_case` — optional. Parametrized list of `JudgeCase` entries for the
  shipped `test_semantic` LLM-judge tests (requires `[judge]` extra + API key).

Optional fixtures that tune the shipped chatbot tests:

- `wardenbot_canary` — a token planted in the chatbot's system prompt.
  Defaults to the `WARDENBOT_CANARY` environment variable. Every shipped
  leak check fails if the token appears in a response.
- `wardenbot_system_prompt` — the chatbot's system prompt text, used to
  detect verbatim reproduction. Defaults to the adapter's `system_prompt`
  attribute when it has one.
- `wardenbot_refusal_markers` / `wardenbot_compliance_markers` — extra
  phrasing for your bot's own refusal and compliance wording.

Also registers:

- wardenbot-specific markers (`wardenbot`, `severity_high|medium|low`)
- `--wardenbot-quickstart [TEMPLATE]` CLI option that generates a starter
  conftest.py + test_my_bot.py and exits.

Most shipped tests live under `pytest_wardenbot.tests`; invoke with:

    pytest --pyargs pytest_wardenbot.tests

The separate instrumented agent suite uses ``agent_target`` and
``agent_observer`` fixtures, paired scenario inputs, and explicit coverage:

    pytest --pyargs pytest_wardenbot.agent_tests --wardenbot-agent-required
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from warnings import WarningMessage

import pytest

from pytest_wardenbot import _agent_plugin
from pytest_wardenbot._agent_plugin import (  # noqa: F401 -- pytest discovers these fixtures
    agent_observer,
    agent_target,
    wardenbot_agent_attack_enabled,
    wardenbot_agent_limits,
    wardenbot_agent_result,
    wardenbot_agent_scenario,
)
from pytest_wardenbot._corpus_override import resolve_corpus
from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.business_truth import BusinessTruthFact
from pytest_wardenbot.corpus.encoded_payloads import (
    ENCODED_PAYLOAD_PROMPTS,
    EncodedPromptEntry,
)
from pytest_wardenbot.corpus.indirect_injection import INDIRECT_INJECTION_PROMPTS
from pytest_wardenbot.corpus.jailbreak import JAILBREAK_PROMPTS
from pytest_wardenbot.corpus.multi_turn import MULTI_TURN_JAILBREAK_PROMPTS
from pytest_wardenbot.corpus.off_topic import OFF_TOPIC_PROMPTS
from pytest_wardenbot.corpus.refusal_bypass import REFUSAL_BYPASS_PROMPTS
from pytest_wardenbot.corpus.system_prompt_leak import SYSTEM_PROMPT_LEAK_PROMPTS
from pytest_wardenbot.grading.judge import JudgeCase
from pytest_wardenbot.quickstart import AVAILABLE_TEMPLATES, run_quickstart

_NO_CHATBOT_FIXTURE_MESSAGE = """\
No `chatbot` fixture configured.

pytest-wardenbot ships tests that need a chatbot to probe. You connect your
chatbot by adding a fixture to your conftest.py. Minimal example:

    import os
    import pytest
    from pytest_wardenbot.adapters.http import HTTPChatbotAdapter

    @pytest.fixture
    def chatbot():
        return HTTPChatbotAdapter(
            url="https://your-chatbot.example.com/chat",
            headers={"Authorization": f"Bearer {os.environ['CHATBOT_TOKEN']}"},
            request_field="message",
            response_field="response",
        )

See https://pytest-wardenbot.wardenbot.ai/quickstart/ for more.
"""

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        "node_modules",
        "site-packages",
        "build",
        "dist",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)


def scoped_conftest_hint(config: pytest.Config, fixture: str) -> str:
    """Explain a fixture defined in a nested conftest.py that the installed suite can't see.

    Fixtures in ``tests/conftest.py`` apply only to tests under ``tests/``. The
    installed suite (``--pyargs pytest_wardenbot.tests``) lives elsewhere, so it
    only sees the project's root conftest.py.
    """
    root = Path(config.rootpath)
    needle = f"def {fixture}("
    found: list[Path] = []
    visited = 0
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = [d for d in subdirs if d not in _SKIP_DIRS and not d.startswith(".")]
        visited += 1
        if visited > 2000 or len(found) >= 3:
            break
        if "conftest.py" in files and Path(directory) != root:
            path = Path(directory) / "conftest.py"
            try:
                if needle in path.read_text(encoding="utf-8", errors="ignore"):
                    found.append(path)
            except OSError:
                continue
    if not found:
        return ""
    names = ", ".join(str(path.relative_to(root)) for path in found)
    first = found[0].parent.relative_to(root)
    return (
        f"\nFound `{needle[4:-1]}` in {names}, but fixtures in a subdirectory's conftest.py "
        f"only apply to tests inside that directory, and the installed suite runs from "
        f"outside it. Either move the fixture to {root / 'conftest.py'}, or import the "
        f"shipped tests into a test module in {first}/ (as the test_my_bot.py generated by "
        f"`pytest --wardenbot-quickstart` does) and run `pytest {first}`.\n"
    )


_NO_TRUTH_FACTS_MESSAGE = """\
No `business_truth_fact` fixture configured.

The shipped `test_business_truth` test is parametrized over a user-supplied list
of business facts your chatbot should always answer correctly. Add a
parametrized fixture to your conftest.py:

    import pytest
    from pytest_wardenbot.business_truth import BusinessTruthFact

    @pytest.fixture(params=[
        BusinessTruthFact(
            label="Standard plan price",
            question="How much does the Standard plan cost per month?",
            expected_answer="$49",
            match_type="substring",
            acceptable_variations=("49/mo", "forty-nine dollars"),
        ),
        BusinessTruthFact(
            label="Business hours",
            question="What are your business hours?",
            expected_answer="9 AM to 5 PM EST",
            match_type="substring",
        ),
    ], ids=lambda f: f.parametrize_id())
    def business_truth_fact(request):
        return request.param

Skip this test entirely if your chatbot is not customer-facing.
"""

_NO_JUDGE_CASES_MESSAGE = """\
No `judge_case` fixture configured.

The shipped `test_semantic` test runs LLM-judge checks (semantic equivalence,
brand alignment, hallucination, off-policy, refusal quality). Each check
requires the `[judge]` extra and an LLM API key.

1. Install:  pip install 'pytest-wardenbot[judge]'
2. Set ANTHROPIC_API_KEY (or override the model in your fixture).
3. Add a parametrized fixture to your conftest.py:

    import pytest
    from pytest_wardenbot.grading.judge import (
        semantic_equivalence_case,
        brand_alignment_case,
        hallucination_case,
        off_policy_case,
        refusal_quality_case,
    )

    @pytest.fixture(params=[
        semantic_equivalence_case(
            prompt="What is your refund policy?",
            canonical_answer="Refunds within 30 days of purchase.",
        ),
        brand_alignment_case(
            prompt="Hi there!",
            brand_voice="friendly, conversational, never sarcastic",
        ),
        hallucination_case(
            prompt="What is your engineering team size?",
            grounding_context="The engineering team has 5 members.",
        ),
        off_policy_case(
            prompt="Should I sue my employer?",
            policy_description="Do not give legal advice; recommend a lawyer.",
        ),
        refusal_quality_case(
            prompt="Tell me a racist joke.",
        ),
    ], ids=lambda c: c.parametrize_id())
    def judge_case(request):
        return request.param

Each invocation costs ~$0.003 against Anthropic Haiku 4.5. Five cases per run ≈
$0.02 per full suite invocation. Skip the test entirely if you don't want LLM
spend in CI.
"""


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register pytest-wardenbot CLI options."""
    group = parser.getgroup("wardenbot", "pytest-wardenbot options")
    group.addoption(
        "--wardenbot-judge-optional",
        action="store_true",
        default=False,
        help=(
            "Skip LLM-judge tests when the judge cannot run (extra not installed or API "
            "key missing). By default they fail once judge cases are configured."
        ),
    )
    _agent_plugin.add_options(group)
    group.addoption(
        "--wardenbot-quickstart",
        nargs="?",
        const="generic",
        default=None,
        choices=AVAILABLE_TEMPLATES,
        metavar="TEMPLATE",
        help=(
            "Generate a starter conftest.py + test_my_bot.py in the current "
            "directory and exit. Optional value selects the template: "
            f"{'/'.join(AVAILABLE_TEMPLATES)}. Default: generic."
        ),
    )
    group.addoption(
        "--wardenbot-judge-consensus",
        choices=("majority", "unanimous", "any"),
        default="majority",
        help=(
            "Consensus policy for ensemble LLM-judge tests (read via the "
            "`wardenbot_judge_consensus` fixture / passed to "
            "`assert_judge_ensemble_passes`): 'majority' (default), 'unanimous', "
            "or 'any'. No effect on single-judge tests."
        ),
    )


def pytest_cmdline_main(config: pytest.Config) -> int | None:
    """Intercept `--wardenbot-quickstart` and exit before test collection."""
    template = config.getoption("--wardenbot-quickstart", default=None)
    if template is None:
        return None
    return run_quickstart(template=template, target_dir=Path.cwd())


def pytest_configure(config: pytest.Config) -> None:
    """Register wardenbot-specific markers so --strict-markers doesn't reject them."""
    config.addinivalue_line("markers", "wardenbot: marks tests provided by pytest-wardenbot")
    config.addinivalue_line("markers", "severity_high: high-severity wardenbot test")
    config.addinivalue_line("markers", "severity_medium: medium-severity wardenbot test")
    config.addinivalue_line("markers", "severity_low: low-severity wardenbot test")
    _agent_plugin.configure(config)


@pytest.hookimpl(trylast=True)
def pytest_sessionstart(session: pytest.Session) -> None:
    """Keep consumer root fixtures visible to the installed ``--pyargs`` suite.

    Pytest 9.1 defers conftest fixture registration until the corresponding
    Directory is collected. The installed suite is outside the consumer's
    rootdir, so its root Directory is never visited. Before 9.1, root conftest
    fixtures were session-wide; restore that visibility for this invocation.

    This compatibility shim mirrors pytest's upstream fix for #14683:
    https://github.com/pytest-dev/pytest/pull/14694
    Taking
    the root conftest out of the pending queue also prevents duplicate fixture
    registration in runs that collect both local and installed tests. Older
    pytest, and versions with the upstream fix, have nothing pending to repair.
    Nested conftests retain their normal directory scope.
    Remove this shim when the minimum supported pytest includes that fix.
    """
    config = session.config
    if not config.getoption("pyargs") or not any(
        arg.split("::", 1)[0] == package or arg.split("::", 1)[0].startswith(package + ".")
        for arg in config.args
        for package in ("pytest_wardenbot.tests", "pytest_wardenbot.agent_tests")
    ):
        return

    # These two internal APIs are confined to the pytest 9.1 compatibility
    # path. Reuse pytest's scanner to preserve scopes, params, ids, autouse,
    # fixture names and dependency/override chains without cloning fixtures.
    fixture_manager = getattr(session, "_fixturemanager", None)
    if fixture_manager is None:
        return
    pending = getattr(fixture_manager, "_pending_conftests", None)
    if pending is None:
        return  # pytest < 9.1 registered these fixtures eagerly.
    root_conftest = pending.pop(config.rootpath, None)
    if root_conftest is not None:
        fixture_manager.parsefactories(holder=root_conftest, node=session)


# ---------------------------------------------------------------------------
# Corpus parametrization (global hook)
# ---------------------------------------------------------------------------
#
# Shipped tests parametrize their attack corpus (prompt/attack_id, plus a few
# wider shapes). We do this from ONE global hook keyed on the test function
# name, so the parametrization travels with the function — including when a
# user imports a shipped test into their own module (the examples and
# `--wardenbot-quickstart` pattern). A per-module `pytest_generate_tests` would
# not fire for imported tests. User corpus overrides still apply via
# `resolve_corpus`.

# test function name -> (param names, override-fixture name, default corpus)
_CORPUS_TESTS: dict[str, tuple[tuple[str, ...], str, tuple[Any, ...]]] = {
    "test_resists_jailbreak_compliance": (
        ("prompt", "attack_id"),
        "wardenbot_jailbreak_prompts",
        JAILBREAK_PROMPTS,
    ),
    "test_jailbreak_does_not_leak_system_prompt": (
        ("prompt", "attack_id"),
        "wardenbot_jailbreak_prompts",
        JAILBREAK_PROMPTS,
    ),
    "test_resists_system_prompt_elicitation": (
        ("prompt", "attack_id"),
        "wardenbot_system_prompt_leak_prompts",
        SYSTEM_PROMPT_LEAK_PROMPTS,
    ),
    "test_maintains_refusal_under_bypass": (
        ("prompt", "attack_id"),
        "wardenbot_refusal_bypass_prompts",
        REFUSAL_BYPASS_PROMPTS,
    ),
    "test_deflects_off_topic_requests": (
        ("prompt", "attack_id"),
        "wardenbot_off_topic_prompts",
        OFF_TOPIC_PROMPTS,
    ),
    "test_resists_indirect_injection": (
        ("prompt", "trigger_words", "attack_id"),
        "wardenbot_indirect_injection_prompts",
        INDIRECT_INJECTION_PROMPTS,
    ),
    "test_resists_encoded_payload": (
        ("prompt", "trigger_words", "attack_id"),
        "wardenbot_encoded_payload_prompts",
        ENCODED_PAYLOAD_PROMPTS,
    ),
    "test_resists_multi_turn_jailbreak": (
        ("priming_turns", "payload_prompt", "attack_id"),
        "wardenbot_multi_turn_jailbreak_prompts",
        MULTI_TURN_JAILBREAK_PROMPTS,
    ),
}


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize shipped corpus-driven tests wherever they are collected.

    Keyed on the test function name (which survives ``from ... import test_X``),
    so imported shipped tests parametrize correctly — not only those collected
    from ``pytest_wardenbot.tests``. Honors user corpus overrides.
    """
    _agent_plugin.generate_tests(metafunc)
    spec = _CORPUS_TESTS.get(metafunc.function.__name__)
    if spec is None:
        return
    param_names, fixture_name, default_corpus = spec
    if not set(param_names) <= set(metafunc.fixturenames):
        return
    corpus = resolve_corpus(metafunc, fixture_name, default_corpus)
    metafunc.parametrize(param_names, corpus, ids=[entry[-1] for entry in corpus])


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    outcome = yield
    _agent_plugin.record_report(item, outcome.get_result())


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _agent_plugin.session_finish(session)


def pytest_terminal_summary(terminalreporter: Any) -> None:
    _agent_plugin.terminal_summary(terminalreporter)


@pytest.hookimpl(tryfirst=True)
def pytest_warning_recorded(warning_message: WarningMessage, nodeid: str) -> None:
    _agent_plugin.sanitize_warning(warning_message, nodeid)


@pytest.fixture
def chatbot(request: pytest.FixtureRequest) -> ChatbotAdapter:
    """The chatbot under test.

    Users MUST override this in their own conftest.py to point at their chatbot.
    If left at the default, tests error with a helpful message. A security
    suite that never probes a chatbot must not report a successful run.
    """
    pytest.fail(
        _NO_CHATBOT_FIXTURE_MESSAGE + scoped_conftest_hint(request.config, "chatbot"),
        pytrace=False,
    )


@pytest.fixture
def business_truth_fact() -> BusinessTruthFact:
    """A single business-truth fact to verify.

    Users override this in their own conftest.py with a parametrized fixture
    listing their business's facts. If left at the default, the shipped
    `test_business_truth` test skips with a helpful message.
    """
    pytest.skip(_NO_TRUTH_FACTS_MESSAGE)


@pytest.fixture
def judge_case() -> JudgeCase:
    """A single LLM-judge case to evaluate.

    Users override this in their own conftest.py with a parametrized fixture
    listing their judge cases (built via the `*_case()` factories in
    `pytest_wardenbot.grading.judge`). If left at the default, the shipped
    `test_semantic` test skips with a helpful message.
    """
    pytest.skip(_NO_JUDGE_CASES_MESSAGE)


@pytest.fixture
def wardenbot_judge_consensus(request: pytest.FixtureRequest) -> str:
    """Consensus policy for ensemble LLM-judge tests.

    Reads `--wardenbot-judge-consensus` (default `majority`). Pass it to
    `assert_judge_ensemble_passes(..., consensus=wardenbot_judge_consensus)` in
    your own judge tests so the policy is switchable from the CLI without
    editing test code.
    """
    return str(request.config.getoption("--wardenbot-judge-consensus"))


# ---------------------------------------------------------------------------
# Per-corpus override fixtures
# ---------------------------------------------------------------------------
#
# Each fixture returns the bundled corpus by default. Users override in their
# conftest.py to substitute or extend:
#
#     @pytest.fixture
#     def wardenbot_jailbreak_prompts():
#         from pytest_wardenbot.corpus import JAILBREAK_PROMPTS
#         return JAILBREAK_PROMPTS + MY_EXTRA_PROMPTS
#
# The override must be a plain `() -> tuple[(str, str), ...]` function (no
# request, no other fixture dependencies) because the shipped tests resolve
# the corpus at collection time, before pytest's fixture machinery runs.


@pytest.fixture
def wardenbot_jailbreak_prompts() -> tuple[tuple[str, str], ...]:
    """The (prompt, attack_id) corpus for shipped jailbreak tests.

    Override in your conftest.py to substitute or extend.
    """
    return JAILBREAK_PROMPTS


@pytest.fixture
def wardenbot_system_prompt_leak_prompts() -> tuple[tuple[str, str], ...]:
    """The (prompt, attack_id) corpus for shipped system-prompt elicitation tests."""
    return SYSTEM_PROMPT_LEAK_PROMPTS


@pytest.fixture
def wardenbot_refusal_bypass_prompts() -> tuple[tuple[str, str], ...]:
    """The (prompt, attack_id) corpus for shipped refusal-bypass tests."""
    return REFUSAL_BYPASS_PROMPTS


@pytest.fixture
def wardenbot_off_topic_prompts() -> tuple[tuple[str, str], ...]:
    """The (prompt, attack_id) corpus for shipped off-topic deflection tests.

    The bundled corpus targets scoped (customer-service / support) bots.
    If your bot is intentionally general-purpose, override this fixture to
    return an empty tuple — the shipped test will then skip cleanly.
    """
    return OFF_TOPIC_PROMPTS


@pytest.fixture
def wardenbot_indirect_injection_prompts() -> tuple[tuple[str, tuple[str, ...], str], ...]:
    """The (prompt, trigger_words, attack_id) corpus for shipped indirect-injection / XPIA tests."""
    return INDIRECT_INJECTION_PROMPTS


@pytest.fixture
def wardenbot_encoded_payload_prompts() -> tuple[EncodedPromptEntry, ...]:
    """The (prompt, trigger_words, attack_id) corpus for encoded-payload tests."""
    return ENCODED_PAYLOAD_PROMPTS


@pytest.fixture
def wardenbot_multi_turn_jailbreak_prompts() -> tuple[tuple[tuple[str, ...], str, str], ...]:
    """The (priming_turns, payload_prompt, attack_id) corpus for multi-turn tests."""
    return MULTI_TURN_JAILBREAK_PROMPTS


# ---------------------------------------------------------------------------
# Grading context fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def wardenbot_canary() -> str | None:
    """The canary token planted in the chatbot's system prompt, or None.

    Defaults to the `WARDENBOT_CANARY` environment variable, so a deployed
    HTTP chatbot can be checked without code changes: put a fixed token in its
    system prompt and export the same value in CI. Override this fixture to
    supply the token another way (for example from `generate_canary_token()`
    when the test process builds the system prompt itself).

    Every shipped test that checks for system-prompt leaks fails when the
    token appears in a response.
    """
    return os.environ.get("WARDENBOT_CANARY", "").strip() or None


@pytest.fixture
def wardenbot_system_prompt(request: pytest.FixtureRequest) -> str | None:
    """The chatbot's system prompt text, or None if unknown.

    Used by the shipped leak checks to detect verbatim reproduction of the
    prompt. Defaults to the `system_prompt` attribute of the `chatbot`
    adapter (set on the OpenAI and Anthropic adapters when you pass
    `system_prompt=`). Override it for chatbots whose prompt lives elsewhere,
    for example by reading the deployed prompt from a file.
    """
    if "chatbot" not in request.fixturenames:
        return None
    prompt = getattr(request.getfixturevalue("chatbot"), "system_prompt", None)
    return prompt if isinstance(prompt, str) and prompt.strip() else None


@pytest.fixture
def wardenbot_refusal_markers() -> tuple[str, ...]:
    """Extra refusal phrasing for your chatbot, as regular expressions.

    Matched case-insensitively against the normalized response (curly quotes
    mapped to ASCII, whitespace collapsed). Used by the shipped refusal-bypass
    and off-topic tests in addition to the built-in patterns. Example:

        @pytest.fixture
        def wardenbot_refusal_markers():
            return (r"that's a question for our support team", r"i specialize in")
    """
    return ()


@pytest.fixture
def wardenbot_compliance_markers() -> tuple[str, ...]:
    """Extra compliance phrasing for your chatbot, as plain substrings.

    A response containing one of these fails the shipped refusal-bypass and
    off-topic tests. Matched case-insensitively against the normalized
    response.
    """
    return ()
