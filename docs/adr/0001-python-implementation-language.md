# Python as the implementation language

The downloader is implemented in Python. The Qobuz-download ecosystem — reference tools, community API knowledge, and FLAC tooling such as mutagen — is Python-native, which de-risks the two integration seams (Qobuz client, Spotify match). Alternatives considered: TypeScript (adequate for a CLI, weaker audio tooling) and Rust (faster, but overkill for a solo tool and slower to iterate).
