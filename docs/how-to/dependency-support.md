# Dependency support

The package declares Python 3.11 or later and pytest 8.1.1 or later. CI checks
Python 3.11, 3.12, 3.13 and 3.14 with the newest stable pytest that pip resolves.
A separate Python 3.11 lane checks exactly pytest 8.1.1. Resolved versions are
printed in each CI run; the current lane moves as new stable versions ship.

Pytest 8.0.x has an upstream `--pyargs` collection regression that can fail on
unrelated protected directories. The floor is 8.1.1, which includes the fix;
8.1.0 was yanked. See the [pytest 8.1.1 changelog](https://docs.pytest.org/en/8.1.x/changelog.html#pytest-8-1-1-2024-03-08).

The minimum core lane uses pytest-asyncio 0.23.8 and pytest-cov 5.0.0 as its
test harness, rather than installing the dev extra. This checks the declared
core pytest floor without forcing newer requirements from development tools.
The `[async]` extra starts at pytest-asyncio 0.24, which requires pytest 8.2
or later ([pytest-asyncio 0.24 metadata](https://pypi.org/pypi/pytest-asyncio/0.24.0/json));
pip resolves the additional requirements when installing that extra.

## Floors without known vulnerabilities

No declared floor has a published advisory. CI's dependency audit fails if one
appears, and also audits the current resolution with every extra and the
hash-locked tool requirements, on every change and weekly. Floors raised for
this reason in 0.6.1: pydantic 2.4.0, langchain-core 1.3.3 for the `langchain`
and `langgraph` extras (the 0.3 line has unfixed advisories), and LangGraph
1.0.10.

One exception remains until 0.7.0: pytest 8.1.1 is affected by
[CVE-2025-71176](https://github.com/advisories/GHSA-6w46-j5rx-g56g), where other
local users on a shared UNIX machine can interfere with pytest's temporary
directories. Only pytest 9.0.3 fixes it, so raising the floor drops pytest 8.
Version 0.7.0 raises the floor to 9.0.3. Until then, pip installs a fixed
pytest unless your project pins an older one.

## Optional SDKs

| Extra | Exact tested floor | Current version tested on 2026-10-11 |
| --- | --- | --- |
| `openai` | OpenAI 1.66.3 | 3.29.0 |
| `anthropic` | Anthropic 0.49.0 | 1.13.0 |
| `langchain` | langchain-core 1.3.3 | 1.7.7 |
| `judge` | DeepEval 4.2.8 | 4.2.8 |
| `mcp` | MCP SDK 2.2.0; Uvicorn 0.31.1 | MCP SDK 2.3.0 |
| `langgraph` | LangGraph 1.0.10 (with langgraph-prebuilt 1.0.8); langchain-core 1.3.3 | LangGraph 1.2.20; langchain-core 1.7.7 |
| `claude-agent` | Claude Agent SDK 0.2.140 | Claude Agent SDK 0.2.180 |

CI's real-SDK contract matrix installs these exact floors and a separate set
of current stable releases on Python 3.12. OpenAI and Anthropic tests construct
real clients and use in-process HTTP transports to check serialization, output,
error handling, concurrent independent sessions and reset behavior. LangChain
tests execute real Runnables. DeepEval contracts use both an offline model and
real provider SDK transports, including the default Anthropic judge path.
No provider API calls or credentials are needed for these contract tests.

The judge extra includes the Anthropic SDK required by its default judge.
DeepEval 2.0 lacks the Anthropic and Gemini model wrappers used by the plugin;
4.2.8 is the verified floor for the current provider setup.

The OpenAI floor includes Responses support. The old Anthropic 0.30 floor
failed default client construction with current httpx because it passes the
removed `proxies` argument. Version 0.40 fixes construction but lacks the
`thinking` request argument used by the current DeepEval default judge. The
combined contract passes at 0.49.0. Current vendor SDKs use httpx2 internally,
while the plugin's HTTP adapter still uses httpx.

The current lane also executes the LangGraph state recipe with
`langgraph==1.2.14`; the observed checkpoint version is 4.2.0. LangGraph is not
part of the LangChain extra, and the minimum LangChain lane does not claim
compatibility with current LangGraph. See [the state recipe](langgraph-state.md).

The `langgraph` and `claude-agent` extras are tested in the MCP contract
lanes: the floors on Python 3.11 with MCP SDK 2.2.0, and current releases on
Python 3.12, 3.13 and 3.14. Claude Agent SDK 0.2.140 is the first release that allows
MCP SDK 2.x. CI tests LangGraph 1.0.10 with `langgraph-prebuilt==1.0.8`.
LangGraph 1.0.10 also allows prebuilt 1.0.13, which imports names LangGraph
1.0.x lacks; pin prebuilt if you stay on LangGraph 1.0. The OpenAI Agents SDK recipe
is tested with the current `openai-agents` release (0.24.0) and is not an
extra.

A dependency floor is a resolver constraint, not evidence that every release
above it has been tested. Unit tests and real-SDK contracts check request construction,
responses, errors, and conversation behavior without provider credentials.
The async-to-sync bridge also exercises repeated real SDK requests against a
local HTTP server, catching connection reuse across event-loop lifetimes.
The manual live-API smoke workflow checks selected installed SDKs against real
services and requires provider credentials; it is not the pull-request gate.

Before claiming a new SDK range, test the exact proposed minimum and a current
stable version with real SDK clients and local transports, record resolved
versions, and update this page and CI together. Test dependency resolution as
well as adapter behavior. Add bounds only when a reproduced incompatibility
justifies them. The judge extra has its own transitive requirements and should
be tested separately from the core minimum lane.

## Packaging and tooling

The optional [MCP harness](mcp-harness.md) has a separate Python 3.11 floor and
Python 3.12–3.14 current matrix. Its real SDK tests cover in-memory, stdio and
loopback Streamable HTTP transports with 2025-11-25 and 2026-07-28 protocol modes.
SDK 2.0.1 failed stdio construction; 2.2.0 is the verified floor. The `<3` bound
keeps a future SDK major outside this tested integration. No MCP package is
required for the core agent contracts or existing chatbot suite.

CI builds and verifies both the sdist and wheel. A fresh environment installs
the wheel and runs the packaged probes from an external consumer directory,
covering plugin entry-point discovery and consumer fixture configuration.
Both the chatbot suite and the packaged agent suite run on minimum/current
pytest from installed wheels. The agent checks also verify versioned selection,
paired baselines, missing configuration, required-coverage deselection and
recorded violations. The reference Responses/MCP agent has offline SDK tests
at the supported OpenAI/MCP floors and current versions; its installed example
uses the real stdio transport without provider requests. The independent support
application example uses only the OpenAI extra and direct local application APIs;
its clean-wheel check explicitly verifies that MCP is absent. Both SDK floors
and current versions exercise its offline model loop.

Ruff and Pyright are pinned to the same versions in the dev extra and
pre-commit hooks. Update both files together and review any resulting lint or
format changes. These tool pins are contributor tooling, not runtime limits.
