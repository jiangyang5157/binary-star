# Changelog

All notable changes to Singularity will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Calendar Versioning](https://calver.org/) (`YY.MM.DD`).

## [26.6.21] — Work in Progress

### Added
- Project versioning infrastructure (version stamp in session/audit JSON,
  `--version` CLI flag)
- `CHANGELOG.md` (this file)
- Runtime `__version__` and `__git_commit__` accessible via
  `import singularity; singularity.__version__`

### Changed
- `pyproject.toml` version reset from `7.1.0` to `26.6.21` (CalVer, aligns with
  branch naming `v26.6.21`)
- `version_control` block in session JSON now includes `project_version` and
  `git_commit`
- Audit output `metadata` now includes `project_version` and `git_commit`

## [Historical — pre-26.6.21]

Versions prior to 26.6.21 did not have structured changelogs or runtime
version tracking. See git history for details.
