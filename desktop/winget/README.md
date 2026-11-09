# winget packaging

Manifest set for the `Catduck.HermesLegal` package, in the winget
multi-file format (manifest version 1.6.0):

- `Catduck.HermesLegal.yaml` — version manifest
- `Catduck.HermesLegal.installer.yaml` — NSIS and MSI installers
- `Catduck.HermesLegal.locale.en-US.yaml` — default locale manifest

Both installers must be the signed artifacts from the desktop workflow;
unsigned installers are not submitted, because unsigned legal software
does not survive Windows SmartScreen in practice.

`InstallerSha256` is added at publish time from the built, signed files.
It is deliberately absent from this scaffold: the hash of an artifact
that does not exist yet cannot be known, and a placeholder hash would
make `winget install` fail verification for every user. Submission to
the microsoft/winget-pkgs repository happens from the release process,
not from this repository, once a signed release exists.
