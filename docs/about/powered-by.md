# Powered by WardenBot AI

`pytest-wardenbot` is maintained by [WardenBot AI](https://wardenbot.ai), which
offers security audits and continuous monitoring for AI chatbots and agents.
Current services and prices are on
[wardenbot.ai](https://wardenbot.ai/); this page only explains how the
plugin relates to them.

## How this plugin relates

The plugin is the free, open-source slice of that work: the same kinds of
checks, run in your own pytest suite and CI against your own systems. Nothing
in the plugin calls WardenBot AI's services or sends data to them.

The managed service adds what a test suite in CI can't: scheduled runs
against deployed systems, history across runs, alerts on regressions and
reports for security and compliance reviews.

## Why it's open source

- **You can inspect every check before trusting it.** Every prompt the
  plugin sends, every grader and every scenario is in this repository, and
  the graders' measured accuracy is published on the
  [grading accuracy](../reference/grading-accuracy.md) page.
- **It's useful on its own.** A team running pytest in CI gets a real
  regression gate without any subscription.

## Want it run continuously?

[Tell us about your setup](https://wardenbot.ai/intake/).
