# Vendored code

`src/_vendor/cli_common/` is a subset of the internal `cli_common` library,
copied verbatim so this repository installs without the internal fleet.

- Origin: `/home/ubuntu/.god-tier-cli/tools/cli_common`
- Commit: `6df65a35`
- License: MIT
- Modules:

- `toon_help`
- `toon_output`

Replace it with a small local module when you touch it. Do not re-vendor from
the internal repository without repeating the import rewrite.
