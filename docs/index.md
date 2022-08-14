# Welcome

This is the technical documentation for Trade Alpha.

## What

* `mkdocs new [dir-name]` - Create a new project.
* `mkdocs serve` - Start the live-reloading docs server.
* `mkdocs build` - Build the documentation site.
* `mkdocs -h` - Print help message and exit.

## Project layout

The project is layed out as a monorepo. It contains the code 
for multiple standalone applications that are built to function together.
For more details, see [architecture](/architecture)

    docs/         # This documentation 
    tradealpha/   # The source code
    alembic/      # Everything related to alembic (database migrations)
    tests/        # Test suite
