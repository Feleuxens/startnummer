[![Build and publish images](https://github.com/Feleuxens/startnummer/actions/workflows/images.yml/badge.svg)](https://github.com/Feleuxens/startnummer/actions/workflows/images.yml)

# Startnummer

Startnummer helps sports photographers turn photos and a competition roster into
reviewed captions. Import an album, analyze it, correct names and disciplines,
then apply approved descriptions to existing **Chevereto 4.5.9** images.

Your photos, roster, names, and captions stay available when you reopen an album.
Extracted face data is temporary and is discarded when you finish face review.

## Get started

Follow the [Docker quick start](docs/docker.md) to install Startnummer, create the
first administrator, and analyze a small album. Linux deployments use Docker;
CPU is the default. Intel OpenVINO and NVIDIA workers are also available.

For a Mac, follow [native installation](docs/devices.md) to use Apple silicon
through CoreML and the Neural Engine.

## What you can do

- Import photos from Chevereto or upload JPEG, PNG, and WebP files.
- Load a roster from a Competitoroverview or Resultoverview URL or HTML file.
- Match athletes using bib reads and face matches within the album.
- Correct a caption, assign a person from the roster, or name a detected face.
- Assign one discipline to a sequence of photos.
- Review and approve captions before replacing gallery descriptions.
- Keep private workspaces for several users and invite new accounts.

Chevereto access is administrator-managed. Other users can upload, analyze, and
review their own photos. Uploaded photos have no gallery destination; Startnummer
does not match them to existing images by filename.

## Guides

| I want to…                                    | Read                                   |
| --------------------------------------------- | -------------------------------------- |
| Install or build the Docker images            | [Docker quick start](docs/docker.md)   |
| Import, review, and publish an album          | [Review an album](docs/review.md)      |
| Connect an existing gallery                   | [Chevereto](docs/chevereto.md)         |
| Invite users or change registration settings  | [Accounts](docs/accounts.md)           |
| Set up HTTPS with Nginx                       | [Reverse proxy](docs/reverse-proxy.md) |
| Check status, change limits, or update        | [Operations](docs/operations.md)       |
| Back up or recover saved work                 | [Backups](docs/backups.md)             |
| Choose an accelerator or install natively     | [Device profiles](docs/devices.md)     |
| Choose an image tag or publish a release      | [Container releases](docs/releases.md) |
| Run the app locally and contribute            | [Development](docs/development.md)     |
| Understand persistence and face-data handling | [Architecture](docs/architecture.md)   |

Startnummer stores its own data in PostgreSQL, separately from Chevereto's
MariaDB database. Keep regular [backups](docs/backups.md) of saved work and server
configuration. Publishing changes existing gallery descriptions only after review
and confirmation.
