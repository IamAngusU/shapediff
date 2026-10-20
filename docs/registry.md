# PyPI publication

Publishing uses PyPI Trusted Publishing, without a stored PyPI token. The exact
publisher identity is:

- GitHub owner: `angusu-de`
- Repository: `shapediff-ci`
- Workflow filename: `publish.yml`
- Environment: `pypi`
- PyPI project: `shapediff`

The public mirror runs the workflow because the canonical account's runners
cannot currently start. Canonical product source remains `IamAngusU/shapediff`.
The `pypi` environment permits only workflow runs from `main`.

Dispatch `Publish reviewed PyPI release` on `main` with an existing canonical
GitHub release tag. With `publish=false`, it verifies without uploading. With
`publish=true`, it uploads after verification through OIDC.

Verification checks the tag against package metadata and the canonical Git ref,
downloads the exact wheel and sdist from that GitHub release, checks their
published SHA-256 hashes and compares packaged Python code with the tagged
source. It then runs the source tests, validates package metadata and installs
the wheel offline into a fresh environment. The exact checked release files
are uploaded; they are not rebuilt into different artifacts for PyPI.

A pending publisher must be configured in the owning PyPI account before the
first upload. Once used, it becomes the project's ordinary trusted publisher.
The configuration permits future releases of this project through that same
workflow and environment; remove it in PyPI to revoke the relationship.

[PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
