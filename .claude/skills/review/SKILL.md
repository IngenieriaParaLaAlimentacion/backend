---
name: review
description: Reviews code for correctness, guardrail violations, layer discipline, naming conventions, and code clarity. Use when asked to review a file, a set of files, a feature, or any code change — even if the user just says "check this", "look at this", "what do you think of this code" or "suggest any improvements".
---

## Process
1. Review every file in scope. Do not skip files because they look simple but don't read more than necessary either.
2. Produce a structured report grouped by file.

## Report format
For each finding include:
- Location (file + line or function name)
- What the problem is
- How to fix it (concrete suggestion or corrected snippet)

## What to check — in order of priority
1. **Security violations**
2. **Layer violations** — router calling repository directly, service touching DB driver, HTTPException raised outside router
3. **Naming** — files, classes, schemas, repositories, services must follow docs/conventions.md exactly
4. **Schema discipline** — no ORM model returned directly from an endpoint
5. **Exception handling** — domain exceptions in services, HTTP mapping only in routers/handlers
6. **Endpoint documentation** — every endpoint must declare explicit `responses` for all possible status codes
7. **Code clarity** — flag anything that could be simplified, deduplicated, or made more readable
8. **Test coverage** — if tests exist, check they cover edge cases and failure paths

## Important
- Do not skip naming or clarity issues because they seem minor. Flag everything.
- If a pattern repeats across files, mention it once and note all locations.
- Do not auto-fix. Report only, unless explicitly asked to fix.