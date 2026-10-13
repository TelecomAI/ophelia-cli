# Contributing to Ophelia

Thank you for your interest in contributing to **Ophelia CLI**, an AI coding assistant developed within the Telecom AI community.

Ophelia is first and foremost a learning project. Our goal is not only to build a useful coding assistant, but also to understand how AI agents work, experiment with new approaches, and share knowledge within the community.

Every contribution should help us build better software and deepen our understanding of the technologies behind it.

## Table of Contents

- [Who Can Contribute?](#who-can-contribute)
- [Join the Community](#join-the-community)
- [Getting Started](#getting-started)
- [Working on an Issue](#working-on-an-issue)
- [Development Workflow](#development-workflow)
- [Code Quality Guidelines](#code-quality-guidelines)
- [AI-Assisted Development](#ai-assisted-development)
- [Backend and Agent Documentation](#backend-and-agent-documentation)
- [Pull Request Guidelines](#pull-request-guidelines)
- [Security and Responsible Development](#security-and-responsible-development)
- [Need Help?](#need-help)

## Who Can Contribute?

Contributions to the repository are currently restricted to authorized repository developers.

To become a developer, you must be a **Télécom Paris student** with an institutional email address ending in `@telecom-paris.fr`.

If you meet these requirements, you can join the development team in either of the following ways:

- **Contact us:** Send an email to [contact@telecom-ia.fr](mailto:contact@telecom-ia.fr).
- **Register online:** Visit the [Telecom AI website](https://telecom-ia.fr/) to register.

Once your eligibility has been confirmed, the team will guide you through obtaining the necessary repository access.

Please do not start implementing an issue before you have the required access and the issue has been assigned to you.

## Join the Community

Join the [Telecom AI Discord community](https://discord.gg/eWtE472wVr) to meet other contributors, discuss ideas, ask questions, and follow the project's development.

Discord is the primary place to exchange ideas and get help from the team.

We encourage you to participate in discussions, share what you learn, and help other contributors whenever possible.

## Getting Started

Once you have repository access, set up your local development environment.

### Prerequisites

- Python 3.12 or later
- [UV](https://docs.astral.sh/uv/getting-started/installation/)
- Git

### Set up the project

Clone the repository:

```bash
git clone https://github.com/TelecomAI/ophelia-cli.git
cd ophelia-cli
```

Install the dependencies:

```bash
uv sync
```

Run the CLI:

```bash
uv run ophelia
```

Run the tests and code-quality checks before making changes:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

If a command fails because of an existing issue or incomplete implementation, document the problem and notify the team rather than silently ignoring it.

## Working on an Issue

**Every contribution must be associated with an issue assigned to you.**

We use GitHub Issues to organize development, track decisions, and avoid duplicated work.

### 1. Find an issue

Browse the [open issues](https://github.com/TelecomAI/ophelia-cli/issues) and identify something you would like to work on.

Read the issue carefully, including its description, acceptance criteria, comments, and any linked documentation.

### 2. Request assignment

Discuss the issue with the team and ask to be assigned to it.

We will assign issues based on your interests, the project's priorities, and the current development workload.

Do not begin substantial implementation until the assignment is confirmed.

### 3. Understand the problem

Before writing code:

- Make sure you understand the problem and the expected behavior.
- Identify the relevant modules and existing implementation.
- Review related issues, documentation, and previous decisions.
- Ask questions if something is unclear.
- Propose an approach when the implementation involves significant architectural decisions.

The objective is to solve the problem, not simply to produce a working patch as quickly as possible.

### 4. Keep the issue updated

Communicate your progress in the issue or its associated discussion.

If you discover that the issue is more complex than expected, encounter a blocker, or need to change your approach, let the team know.

If you can no longer work on an assigned issue, notify the team as early as possible so it can be reassigned.

## Development Workflow

We follow a lightweight Git workflow designed to keep contributions easy to review.

### 1. Create a branch

Create a dedicated branch for each issue. Do not commit directly to the main branch.

Use descriptive branch names:

```text
feat/42-add-conversation-history
fix/57-handle-tool-errors
docs/63-document-agent-context
refactor/71-simplify-agent-graph
test/85-add-agent-tests
```

The numbers correspond to GitHub issue numbers.

### 2. Make focused commits

Keep commits small, coherent, and easy to understand.

We recommend conventional commit prefixes:

```text
feat: add conversation history
fix: handle tool execution errors
docs: explain context management
refactor: simplify agent state handling
test: cover prompt construction
chore: update development dependencies
```

Each commit should represent a meaningful change. Avoid unrelated modifications in the same commit.

### 3. Keep your branch up to date

Before opening a pull request, synchronize your branch with the current dev branch using the team's preferred Git workflow.

Resolve conflicts carefully and verify that your changes still work afterward.


### 4. Test your changes

Run the relevant tests and checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Add or update tests whenever behavior changes.

If a test cannot be run, explain why in your pull request.

### 5. Open a pull request

Push your branch and open a pull request against `dev`.

Link the associated issue using GitHub keywords when appropriate, for example:

```text
Closes #42
```

A pull request should explain the problem, the proposed solution, and how the change was verified.

Wait for review and approval before merging. Address review feedback constructively and keep the discussion focused on improving the implementation.

## Code Quality Guidelines

We aim to maintain a codebase that is readable, testable, and easy to learn from.

### General principles

- Prefer simple, explicit solutions over unnecessary abstractions.
- Follow existing project conventions unless there is a good reason to change them.
- Use meaningful names for variables, functions, classes, and modules.
- Add type hints to public functions and important interfaces.
- Write docstrings for non-obvious or important behavior.
- Handle errors explicitly and provide useful error messages.
- Avoid duplicated logic when a clear shared abstraction is justified.
- Keep functions and modules focused on a well-defined responsibility.
- Do not introduce dependencies without a clear reason.
- Never commit credentials, secrets, private user data, or generated artifacts that do not belong in the repository.

### Testing

Tests are part of the implementation, not an optional final step.

Depending on the change, add tests for:

- Expected behavior and normal execution.
- Invalid inputs and error handling.
- Edge cases and boundary conditions.
- Agent state transitions and tool execution.
- Regression scenarios for previously reported bugs.

Tests should be deterministic whenever possible. Mock external services when appropriate instead of relying on live API calls.

## AI-Assisted Development

**AI-assisted development is welcome. Understanding your contribution is mandatory.**

You may use AI coding assistants to explore the codebase, understand unfamiliar concepts, generate ideas, draft implementations, or help write tests and documentation.

However, Ophelia is also a learning project. Using AI to generate code that you cannot explain defeats one of the project's primary objectives.

Every contributor is responsible for the code they submit, regardless of how it was produced.

Before submitting AI-assisted work, you must be able to:

- Explain what the code does and why it is necessary.
- Justify the main implementation and design decisions.
- Understand the important functions, data structures, and dependencies involved.
- Explain relevant failure modes, limitations, and security implications.
- Modify or debug the implementation without blindly relying on generated suggestions.
- Verify the implementation through appropriate tests and code review.

AI-generated code must be reviewed, tested, and adapted to the project's architecture. Do not blindly accept suggestions, fabricated API references, or undocumented dependencies.

When AI assistance is used for a substantial or non-trivial change, briefly disclose it in the pull request and explain what assistance was used and how the result was verified. Routine use of autocomplete does not need to be reported.

During code review, contributors may be asked to walk through their implementation and explain their reasoning. This is a normal part of our learning process, not a punishment for using AI.

## Backend and Agent Documentation

Changes to the backend require particular care because Ophelia's behavior depends on several interacting components.

Pull requests involving any of the following must include meaningful technical documentation:

- Agent behavior and orchestration.
- LangChain or LangGraph workflows.
- State management and context handling.
- Prompt design, system instructions, and prompt construction.
- Memory, conversation history, and context compression.
- Tool definitions, tool execution, and error handling.
- Model selection, model integrations, and configuration.
- Safety constraints and permissions for code execution or file modification.

### What the documentation should explain

For a non-trivial backend change, document:

1. **Motivation:** What problem are you solving, and why is the change necessary?
2. **Previous behavior:** How did the system work before the change?
3. **New behavior:** What changed, and how does the new implementation work?
4. **Design decisions:** What alternatives did you consider, and why did you choose this approach?
5. **References:** Which official documentation, technical articles, research papers, or other reliable sources informed your implementation?
6. **Validation:** What tests or experiments demonstrate that the change works?
7. **Limitations:** What trade-offs, unresolved problems, or potential regressions remain?

Include links to the documentation and references that helped you understand or implement the change. Explain how those references apply rather than simply listing links.

For example, a change to LangGraph state management should explain the relevant state transitions and link to the applicable LangGraph documentation. A prompt modification should explain the intended behavioral effect and how it was evaluated.

Documentation may live in the pull request description, relevant code docstrings, or a dedicated document in the repository, depending on the scope of the change.

The goal is to make important decisions understandable and reusable by the next contributor.

## Pull Request Guidelines

Before requesting a review, make sure your pull request meets the following requirements:

- [ ] It is linked to an assigned GitHub issue.
- [ ] Its title clearly describes the change.
- [ ] Its description explains the motivation and implementation.
- [ ] The change is focused and does not include unrelated modifications.
- [ ] Relevant tests have been added or updated.
- [ ] Tests and code-quality checks have been run, with failures explained.
- [ ] Backend or agent changes include the required technical documentation and references.
- [ ] AI assistance used for substantial work has been disclosed.
- [ ] No secrets, credentials, or sensitive information have been committed.
- [ ] Known limitations and follow-up work are documented.

Keep pull requests reasonably small when possible. If a change is large, consider splitting it into smaller, independently reviewable steps.

Be respectful when reviewing or discussing code. Critique implementations and decisions, not people. Explain requested changes and be open to alternative solutions.

## Security and Responsible Development

Ophelia interacts with codebases, tools, models, and potentially sensitive information. Changes affecting these areas must be reviewed with security in mind.

- Do not hardcode API keys or credentials.
- Do not execute untrusted commands or modify files without respecting the application's permission model.
- Treat model output and repository content as potentially untrusted input.
- Consider prompt injection, unintended tool execution, and unintended data disclosure when modifying agent behavior.
- Do not send private code or sensitive information to external AI services without authorization.
- Report security vulnerabilities privately to the project maintainers rather than publishing exploit details in a public issue.

Security-related changes should include tests or a clear explanation of how the relevant risk is mitigated.

## Need Help?

If you have questions, need clarification, or are blocked:

- Join the [Telecom AI Discord community](https://discord.gg/eWtE472wVr).
- Discuss the issue with the team.
- Email [contact@telecom-ia.fr](mailto:contact@telecom-ia.fr) if you need help joining the development team.

We would rather you ask questions early than spend hours implementing something based on an incorrect assumption.

Thank you for helping us build Ophelia and learn together!
