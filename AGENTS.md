# Repository Guidelines

## Project Overview

This repository contains a small Flask application for previewing Mermaid diagrams and README files. Keep the implementation simple, dependency-light, and easy to maintain. Do not introduce frontend frameworks, a database, authentication, or editing capabilities unless explicitly requested.

## Architecture

- `app.py` contains the Flask application and filesystem APIs.
- `templates/index.html` contains the single-page HTML structure.
- `static/app.js` contains all client-side behavior.
- `static/style.css` contains the dark theme and responsive layout.
- `static/vendor/` contains pinned browser bundles served locally.
- `tests/test_app.py` contains the backend test suite.
- Mermaid and README files must remain stored only inside the configured data directory.

## Development Rules

- Preserve support for Python 3.12+ and the Docker workflow.
- Prefer standard library features and vanilla JavaScript over new dependencies.
- Keep filesystem path validation centralized and apply it to every read, write, rename, or delete operation.
- Reject path traversal, absolute paths, unsupported files, invalid UTF-8, and symbolic links.
- Never add an editor for Mermaid or Markdown unless explicitly requested.
- Keep browser dependencies pinned and served locally so runtime use does not require internet access.
- Update the README and tests whenever public behavior or APIs change.

## Validation

Run the checks relevant to the change before considering it complete:

```bash
node --check static/app.js
python -m unittest discover -s tests -v
docker compose config
docker compose build
```

When the host does not have the Python dependencies installed, run the tests inside the built image:

```bash
docker run --rm -v "$PWD/tests:/app/tests:ro" mmd-preview-app python -m unittest discover -s tests -v
```

## Commit Discipline

- After each coherent change has been implemented and its relevant checks pass, create a Git commit before starting the next change.
- Keep commits focused on one behavior or fix and include related tests and documentation in the same commit.
- Use concise Conventional Commit messages, such as `feat: add folder deletion` or `fix: hide loading state after rendering`.
- Do not commit generated caches, local data, virtual environments, secrets, or unrelated user changes.
- Do not amend, squash, rebase, force-push, or otherwise rewrite existing commits unless explicitly requested.
