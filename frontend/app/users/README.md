# Mock Public Routes

`app/users/...` is a Phase 5 mock-only surface for local acceptance of
`publicUrl` paths opened from the authoring workspace.

Real published pages should continue to be generated as static site artifacts
outside the Next.js authoring app. Remove these routes when the real static
publish pipeline owns `/users/{userSlug}/...`.
