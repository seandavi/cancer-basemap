# Architecture decisions

One file per decision, `NNNN-kebab-title.md`, numbered in the order taken and
never renumbered. A superseded ADR is not deleted or edited into agreement with
the present — it gets a `Superseded by` line and stays, because the reasoning
that turned out wrong is the useful part.

## Inherited decisions

Cancer Basemap adopts [biocOnIce's ADRs](https://github.com/seandavi/bioc-on-ice/tree/main/docs/adr)
by reference (SPEC.md § Architecture): land raw then derive (0002), declared
schemas (0003), merge recomputes the scope (0004), the Cloudflare account is
the trust domain (0005), release manifest (0007), bucket-scoped vending tokens
(0011), cdsci-lake as source (0012), dataset releases (0013). [ADR-0001](0001-public-releases-monthly-parquet-bundles.md)
adopts biocOnIce 0014–0016 (Parquet bundles, writers in cdsci-lake, R2 plus
Hugging Face), replaces 0013's per-dataset releases for the public product, and,
once icegate retires, ends 0005 and 0011's role in serving. An ADR here is needed only where this
domain departs from, or adds to, those.

## What belongs here, and what does not

| | holds |
| --- | --- |
| **SPEC.md** | what the system MUST do — normative behaviour, current and complete |
| **ADRs** | why a decision went the way it did, and what was rejected |
| **milestone tracking issues** | how the work is being found and sequenced |

The test for writing one: would somebody six months from now, or an
architecture review, propose the rejected option again? If yes, write the ADR.

Format: `# NNNN — Title`, `**Status**:`, `## Context`, `## Decision`,
`## Why not <the rejected option>`.

## Status values

`Accepted` · `Superseded by NNNN` · `Reopened` (say by whom and where).
