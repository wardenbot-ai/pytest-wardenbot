---
description: Serve recorded, exported or hand-written model replies to your application in CI, and record them locally.
---

# Response folders

A response folder is a directory of reply files the model endpoint serves in
place of a real model. In `replay` mode, the default once the endpoint is
configured, every request that isn't scripted gets its reply from the folder.
Projects bring their own data this way: export replies the application
already logged, or write them by hand, and run the pipeline against them in CI
with no API key.

## Configure it

```toml
# pyproject.toml, or the [model] table of wardenbot.toml
[tool.wardenbot.model]
responses_dir = "tests/llm_responses"
ignore_fields = ["user", "metadata"]  # request fields left out of the request hash
normalizers = ["myapp.tests.llm:strip_run_ids"]  # more request text to normalize
guard_hosts = []  # extra model API hosts for the egress guard
```

Paths resolve against the config file. Under pytest the file is found from
the rootdir; elsewhere from the working directory, up to the project root.

## Layout

```
tests/llm_responses/
  wardenbot-responses.toml       # optional manifest: rules, marker seed, allow patterns
  cases/<case>/                  # hand-written replies for one case, served in filename order
  recorded/<case>/<hash>-1.json  # written by record mode, with a .request.json sidecar
  exports/*.jsonl                # exported application logs
  anything/else.json             # files referenced by manifest rules
```

A case folder's name is the case name with every character outside
`[A-Za-z0-9_.-]` replaced by `_`: `tests/test_x.py::test_attack` becomes
`tests_test_x.py__test_attack`. Two case names that would share a folder fail
instead of silently sharing replies.

## Reply files

| File | Treated as | Served to |
|---|---|---|
| `*.json` with `"object": "response"` | A complete Responses body | `/v1/responses`; wrapped in events for a stream request |
| `*.json` with `"object": "chat.completion"` | A complete Chat Completions body | `/v1/chat/completions`; turned into chunks for a stream request |
| `*.json` with no such `object` | The assistant's JSON output (structured output) | Either endpoint, wrapped |
| `*.txt` | The assistant's text | Either endpoint, wrapped |
| `*.sse` | A raw event stream | Stream requests, byte for byte |
| `*.jsonl` | One `{"request": ..., "response": ..., "case"?: ..., "path"?: ...}` per line | Matched by request hash, or picked by a rule |

Wrapped replies are complete enough for SDK helpers such as
`responses.stream()` and `responses.parse`. Text and JSON files may contain
`{{wardenbot.marker}}` and `{{wardenbot.canary}}`, filled with the case's values.
`.sse` and `.jsonl` files are never rewritten, and a `.jsonl` line's `headers`
key is ignored.

Editors and whitespace hooks end files with one newline, so a `.txt` reply
drops one trailing newline and an `.sse` stream gets its final blank line
back. Better still, exclude response folders from whitespace fixers such as
pre-commit's `end-of-file-fixer`.

## How a request finds its reply

1. **Manifest rules**, checked in file order; the first match wins.
2. **The request hash, scoped to the case**: `recorded/<case>/` and `.jsonl`
   entries whose `case` is this case, then `.jsonl` entries with no `case`.
3. **The case folder**, `cases/<case>/`, one file per call. Running out fails.

Repeated identical requests replay in call order, and the last file repeats.
Each `model_endpoint` block starts counting again, so a naive and a fixed
implementation that share a case both get the first reply.
Requests made outside any block (module-level code, `runserver` under
`override`) are looked up afresh each time, so the result never depends on
which tests ran first: they get the first matching file, and a `files` rule
serves its first file.

### Manifest rules

```toml
marker_seed = "q7v2m9..."

[[response]]
case = "source_rating_attack"
file = "source_rating/attack_batch.json"
record = false  # hand-crafted hostile reply: record mode never overwrites it

[[response]]
path = "/v1/chat/completions"
contains = "Rate each source for relevance"  # substring of the prompt text
files = ["source_rating/batch_1.json", "source_rating/batch_2.json"]
then = "repeat_last"  # or "fail" (the default) once the list runs out

[[response]]
case = "posts_attack"
file = "exports/posts.jsonl"
where = { case = "posts_attack" }  # pick an entry by field, or line = 3
```

