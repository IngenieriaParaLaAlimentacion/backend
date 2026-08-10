---
name: user-story
description: Transforms the knowledge gained during the current session into a formal user story in Spanish — título, a "Como ___, quiero ___, para ___" descripción, and numbered criterios de aceptación. Use when the user asks to write a user story, turn this session/feature/discussion into a user story, or says things like "write this up as a user story", "generate a user story for what we just did", "escribí esto como user story", or "/user-story".
---

# Session-to-User-Story

Turn what was actually discussed or built in this session into a single, well-formed user story. Do not invent scope that wasn't part of the session.

## Process

1. **Review the session**, not just the last message. Identify:
   - The actor/role who benefits (end user, admin, field worker, analyst, developer, etc. — infer from context; ask if genuinely ambiguous).
   - The concrete capability or change delivered or discussed.
   - The underlying motivation — why it matters, what problem it solves.
   - Any constraints, edge cases, or explicit requirements that surfaced during the session (these become acceptance criteria).

2. **If the session covered multiple unrelated features**, ask the user which one to turn into a story, or produce one story per 
feature if they ask for all of them — don't merge unrelated work into a single story.

3. **Write the story** using the exact format below, in spanish. 
Keep it concrete and grounded in what was actually said or done — no filler, no speculative scope.

## Output format

```markdown
## Título
<Short, action-oriented title (max ~8 words)>

## Descripción
Como <role>, quiero <capability/goal>, para <reason/benefit>.

## Criterios de Aceptación
**CA 1**:
- [ ] a specific testable condition
- [ ] another specific testable condition
**CA 2**:
- [ ] a specific testable condition
...
```

## Rules

- **Title**: imperative or noun-phrase, no punctuation at the end. E.g. "Idempotent measurement upload endpoint".
- **Description**: exactly one sentence in the "As a ___, I want ___, for ___" shape. Pick the role/s that most directly benefits from the capability 
— not "the system" or "the developer" unless the story is genuinely about tooling for that audience.
- **Acceptance Criteria**: bullet list, each item independently testable (pass/fail), phrased as observable behavior — not implementation detail. 
Pull these from constraints, edge cases, and requirements that came up during the session (error handling, validation rules, permission checks, specific responses, etc.). 
Include negative/edge cases if they were discussed (e.g. "returns 409 when X already exists").
- Do not add acceptance criteria for behavior that wasn't discussed or implied by the session — no speculative hardening.
- If the session left something genuinely unresolved (e.g. an open question about behavior), note it as a `> Open question:` 
line under Acceptance Criteria rather than guessing.
