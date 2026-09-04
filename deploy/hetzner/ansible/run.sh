#!/usr/bin/env bash
# Run any playbook in this directory THROUGH THIS SCRIPT when your control machine is a Mac.
#
#   ./run.sh playbooks/deploy_nat.yml
#   ./run.sh playbooks/deploy_backend.yml --tags config,service
#
# Why it exists: on macOS an Ansible run can stop dead in the middle of a task with no error,
# no failure and NO PLAY RECAP at all — most often on a package step, because those modules do
# the most work inside the forked worker. It is not the playbook and not the host. Apple's
# Objective-C runtime aborts a process that forks after certain frameworks have initialised,
# and Ansible forks one worker per host per task; the worker dies silently and the parent has
# nothing to report.
#
# Two environment variables cure it, and neither can be set from ansible.cfg:
#
#   OBJC_DISABLE_INITIALIZE_FORK_SAFETY  the abort itself
#   no_proxy='*'                         the same crash from the macOS proxy lookup in
#                                        forked children (urllib/SystemConfiguration)
#
# If a run still stops without a recap, take the forking out of the picture entirely:
#
#   ANSIBLE_STRATEGY=linear ./run.sh playbooks/deploy_nat.yml --forks 1 -vvv
#
# and watch which task it dies on. A real Ansible failure ALWAYS prints a recap; a missing
# recap means the process was killed, not that the task failed.
set -euo pipefail

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export no_proxy='*'
# Keep the interpreter from being clever about threads it inherited across the fork.
export PYTHONUNBUFFERED=1

cd "$(dirname "$0")"

if [ $# -eq 0 ]; then
  echo "usage: ./run.sh playbooks/<playbook>.yml [ansible-playbook options]" >&2
  exit 2
fi

exec ansible-playbook -i inventory.ini "$@"
