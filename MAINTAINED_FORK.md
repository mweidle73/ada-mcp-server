# Maintained fork patch series

This repository is a downstream fork of
[`MDBrothers/ada-mcp-server`](https://github.com/MDBrothers/ada-mcp-server).
It keeps the upstream history and the maintained changes separate:

- `main` mirrors upstream.
- `abuild/maintained` is the ordered, project-neutral server patch series.
- `abuild-gh` is the default operational branch. It contains
  `abuild/maintained` and adds documentation, formatting, dependency updates,
  and GitHub Actions used to maintain the fork.

The table below is the fork-local record of the functional differences from
upstream. Its order is the commit order on `abuild/maintained`. The patch
numbers match the exported patch sequence used by Abuild; the patch files
themselves are maintained in the Abuild repository.

## Functional patch series

| Patch | Fork commit | Purpose |
| --- | --- | --- |
| `0001` | [`597789b`](https://github.com/mweidle73/ada-mcp-server/commit/597789ba3c413e6024e34eb150475e55d6e0dd96) | Use ALS's evaluated project view instead of parsing GPR source text with regular expressions. |
| `0002` | [`dadf72c`](https://github.com/mweidle73/ada-mcp-server/commit/dadf72cb34acf07e82eb91b892873af0adce0653) | Fail pending requests when ALS disconnects and keep document-open state per ALS client. |
| `0003` | [`50a0967`](https://github.com/mweidle73/ada-mcp-server/commit/50a0967bd905fac58b0b24e40603f2f716efb92d) | Synchronize document changes and distinguish complete file diagnostics from the incomplete publication cache. |
| `0004` | [`4bc5fea`](https://github.com/mweidle73/ada-mcp-server/commit/4bc5fea6bf4304b5385d6b69deb2ac70f3b14bc6) | Wait for ALS indexing and select the intended project for workspace-wide semantic requests. |
| `0005` | [`d9edb84`](https://github.com/mweidle73/ada-mcp-server/commit/d9edb846fb919f63966dc403436978d0802ebb1f) | Return a calibrated incomplete result when ALS cannot load an imported or generated GPR dependency. |
| `0006` | [`6b43900`](https://github.com/mweidle73/ada-mcp-server/commit/6b43900bb2d82bf05537c48642ed55b51d753ab9) | Announce Ada sources created after ALS startup so they join the running project. |
| `0007` | [`c9481ea`](https://github.com/mweidle73/ada-mcp-server/commit/c9481ea3e41d0d06bb3b45272133a5ae4c472670) | Synchronize source documents before completion and refactoring requests. |
| `0008` | [`f6dec47`](https://github.com/mweidle73/ada-mcp-server/commit/f6dec47dea1d7510009a6c6ba453d7d9615fef4b) | Merge live document symbols into workspace searches when ALS omits open sources. |
| `0009` | [`f6f5ea2`](https://github.com/mweidle73/ada-mcp-server/commit/f6f5ea2389f4966738972fca001cf393f17a1060) | Synchronize creation and deletion of Ada sources with ALS and reject stale symbol locations. |
| `0010` | [`e6b4a49`](https://github.com/mweidle73/ada-mcp-server/commit/e6b4a4952465058d3aaeacd4be0545a0fda39325) | Preserve the selected identifier and exact source spelling in rename previews. |
| `0011` | [`19c311f`](https://github.com/mweidle73/ada-mcp-server/commit/19c311fc9cb558e06db84b7ed0d04ce8129b4974) | Pass validated scenario variables to ALS so headless clients can select a GPR scenario. |
| `0012` | [`5d519c3`](https://github.com/mweidle73/ada-mcp-server/commit/5d519c3233afddb207f68358a477084c670b9c6b) | Constrain the MCP SDK to the supported 1.x API. |
| `0013` | [`a19cc2b`](https://github.com/mweidle73/ada-mcp-server/commit/a19cc2b9bd3968e7926577935cd5483023b06b50) | Validate scenario configuration, retain the default payload, and make applied variables diagnosable. |
| `0014` | [`991e56e`](https://github.com/mweidle73/ada-mcp-server/commit/991e56ea740d6740f073c7ad1a24f6a13740b2f9) | Log scenario-variable names without exposing their values. |
| `0015` | [`4b6deaa`](https://github.com/mweidle73/ada-mcp-server/commit/4b6deaa740716b3fe7421db30dbebe1f7987fba9) | Keep real-ALS probes aligned with the mandatory project-anchor contract. |
| `0016` | [`a978da3`](https://github.com/mweidle73/ada-mcp-server/commit/a978da3a6aae9fb644fd204c51f325e324d669bb) | Complete the strict source-package type contract without changing the MCP representation. |
| `0017` | [`a2b4bd7`](https://github.com/mweidle73/ada-mcp-server/commit/a2b4bd765f6fab39f863d4d379d0cb88ab41b2b8) | Return the selected project settings when ALS pulls workspace configuration during initialization. |
| `0018` | [`eeb53ca`](https://github.com/mweidle73/ada-mcp-server/commit/eeb53ca68b340c8fb5b53e11a7e1bd938c430316) | Discard a failed ALS project instance so repaired GPR project views are evaluated by the next request. |
| `0019` | [`8ef1c77`](https://github.com/mweidle73/ada-mcp-server/commit/8ef1c770a0d746bf4b3faff2b910ec96a57de1c0) | Refresh explicit file diagnostics after a dependency source changes while retaining the navigation document cache. |
| `0020` | [`1218f45`](https://github.com/mweidle73/ada-mcp-server/commit/1218f455c78b05512f95c7e7dc12ef5468d36c5a) | Select an exact GPR project view and retain it for subsequent file tools. |
| `0021` | [`ae71c6b`](https://github.com/mweidle73/ada-mcp-server/commit/ae71c6bfa52add85f466ccfa0477f398bb970e15) | Apply the maintained source format to the project-view pool lookup. |
| `0022` | [`c79361d`](https://github.com/mweidle73/ada-mcp-server/commit/c79361d33db87714253cf0c8e1e0e76fdb3e11a3) | Attach validated GPR search paths and scenario overrides to an exact project view. |

All entries are fork-only relative to the upstream history mirrored by `main`.
Here, *fork-only* means that the commit is absent from that mirrored history;
it does not assert whether related upstream discussion or work exists.

## Fork-maintenance changes

`abuild-gh` also carries operational history on top of the functional series.
These changes are deliberately not assigned patch numbers because Abuild does
not export them. The initial maintenance layer consists of:

| Commit | Purpose |
| --- | --- |
| [`cd2626d`](https://github.com/mweidle73/ada-mcp-server/commit/cd2626d63cca465639d6abb5f8fcb2da7d8c8b4c) | Normalize tests and protocol probes for the fork's enforced formatter. |
| [`ebb231a`](https://github.com/mweidle73/ada-mcp-server/commit/ebb231a6af481c4f462eda39080243ef69a373d5) | Add the maintained-fork branch model, pinned CI quality gate, and dependency update configuration. |

Later documentation, workflow, and dependency-update commits remain ordinary
`abuild-gh` history rather than becoming part of the numbered functional
series.

## Verification and downstream consumption

The [`abuild-gh` quality gate](.github/workflows/ci.yml) runs the unit suite on
Python 3.11 and 3.12. On Python 3.13 it checks Ruff formatting and linting,
strict Mypy typing, coverage, and built distributions. A separate job runs a
protocol probe against a pinned Ada Language Server release.

Abuild exports the functional series as numbered patches and verifies that
each exported diff is byte-for-byte equivalent to its corresponding fork
commit. The accepted Abuild patch series can temporarily lag this branch while
a downstream merge request is under review. Its published mapping and build
instructions are maintained in the
[Abuild patch documentation](https://github.com/mweidle73/abuild/tree/master/docker/analysis/ada-mcp/patches).

When adding, dropping, reordering, or rebasing a functional commit, update this
table in the same change. When the change is consumed by Abuild, update its
numbered patch, mapping, and equivalence check together.