A rule can match on `case` (the full case name, or its last component, so
`test_attack` matches `tests/test_x.py::test_attack`), `path`, `model`,
`contains`, `regex` and `request_hash`, and every field it sets must match. A
rule that names a `.jsonl` file serves the entry it picks whatever the request
hash, which is how exported logs serve requests that changed since.

### The request hash

The hash covers the method, the path without its query string, and the whole
JSON body with keys sorted: `stream`, tools, `text.format` and
`response_format` included, so streamed and non-streamed requests differ. Fields
in `ignore_fields` are dropped first (top-level names or dotted paths), and
every string is normalized: ISO dates and UUIDs become placeholders, then your
`normalizers` run. Each is a function from a string to a string.

## Markers and canaries

`injection_marker()` returns the case's marker, to plant in untrusted input
and look for in the output. In `record`, `replay` and `override` it is derived
from the case name and the manifest's `marker_seed`, so a recorded reply holds
the same marker the replaying test plants, and request hashes match. `record`
writes a seed when there is none. `case_canary()` works the same way, unless a
canary is configured (the `wardenbot_canary` fixture or `WARDENBOT_CANARY`); use
a fixed one with recordings.

## When a request misses

A miss fails the `model_endpoint` block, even if the application caught the
HTTP error, with:

- the request: path, model, the start of each role's text, and its hash;
- every rule and file tried, and why it didn't match;
- a diff against the closest recorded request for the case;
- the command that records it.

The endpoint has no upstream in `replay`, so a miss can't reach the network,
and the egress guard catches clients that bypass the endpoint.

## Record and override locally

```bash
WARDENBOT_MODEL_MODE=record OPENAI_API_KEY=... pytest tests/test_pipeline.py
WARDENBOT_MODEL_MODE=override OPENAI_API_KEY=... pytest tests/test_pipeline.py
```

`record` writes each reply where replay will read it, taking replay's steps in
replay's order:

- a matching rule's file, or the Nth of its `files` on call N;
- a case folder's files in call order (further calls add files that sort after
  the last one);
- otherwise `recorded/<case>/<hash>-N.json` (`.sse` for streams).

Rules with `record = false`, rules that pick from a `.jsonl` file, and requests
a `.jsonl` entry already answers are served from the folder with no call. A
target that can't hold the reply is refused: an `.sse` file for a request that
doesn't stream (before the call is made), or a `.txt` file for a reply with
tool calls. On a case's first write, files in `recorded/<case>/` from before
the run are deleted, so nothing stale answers in front of a new reply; files
other pytest-xdist workers wrote during the run are kept. Cases that pass
`script=` are never recorded.

`override` serves what the folder has and sends misses to the real API without
saving them. Both modes, and `live`, refuse to run in CI. In `live` and
`override` the real API's errors reach your client with their retry headers,
so the SDK retries as it would in production; in `record` an upstream error
fails the test instead, since a retry would be saved as the next call.

The upstream is `WARDENBOT_UPSTREAM_BASE_URL`, else your original
`OPENAI_BASE_URL`, else `https://api.openai.com`. Your key is held in memory
and sent only there.

## Hygiene

Response folders get committed, so they must never hold credentials:

- recordings store request and response bodies, method, status and the path
  without its query string; never request headers;
- a non-2xx reply is never saved, because an error body can echo the key;
- the recorder and the loader scan every file for credential patterns (OpenAI,
  Anthropic, Google and AWS keys, GitHub tokens, Bearer tokens, `api_key=` and
  `key=` parameters) and refuse a match, naming the file and line. Event
  streams are also scanned with their deltas joined, since a model echoes a
  key a few characters at a time. Values made only of words, such as
  `your-api-key-here`, aren't flagged. Add a regular expression to
  `allow_patterns` in the manifest for a false positive, and plant secrets on
  purpose with `case_canary()`, whose tokens never look like keys;
- files under hidden folders (`.scratch/`) are neither served nor checked.

Response folders hold full prompts and model output: review them like source
code before committing. Check one without a test run:

```bash
python -m pytest_wardenbot.model check tests/llm_responses
```

It runs the credential scan, validates the manifest and `.jsonl` files, and
reports rules whose files are missing and rules an earlier rule always
preempts.
