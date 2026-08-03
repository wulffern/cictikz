# Releasing cictikz

Releases go to [PyPI](https://pypi.org/project/cictikz/) the same way
cicwave's do: tag the version, push the tag, and GitHub Actions builds,
checks, publishes and cuts a release.

The very first upload is the exception — it has to be done by hand,
because a project has to exist on PyPI before it can be given a trusted
publisher.

## The first release, by hand

1. Check the artefacts build and carry their data:

   ```sh
   make build          # clean, build, twine check
   ```

2. Look inside the wheel. The TeX libraries and the symbol descriptions
   are the package; without them an installed cictikz can neither render
   a figure nor describe a symbol:

   ```sh
   python -c "import zipfile,glob; n=zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist(); \
              print(sum(f.endswith('.tex') for f in n), 'tex,', \
                    sum(f.endswith('.yaml') for f in n), 'yaml')"
   ```

   Expect 13 `.tex` and 53 `.yaml`.

3. Install the wheel into a throwaway environment and use it, rather
   than trusting the file list:

   ```sh
   python -m venv /tmp/t && /tmp/t/bin/pip install dist/*.whl
   /tmp/t/bin/cictikz symbols | head
   printf '\\draw (0,0) \\vground \\vresistor{$R$} \\lvnmos{M1}{$v_i$};\n' > /tmp/probe.tex
   /tmp/t/bin/cictikz render /tmp/probe.tex --wrap --png -o /tmp
   ```

4. Upload. Test PyPI first if you want a rehearsal:

   ```sh
   make test_upload    # https://test.pypi.org
   make upload         # https://pypi.org
   ```

   `twine` will ask for a token; create one at
   <https://pypi.org/manage/account/token/>.

## After that: trusted publishing

Once `cictikz` exists on PyPI, add a trusted publisher so no token ever
has to live in the repository:

- PyPI → the project → *Publishing* → *Add a new publisher*
- Owner `wulffern`, repository `cictikz`, workflow `release.yml`,
  environment `pypi`
- In GitHub → *Settings* → *Environments*, create an environment called
  `pypi`

Then every release is:

```sh
# bump the version in pyproject.toml first
git commit -am "Release 0.2.0"
git tag 0.2.0
git push && git push --tags
```

The workflow runs the tests, builds, checks the metadata, asserts the
wheel still carries the library and the symbol descriptions, publishes,
and creates a GitHub release with generated notes. Both `0.2.0` and
`v0.2.0` trigger it: the sibling repositories disagree about the leading
`v`, and a release should not fail over that.

## Versioning

`pyproject.toml` holds the single version. `cictikz.__version__` reads it
back through `importlib.metadata`, so there is nothing to keep in sync.
