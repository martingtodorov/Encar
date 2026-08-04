
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
