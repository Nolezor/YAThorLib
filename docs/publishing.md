# Publishing YAThorLib

The release workflow `.github/workflows/publish.yml` publishes the wheel and source distribution using PyPI Trusted Publishing. No API token is stored in GitHub. It runs tests, validates metadata, checks archive contents, and requires the release tag to match `pyproject.toml`.

## One-time account setup

1. Log in to PyPI with a verified account and two-factor authentication.
2. Open https://pypi.org/manage/account/publishing/ and add a pending GitHub publisher:

   | Field | Value |
   | --- | --- |
   | PyPI project name | `yathorlib` |
   | GitHub owner | `Nolezor` |
   | Repository | `YAThorLib` |
   | Workflow filename | `publish.yml` |
   | Environment | `pypi` |

3. In `Nolezor/YAThorLib` → Settings → Environments, create `pypi`. Optional required reviewers can control release approval.
4. Ensure the library source, metadata, README, LICENSE, MANIFEST.in, tests, `tools/check_dist.py`, documentation and workflows are on GitHub. The repository also tracks vendor binaries and research inputs; these are not needed for publishing and MANIFEST.in excludes them from the distributions. The MIT license applies to YAThorLib code, not third-party research inputs.

If the PyPI project already exists under your account, add the same publisher under that project's Publishing settings instead. A missing project page does not guarantee PyPI will accept the name.

## Release 0.1.0

Build and validate locally:

```sh
.venv313/bin/python -m pip install '.[dev,release]'
.venv313/bin/python -m build
.venv313/bin/python -m twine check --strict dist/*
.venv313/bin/python tools/check_dist.py
```

Use a clean `dist/` for each release; `check_dist.py` rejects mixed releases. On GitHub, create and publish a release tagged `v0.1.0` at the commit containing the publishing workflow. This triggers the upload. Use release notes that describe the experimental status and lack of physical-device qualification.

Watch the **Publish to PyPI** workflow. Once it succeeds, verify https://pypi.org/project/yathorlib/0.1.0/ and install in a fresh Python 3.13+ environment:

```sh
python -m pip install yathorlib==0.1.0
python -c 'import yathorlib; print(yathorlib.__version__)'
```

For later releases, update both `pyproject.toml` and `src/yathorlib/__init__.py`, commit, and publish the matching `vVERSION` release. PyPI does not allow replacing an uploaded distribution with a different file under the same filename.

References: [PyPI pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/), [using Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/).
