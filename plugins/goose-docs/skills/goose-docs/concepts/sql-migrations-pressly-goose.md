# SQL migrations - pressly/goose

> Source: https://pressly.github.io/goose/blog/category/sql-migrations

## [SQL migration files and goose annotations](<https://pressly.github.io/goose/blog/2022/overview-sql-file/>)

In this post we'll explore SQL migration files and `+goose` annotation comments, which are used to parse SQL statements and optionally modify how migrations are executed.

As of this writing there are five annotations:
[code] 
    -- +goose Up
    -- +goose Down
    -- +goose StatementBegin
    -- +goose StatementEnd
    -- +goose NO TRANSACTION
    
[/code]

Back to top

