# Shared Fluidd Z-offset controls

This internal installer carries one verified Jacob Fluidd `v1.37.4` overlay for
the optional Global Carto Touch and Material Z-offset editors. Keeping both
dialogs in one archive prevents either optional feature from replacing the
other one's UI.

The normal Fluidd core installer and update source are unchanged. The overlay
uses an atomic directory swap, retains the original pre-overlay backup, and
restarts only nginx after a successful validation.

For audit/reproduction, apply `fluidd-v1.37.4.patch` to Jacob's exact
`v1.37.4` tree with `git apply --unidiff-zero` before building.
