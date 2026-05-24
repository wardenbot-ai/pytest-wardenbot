# Business truth

Verifies your chatbot answers correctly about your business — pricing, hours,
refund policy, contact info, anything else you'd put in a customer-facing
knowledge base.

## What this catches

The most common chatbot failure mode in production: a vendor pushes a model
update and your bot starts confidently saying "$59" when your actual price
is "$49." Customer reads it, screenshots it, and now you're arguing about
honoring a price your bot invented.

## How it works

Users provide a parametrized fixture listing facts the chatbot must know.
The shipped test runs once per fact, asking the chatbot the configured
question and verifying the response matches the expected answer.

## Configuration

```python
from pytest_wardenbot.business_truth import BusinessTruthFact

@pytest.fixture(params=[
    BusinessTruthFact(
        label="Standard plan price",
        question="How much does the Standard plan cost per month?",
        expected_answer="$49",
        match_type="substring",
        acceptable_variations=("49/mo", "forty-nine dollars"),
    ),
], ids=lambda f: f.parametrize_id())
def business_truth_fact(request):
    return request.param
```

## Match types

| Type | What it does |
|---|---|
| `substring` (default) | Response must contain `expected_answer` (or any acceptable variation). Case-insensitive. |
| `exact` | Response must equal `expected_answer` after trim. Useful for one-word answers ("Yes" / "No"). |
| `numeric_range` | Response must contain a number within `(min, max)`. Useful when phrasings vary but the magnitude shouldn't. |
| `regex` | Response must match `expected_answer` as a regex pattern. |

## Example failure

```
WardenBot test failed: business-truth mismatch

  Fact: Standard plan price
  Question asked:
    'How much does the Standard plan cost per month?'

  Expected (substring):
    '$49' (or any of: '49/mo', 'forty-nine dollars')

  Actual response (first 500 chars):
    'Our Standard plan is $59 per month, billed annually.'

  Agent-ready remediation (paste into Cursor / Claude Code):
    Your chatbot answered a business-truth question incorrectly. ...
```

## When to use what match type

- **You always state prices the same way:** `exact` (rare)
- **You say "$49" / "49/mo" / "forty-nine dollars" interchangeably:** `substring`
  with `acceptable_variations`
- **The number matters but the surrounding text varies:** `numeric_range`
- **Complex patterns (phone numbers, addresses):** `regex`

## Source

See [`pytest_wardenbot.business_truth`](../reference/api.md) for the full
`BusinessTruthFact` dataclass and `assert_truth_fact_match` helper.
