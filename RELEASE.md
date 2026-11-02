# Publishing a version

A guide for maintainers. A FYOS version consists of two repos with the same tag: `fyos-agent` (image `runner`) and
`fyos-os` (images `web` and `hub`, PyPI packages `fyos-hub` and `fyos-installer`). The installer pulls the agent image
with the tag of its own version (`AGENT_TAG` in `installer/fyos_installer/erzeugen.py`). That is why `fyos-agent` gets
the tag first. The examples name version 0.1.1; put in your version.

Keep to the order and only move on when the step before is right. A published PyPI entry and a tag on GitHub cannot be
taken back.

## Before: the version is everywhere

A pull request on the Git server prepares the version and is merged before you start:

- `fyos-hub` (`hub/pyproject.toml`, `hub/mcp_hub/__init__.py`), `fyos-installer` (`installer/pyproject.toml`,
  `installer/fyos_installer/__init__.py`) and `web/package.json` together with `web/package-lock.json` carry the
  version.
- `AGENT_TAG` in the installer points to the version's tag (`v0.1.1`); the test `installer/tests/test_erzeugen.py`
  checks this.
- `CHANGELOG.md` has a section for the version (in both repos). When publishing, replace "unreleased" with the date.

## Steps

1. **The Git server's main branch is green.** In both repos the last run on `main` is free of errors, including the
   scheduled run. A red run gets fixed, not skipped.
2. **Check the cleanliness of the history**, first in `fyos-agent`, then in `fyos-os`:

   ```sh
   python3 tools/sauber.py --historie
   ```

   The command must stay silent and end with exit code 0. It checks names and addresses of author and committer and
   all commit messages. A finding means: publish nothing, remove the cause first.
3. **Export to GitHub**, first `fyos-agent`, then `fyos-os`. The export is a clean state of the main branch without the
   Git server's history; the commit carries the stamp "FYOS 0.1.1". After pushing, check that the main branch on GitHub
   has the expected state and that the files match this repo.
4. **Set the tag `v0.1.1`**, first in `fyos-agent`, then in `fyos-os`, each on the export on GitHub. The tag triggers
   the runs: in `fyos-agent` the image `runner`, in `fyos-os` the runs `tests`, `pypi` and `bilder`. After the first
   tag, wait until the agent image is there before you set the second.
5. **Check** that everything arrived:
   - The runs `tests`, `pypi` and `bilder` (and in `fyos-agent` `tests` and `bilder`) are green.
   - PyPI has `fyos-hub` and `fyos-installer` in version 0.1.1.
   - The registry `ghcr.io/sirfyyn` has the tags `v0.1.1` and `latest` for `fyos-os/web`, `fyos-os/hub` <!-- sauber: ok -->
     and `fyos-agent/runner`.
   - The installer runs through a dry run with the published version and names the images with the tag `v0.1.1`:

     ```sh
     pipx run --spec fyos-installer==0.1.1 fyos-install --auswahl kern,agent --ziel compose --trocken
     ```

     The plan must name the images `web`, `hub` and `runner` with the tag `v0.1.1`, for Compose as for Kubernetes
     (`--ziel k8s`). Instead of `pipx`, a fresh virtual environment with `pip install fyos-installer==0.1.1` works too.
6. **Only then the release text on GitHub**, per repo from the version's section in `CHANGELOG.md`. Take the text
   word for word from the section and add at most the links to the packages and images.

## If something goes wrong

- **A run is red before anything was published** (PyPI check, image build): fix the cause, bring a new state into both
  repos through a pull request, repeat the export and set the tag again. You may delete and re-set a tag that carries
  no published state.
- **PyPI already has the packages:** a version cannot be overwritten there. Fix the error in a new patch version (for
  example 0.1.2) and, if needed, mark 0.1.1 as "yanked" on PyPI.
- **An image tag is missing:** start the run `bilder` by hand for the tag (Actions, `bilder`, "Run workflow").
