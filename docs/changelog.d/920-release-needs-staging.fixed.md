**`cplat next` no longer offers "Release now" for a deployable component that has no staging instance (#920).** A fresh service
repo whose system promotes staging after the dev smoke was asked "N changes since the start. Release now?", and
`cplat component release target` then refused because nothing ran in staging; the next `cplat next` asked again. The release item of
a deployable component now follows the release's own precondition: without a staging instance the next step is the first, manual
promotion to staging (`/instance:promote <component> --to staging`, run in the gitops repo it names), and a staging commit that is
already released offers no release. A library still releases from main. The staging promote question no longer asks "Promote it
to prod?".
