---
description: Run promptfoo prompt security evaluation and summarise results
---

Run `make eval`. It makes real model calls billed to `GOOGLE_CLOUD_PROJECT` and needs
Application Default Credentials. If it stops with missing settings, report them and suggest
`make eval-check`, which checks the suite without any model call. After it completes:

1. Report the overall pass rate (e.g. "9/10 tests passed — 90%")
2. List any failing tests by name with their actual output vs expected
3. If below the threshold in `tests/evals/promptfoo.yaml`, suggest which prompt file to edit to fix the failure
4. If cases "could not be graded", say the grader could not log in or hit quota: that is not an agent failure
5. If promptfoo is not installed, it will be fetched via npx automatically
