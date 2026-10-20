# PyPI publication

The project is not on PyPI yet. The checked GitHub wheel and single-file release
remain the supported installation routes; do not assume an identically named
registry package is maintained by this project.

Before the first upload, create a PyPI account with two-factor authentication,
confirm that `shapediff` is available, and create a pending Trusted Publisher:
owner `IamAngusU`, repository `shapediff`, workflow `publish.yml`, environment
`pypi`. Reserve a different name in package metadata first if the name is taken.

The manual workflow builds the wheel and sdist, checks their metadata, tests
the source and installs the built wheel offline before an OIDC upload. It runs
only on a version tag matching package metadata. Protect the `pypi` environment
with a required reviewer and run it only for a reviewed immutable release tag.
The runner account must be able to start Actions; a mirror is not automatically
an authorized publisher. Configure the actual repository identity in PyPI.

[PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
