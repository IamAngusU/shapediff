# PyPI publication

The project is published on [PyPI](https://pypi.org/project/shapediff/0.1.0a4/)
and owned by `iamangusu`. Install the current alpha explicitly with
`pipx install shapediff==0.1.0a4` or, inside a virtual environment,
`python -m pip install shapediff==0.1.0a4`.

Publishing uses PyPI Trusted Publishing, without a stored PyPI token. The exact
publisher identity is:

- GitHub owner: `angusu-de`
- Repository: `shapediff-ci`
- Workflow filename: `publish.yml`
- Environment: `pypi`
- PyPI project: `shapediff`

The public mirror runs the workflow; canonical product source remains
`IamAngusU/shapediff`. [Runner account context](https://github.com/IamAngusU/IamAngusU/blob/main/ci.md)
is maintained centrally. The `pypi` environment permits only workflow runs from `main`.

Dispatch `Publish reviewed PyPI release` on `main` with an existing canonical
GitHub release tag. With `publish=false`, it verifies without uploading. With
`publish=true`, it uploads after verification through OIDC.

Verification checks the tag against package metadata and the canonical Git ref,
downloads the exact wheel and sdist from that GitHub release, checks their
published SHA-256 hashes and compares packaged Python code with the tagged
source. It then runs the source tests, validates package metadata and installs
the wheel offline into a fresh environment. The exact checked release files
are uploaded; they are not rebuilt into different artifacts for PyPI.

The publisher was configured and first used for `0.1.0a4` on 2026-10-20.
The [successful publication run](https://github.com/angusu-de/shapediff-ci/actions/runs/39367983642)
uploaded the existing GitHub release files. Their SHA-256 digests in the public
PyPI JSON API match the GitHub release checksums:

```text
shapediff-0.1.0a4-py3-none-any.whl  d2acd9db86a8252e2a49d544be1ceaebb54c588e9ce7afae490a4f0af1cd8dfa
shapediff-0.1.0a4.tar.gz            21c4b44360269ca00ba5e3caffc05fee4956c93292e544654757fc2c8ef88c73
```

The configuration permits future releases of this project through the same
workflow and environment. Remove the trusted publisher in PyPI to revoke it.

[PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
