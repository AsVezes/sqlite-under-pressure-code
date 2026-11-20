# Stockroom Ledger checkpoint snapshots

These immutable commits are the development inputs for CP00–CP02. The SQLite source, CLI profile and full replay are recorded separately during validation.

| Step | Entrance | Output commit | Chapter | Observable state |
| --- | --- | --- | --- | --- |
| CP00 | [Kit before the project](https://github.com/AsVezes/sqlite-under-pressure-code/commit/26b6888f3ab74fb47248dfde7a113b2afd78b46d) | [34a0abc](https://github.com/AsVezes/sqlite-under-pressure-code/commit/34a0abc192df4e45bae08343f3cd49debe7de4ac) | C01 | Two processes identify the same exclusive workspace and its schema version 0. |
| CP01 | CP00 database | [8c468f6](https://github.com/AsVezes/sqlite-under-pressure-code/commit/8c468f602177de7fdaf3061141404019136ee50a) | C03 | Schema v1 in the same file, opening quantities 10/2 and 4/8, no movements, O1 passes. |
| CP02 | CP01 database | [5292d39](https://github.com/AsVezes/sqlite-under-pressure-code/commit/5292d3944ed2ece7f93327fa93496acfe949f748) | C05 | Moving three bolts leaves 7/5, one transfer and two journal legs. Negative controls preserve the prior state. |

Download or check out each output commit in a separate directory and follow its [command guide](README.md) from the repository root. Keep the database in a separate disposable directory and carry the same absolute path across all three states. At each stage run `python3 -m unittest discover -s stockroom -t . -v`. CP02 also provides the entry points needed to build all three states directly from a fresh workspace.

These development snapshots require execution and independent review.
