# Go migrations - pressly/goose

> Source: https://pressly.github.io/goose/blog/category/go-migrations

## [Embedding migrations](<https://pressly.github.io/goose/blog/2021/embed-sql-migrations/>)

### [Embedding migrations](<https://pressly.github.io/goose/blog/2021/embed-sql-migrations/#embedding-migrations_1>)

Go continues to be boring while sprinkling quality of life features. One of the recent additions was the ability to embed files at compile time. Click here for [go1.16 release notes](<https://golang.org/doc/go1.16#library-embed>).

Sine many users compile `goose` themselves, this new embed feature paves the way for embedding SQL files directly into the `goose` binary. This was _already_ possible with existing tools, however, now that embedding is part of the standard library it's never been easier to offer this feature.

Back to top

