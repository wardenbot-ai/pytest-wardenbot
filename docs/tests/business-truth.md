# Business truth

Checks your chatbot's answers against configured facts about pricing, hours,
refund policy and contact information. These are lexical regression checks;
their meaning depends on the matcher you choose.

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
| `numeric_range` | Exactly one distinct extracted number must be within `(min, max)`. Use `numeric_pattern` to select the relevant value when the answer contains several numbers. |
| `regex` | Response must match `expected_answer` as a regex pattern. |

Substring matching does not understand negation: `"The price is not $49"`
contains `$49` and passes that substring check. Regex checks have the same
limitation unless your pattern rules it out. For a constrained answer, ask for
only the price and use `exact`. For free-form meaning or contradictions, use a
[semantic judge](semantic.md) with an explicit rubric and review its limitations.

### Extract the relevant number

An answer such as `"The price is $99; your account number is 49"` must not pass a
price check for 49. Numeric matching rejects multiple distinct extracted values.
Repeated mentions of the same value are allowed. Numbers are parsed as whole
tokens, including signs, decimals, thousands separators and scientific notation.

When legitimate answers contain other numbers, select the value explicitly:

```python
BusinessTruthFact(
    label="Standard plan price",
    question="State 'The price is $N' followed by the billing period.",
    expected_answer="49",
    match_type="numeric_range",
    numeric_range=(49, 49),
    numeric_pattern=r"price is \$(?P<value>\d+(?:\.\d+)?)\b",
)
```

The pattern needs a named `value` group containing a complete number. No match,
invalid numbers or multiple distinct selected values fail. Bounds must be
finite. The pattern is your extraction rule; it still does not infer whether
the surrounding sentence affirms or denies the value.

**Migration:** earlier releases accepted any in-range number anywhere in the
answer. Checks that depended on that permissive behavior should use a scoped
`numeric_pattern` or a more appropriate matcher.

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
- **One number matters but the surrounding text varies:** `numeric_range`, with
  `numeric_pattern` when other numbers can appear
- **Complex patterns (phone numbers, addresses):** `regex`

## Source

See [`pytest_wardenbot.business_truth`](../reference/api.md) for the full
`BusinessTruthFact` dataclass and `assert_truth_fact_match` helper.
