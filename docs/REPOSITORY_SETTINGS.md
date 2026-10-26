# Repository settings

The workflows enforce read-only pull-request checks and read-only Windows builds.
Only the separate draft-release job receives contents write access. The source
and existing published downloads are independent of the following admin settings.

An owner should check these switches in GitHub:

- **Rules ? Rulesets:** protect main against deletion and force pushes. Require
  **Windows checks** after its first passing run. A solo maintainer does not need
  to require another reviewer's approval.
- **Actions ? General:** choose read-only default workflow permissions, require
  approval for all external contributors' workflows, and leave workflow creation
  or approval of pull requests disabled. Explicit release-job permissions remain
  scoped to publishing.
- **Security / Advanced Security:** enable Dependabot alerts, verify secret
  scanning and push protection, and enable private vulnerability reporting.
- **General ? Pull Requests:** enable automatic deletion of merged branches.
  Squash merging is the suggested default.
- **General ? Features:** Discussions is optional for questions and ideas.

The repository connector cannot apply these admin switches. Their current state
should be checked in the owner's signed-in GitHub settings. Normal CI runs do not
have permission to change them.
