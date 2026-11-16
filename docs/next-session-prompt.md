Session V1 is closing round 4. Its release commit (0.32.1) is followed in the same chat by
`docs: close round 4`, then the owner's `/code-review high` over the release commit, the review
commit, the release checks again, the readiness report in the chat, and the `v0.32.1` tag the owner
approves. The close rewrites this file for the next intake.

## State you need that is not in the specs

- **V1's done-note** is in `docs/spec/SESSIONS.md` at the release commit, with the release checks
  run on its tree.
- **0.32.1 is installed and live.** Krita was restarted at 0 unsaved, and the owner's MCP client
  needs its own restart to pick up the server.
- **Push status:** `origin/main` holds everything through L1's review commit. The release commit
  waits for an approved push; list `origin/main..HEAD` before it.

## Watch for

- **Nothing private in any file or commit message.** Draft the message into
  `"$(git rev-parse --git-dir)/COMMIT_DRAFT"`, run `verify` with it, commit with `git commit -F`,
  then delete the draft.
- **A tag is not a push.** The tag and the repository's visibility each need their own approval.
