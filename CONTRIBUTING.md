# Contributing

Thanks for your interest. This project is primarily a portfolio / demo, but
patches are welcome.

## Issues

File a [GitHub issue](https://github.com/<TBD>/issues/new) with:
- What you tried (commands, expected output)
- What happened (full error / log excerpt)
- Your environment (OS, Python version, Node version)

## Pull requests

1. Fork the repo, create a feature branch from `main`
2. Run before submitting:
   ```bash
   cd backend && pytest tests/ && mypy app --strict --ignore-missing-imports
   cd ../frontend && npx vue-tsc --noEmit
   ```
3. Keep PRs focused — one feature or fix at a time
4. Add tests for new behavior
5. Use conventional commit prefixes when natural: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`

## Code style

- Python: PEP 8 + 100% type hints + Google-style docstrings on public symbols
- TypeScript: explicit types preferred; no `any` without justification
- Vue: `<script setup lang="ts">` SFCs only

## License

By contributing you agree your contribution will be released under the project's MIT license.
