# 2021 - pressly/goose

> Source: https://pressly.github.io/goose/blog/archive/2021

## [Ad-hoc migrations with no versioning](<https://pressly.github.io/goose/blog/2021/no-version-migrations/>)

This post describes a new feature recently added to `goose` \-- the ability to apply migrations with **no versioning**. A common use case is to seed a database with data _after_ versioned migrations have been applied.

## [A tour of goose up and down commands](<https://pressly.github.io/goose/blog/2021/visualizing-up-down-commands/>)

A while ago a co-op student, who happened to be a visual leaner, asked if it were possible to explain `goose` commands visually. At the time we were still at an office, so we gathered around the whiteboard and doodled some diagrams.

This post captures some of those whiteboard sketches, which seemed to help.

## [Adding support for out-of-order migrations](<https://pressly.github.io/goose/blog/2021/out-of-order-migrations/>)

Starting with `goose` [v3.3.0](<https://github.com/pressly/goose/releases/tag/v3.3.0>) we added the ability to apply missing (out-of-order) migrations. Thanks for all the the community feedback over the years.

## [Better tests with containers](<https://pressly.github.io/goose/blog/2021/better-tests/>)

Managing state is hard. Managing database state is even harder. And coordinating state within a test suite is just always a bad time.

But it doesn't have to be this way!

There is a fantastic Go package called [ory/dockertest](<https://github.com/ory/dockertest>) that allows you to spin up ephemeral docker containers. It'll work both locally (assuming you have Docker installed) and in your Continuous Integration (CI) pipelines.

## [Embedding migrations](<https://pressly.github.io/goose/blog/2021/embed-sql-migrations/>)

### [Embedding migrations](<https://pressly.github.io/goose/blog/2021/embed-sql-migrations/#embedding-migrations_1>)

Go continues to be boring while sprinkling quality of life features. One of the recent additions was the ability to embed files at compile time. Click here for [go1.16 release notes](<https://golang.org/doc/go1.16#library-embed>).

Sine many users compile `goose` themselves, this new embed feature paves the way for embedding SQL files directly into the `goose` binary. This was _already_ possible with existing tools, however, now that embedding is part of the standard library it's never been easier to offer this feature.

## [Hello, docs!](<https://pressly.github.io/goose/blog/2021/welcome/>)

Introductory blog post. I guess I'll write a few words.

Back to top

