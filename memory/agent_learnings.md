
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
