
## search_replace corruption on frontend components (hit 3x on 2026-06-04)
Several `search_replace` calls on `/app/frontend/src/components/**` reported "Edit was
successful" but actually appended the tail of the file AFTER `export default X;`, and in
one case silently reverted an earlier edit in the same file. Symptoms: a webpack
"Unterminated string constant / Unexpected token" pointing at the line right after the
export, or a runtime "<newProp> is not defined" because the component signature reverted
while the body kept the new reference.
Files affected: AdminCatalogueSync.js, CustomerPicker.js, CarCard.js.
Rule of thumb: after editing a .js component, VIEW the last ~10 lines (and the signature
if it was changed) before testing. For more than one edit in the same small file, rewrite
it with `create_file overwrite=true` instead of stacking search_replace calls.

## An empty env var is not a missing env var (2026-06-08)
`os.environ.get("X", "default")` returns `""` when X is set but empty, so the default never
fires. This is the standard failure mode of a templated deploy: Ansible/Docker write every
variable from their vars file whether it was filled in or not. It cost a whole feature
(container tracking) in production while preview worked, because preview's .env happened to have
the value spelled out. When reading config that has a meaningful default, treat empty as absent:
`(os.environ.get(name) or "").strip() or fallback`. In Jinja, `default(x)` is NOT enough either —
it only fires on undefined; use `default(x, true)`.
Also: never cache a failure caused by our own configuration. The moment it is corrected the
answer changes, and a stale error row makes a working fix look broken.

## The workspace is not the server (2026-06-08)
A bug report about encareurope.com is a report about the LAST DEPLOYED commit, not about the
code in /app. Fixing /app changes nothing in production until the owner pushes ("Save to
GitHub") and runs the Ansible playbooks. State that explicitly in the same message as the fix,
or the owner tests the old build, reports "still broken", and both sides start hunting a second
bug that does not exist.

## Never hide a health line behind "is it configured"
`{quota?.configured && <line/>}` meant that the ONE case where the operator needed a message —
no key at all — displayed nothing. A missing integration must announce itself louder than a
working one, not more quietly.

## One flag must not carry two facts (2026-06-08)
`configured: false` meant both "no integration" and "found nothing", so a working provider
reported itself as unconfigured and the UI told the owner to add credentials for a service he
does not use. When a check is named `is_configured()`, it must cover every provider that can
satisfy the feature — not the one that happened to be written first. And when a helper returns
None for three different reasons, give it somewhere to say which.

## The quota counter as a diagnostic
A metered third-party API is a witness: if the counter does not move while the user is loading
the page, their server never called it. That single number separated "the key is wrong" from
"the key never reached the process" faster than any log would have.

## Never send parallel edits to the SAME file (2026-06-08)
Five parallel `search_replace` calls on one test file silently clobbered each other: every call
reported success, but only some of the changes survived, and the result was a NameError for a
constant I had "definitely added". Parallel tool calls are for INDEPENDENT targets. Two edits to
one file are not independent — batch them into one call or run them in sequence.

## Check the browser binary before suspecting the payment code
20 deposit tests ERRORed with "Executable doesn't exist at /pw-browsers/...". That is
`python -m playwright install chromium`, not a bug in Stripe handling. Also: those tests drive
Stripe's real hosted page and time out under two xdist workers, so verify them in isolation
before calling a failure a regression.

## Prove the CLIENT calls it, not just that the endpoint works (2026-06-08)
A counter pinged fire-and-forget with `.catch(() => {})` cannot report its own failure. Testing
the endpoint with curl and pytest proves the server counts; it proves nothing about whether the
app ever asks. Verify from a real browser with a network listener, and as the right kind of
visitor — an admin session proved nothing here, because admin views are deliberately excluded.
Doing that immediately exposed a wrong label separator that no server-side test could have seen.
