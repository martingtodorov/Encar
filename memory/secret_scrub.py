"""One-off: take the real secrets out of tracked files.

The admin master token, the owner's password and the seeded admin password were hardcoded
in test files and quoted in test reports, so they travelled to GitHub with the repo. Tests
now read them from the environment (conftest already loads backend/.env); the reports and the
Ansible example get placeholders. Rotation is still the real fix — a value that has been
pushed once is public forever.
"""
import glob
import os
import re

TOKEN = "kR7wZq2mXv9TbNp4LdYs6HcJf1UgE3aQ"
SEED_PW = "AdminTest2026!"
OWNER_PW = "Nero"

ENV_READS = {
    "ADMIN_TOKEN": 'os.environ.get("ADMIN_TOKEN", "")',
    "ADMIN_PASSWORD": 'os.environ.get("ADMIN_SEED_PASSWORD", "")',
    "ADMIN_PASS": 'os.environ.get("ADMIN_SEED_PASSWORD", "")',
    "OWNER_PASSWORD": 'os.environ.get("OWNER_PASSWORD", "")',
}

changed = []
for path in glob.glob("/app/backend/tests/*.py"):
    src = open(path).read()
    out = src
    for name, expr in ENV_READS.items():
        out = re.sub(rf'^{name} = "[^"]*"$', f"{name} = {expr}", out, flags=re.M)
    if out != src and "import os" not in out:
        out = out.replace("import pytest", "import os\nimport pytest", 1)
    if out != src:
        open(path, "w").write(out)
        changed.append(path)

# Reports are history, not config: the value itself is what has to go.
for path in glob.glob("/app/test_reports/*.json") + ["/app/test_result.md", "/app/plan.md"]:
    if not os.path.exists(path):
        continue
    src = open(path).read()
    out = (src.replace(TOKEN, "<ADMIN_TOKEN from backend/.env>")
              .replace(SEED_PW, "<ADMIN_SEED_PASSWORD from backend/.env>")
              .replace(f"/ {OWNER_PW}", "/ <OWNER_PASSWORD from backend/.env>")
              .replace(f"'{OWNER_PW}'", "'<OWNER_PASSWORD>'"))
    if out != src:
        open(path, "w").write(out)
        changed.append(path)

print("\n".join(changed) or "nothing changed")
