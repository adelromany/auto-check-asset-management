# 08 — Git Branches Principles

- GIT-01 Never commit to `main` or `feature/sso`. Never force-push. Never rewrite pushed history. Never merge branches (the owner merges).
- GIT-02 One concern per branch. Names: `feature/<name>`, `refactor/<name>`, `fix/<bug>`, `test/<name>`, `docs/<name>`, `chore/<name>`. Lowercase, hyphens.
- GIT-03 Historical implementation branches are listed in the project log; follow-up work starts from the verified prior tip and stays off `main`. This gap-fix run uses `fix/software-verification` as its integration branch.
- GIT-04 Commits follow Conventional Commits: `feat(scope): …`, `fix(scope): …`, `refactor(scope): …`, `test(scope): …`, `docs(scope): …`, `chore(scope): …`. Subject ≤ 72 characters, imperative, no trailing period.
- GIT-05 One logical change per commit; the suite is green at every commit. Do not mix refactoring and behavior change in one commit.
- GIT-06 Never commit: `.env`, `data/`, `*.db`, uploaded documents, `deploy/snipeit-dev/.env`, `node_modules/`. Generated `static/css/app.css` IS committed (the Python app deploys without Node).
- GIT-07 Line endings: `.gitattributes` enforces LF. Do not commit mass line-ending changes together with real changes.
- GIT-08 Before each commit: run the suite, run `git status`, review `git diff --staged` for secrets and unrelated edits.
- GIT-09 Integration into `feature/sso` happens by the owner, in order, after review.
