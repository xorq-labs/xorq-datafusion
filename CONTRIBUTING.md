## Contributing Guide

### Setting up a development environment

This assumes that you have rust and cargo installed. We use the workflow recommended by [pyo3](https://github.com/PyO3/pyo3) and [maturin](https://github.com/PyO3/maturin).

#### Using pip and venv

```bash
# fetch this repo
git clone git@github.com:xorq-labs/xorq-datafusion.git
# prepare development environment (used to build wheel / install in development)
python3 -m venv venv
# activate the venv
source venv/bin/activate
# update pip itself if necessary
python -m pip install -U pip
# install dependencies 
python -m pip install -r requirements-dev.txt
# set up the git hook scripts
pre-commit install
```

#### Using uv

This assumes you have uv installed, otherwise please follow these [instructions](https://docs.astral.sh/uv/getting-started/installation/).

```bash
# fetch this repo
git clone git@github.com:xorq-labs/xorq-datafusion.git
# set uv run command to not sync 
export UV_NO_SYNC=1
# prepare development environment and install dependencies
uv sync --all-extras --all-groups --no-install-project
# compile and install the rust extensions
uv run maturin develop --uv --release --strip
# activate the venv
source venv/bin/activate
# set up the git hook scripts
uv run pre-commit install
```

### Running the test suite

To test the code:
```bash
uv run pytest python/tests 
```

### Writing the commit

xorq-datafusion follows the [Conventional Commits](https://www.conventionalcommits.org/) structure.
In brief, the commit summary should look like:

    fix(types): make all floats doubles

The type (e.g. `fix`) can be:

- `fix`: A bug fix. Correlates with PATCH in SemVer
- `feat`: A new feature. Correlates with MINOR in SemVer
- `docs`: Documentation only changes
- `style`: Changes that do not affect the meaning of the code (white-space, formatting, missing semi-colons, etc)

If the commit fixes a GitHub issue, add something like this to the bottom of the description:

    fixes #4242


### Release Flow
***This section is intended for xorq-datafusion maintainers***

#### Steps
1. Ensure you're on upstream main: `git switch main && git pull`
2. Compute the new version number (`$version_number`) according to [Semantic Versioning](https://semver.org/) rules.
3. Create a branch that starts from the upstream main: `git switch --create=release-$version_number`
4. Update the version number in `Cargo.toml`: `version = "$version_number"`
5. Update the CHANGELOG using `git cliff --github-repo xorq-labs/xorq-datafusion -p CHANGELOG.md --tag v$version_number -u`, manually add any additional notes (links to blogposts, etc.).
6. Create commit with message denoting the release: `git add --update && git commit -m "release: $version_number"`.
7. Push the new branch: `git push --set-upstream upstream "release-$version_number"`
8. Open a PR for the new branch `release-$version_number`
9. Trigger the [ci-pre-release action](https://github.com/xorq-labs/xorq-datafusion/actions/workflows/ci-pre-release.yml) from the branch created: Run workflow -> Use workflow from -> Branch `$version_number`
10. Wait for the ci-pre-release tests to all pass
11. "Squash and merge" the PR
12. Tag the updated main with `v$version_number` and push the tag: `git fetch && git tag v$version_number origin/main && git push --tags`
13. Create a [GitHub release](https://github.com/xorq-labs/xorq-datafusion/releases/new) to trigger the publishing workflow.
