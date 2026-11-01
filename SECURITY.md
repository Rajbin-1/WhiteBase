# Security

Report suspected security vulnerabilities privately to the repository owner;
do not include exploit details in public issues.

White Base validates package archive paths and basic manifest requirements.
It does **not** sandbox connector code. Bricks execute in-process with the
permissions of the White Base process. Manifest permissions, dependencies,
and resource requests are descriptive metadata and are not enforced.

Install only trusted Brick packages. Do not treat archive validation as
protection against malicious connector code. See [docs/SECURITY.md](docs/SECURITY.md)
for the current security boundary.
