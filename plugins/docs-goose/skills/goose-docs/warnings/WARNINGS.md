# Warnings and Deprecation Notices


## Blog - pressly/goose

Source: https://pressly.github.io/goose/blog


## [Using `sqlc` and `goose`](<https://pressly.github.io/goose/blog/2024/goose-sqlc/>)

In this post, we give you a brief introduction to `sqlc` and show you how to use it with `goose`.

## [Adding a goose provider](<https://pressly.github.io/goose/blog/2023/goose-provider/>)

### [Introduction](<https://pressly.github.io/goose/blog/2023/goose-provider/#introduction>)

In this post, we'll explore the new `Provider` feature recently added to the core goose package. If you're new to goose, it's a tool for handling database migrations, available as a standalone CLI tool and a package that can be used in Go applications.

Requires version **[v3.16.0](<https://github.com/pressly/goose/releases/tag/v3.16.0>)** and above.

Adding a provider to your application is easy, here's a quick example:
[code] 
    provider, err := goose.NewProvider(
      goose.DialectPostgres, [](<#__code_0_annotation_1>)
      db, [](<#__code_0_annotation_2>)
      os.DirFS("migrations"), [](<#__code_0_annotation_3>)
    )
    
    results, err := provider.Up(ctx) [](<#__code_0_annotation_4>)
    
[/code]

  1.   2.   3.   4. 


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

## [Improving ClickHouse support](<https://pressly.github.io/goose/blog/2022/improving-clickhouse/>)

[ClickHouse](<https://clickhouse.com/>) is a an open-source column-oriented database that is well-suited for analytical workloads. Over the past few years we've seen more and more demand for improved ClickHouse support in goose.

To summarize:

  * Upgraded to the latest `/v2` driver: [ClickHouse/clickhouse-go](<https://github.com/ClickHouse/clickhouse-go>)
  * Full end-end tests against the docker image: [clickhouse/clickhouse-server](<https://hub.docker.com/r/clickhouse/clickhouse-server/>)
  * Bug fixes and improvements


The `/v2` driver [changed the DSN format](<https://github.com/ClickHouse/clickhouse-go/issues/525>), so be prepared for a breaking change. This is actually a good thing, because it brings the format in-line with other databases.

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

## Improving ClickHouse support

Source: https://pressly.github.io/goose/blog/2022/improving-clickhouse


# Improving ClickHouse support

[ClickHouse](<https://clickhouse.com/>) is a an open-source column-oriented database that is well-suited for analytical workloads. Over the past few years we've seen more and more demand for improved ClickHouse support in goose.

To summarize:

  * Upgraded to the latest `/v2` driver: [ClickHouse/clickhouse-go](<https://github.com/ClickHouse/clickhouse-go>)
  * Full end-end tests against the docker image: [clickhouse/clickhouse-server](<https://hub.docker.com/r/clickhouse/clickhouse-server/>)
  * Bug fixes and improvements


The `/v2` driver [changed the DSN format](<https://github.com/ClickHouse/clickhouse-go/issues/525>), so be prepared for a breaking change. This is actually a good thing, because it brings the format in-line with other databases.

* * *

## Getting started

Here's a quick tour of using goose against a running ClickHouse docker container.
[code] 
    docker run --rm -d \
        -e CLICKHOUSE_DB=clickdb \
        -e CLICKHOUSE_USER=clickuser \
        -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 \
        -e CLICKHOUSE_PASSWORD=password1 \
        -p 9000:9000/tcp clickhouse/clickhouse-server:22-alpine
    
[/code]

Once the container is running, we'll apply 3 migrations with goose. For the sake of this demo, we're using migrations from [pressly/goose](<http://github.com/pressly/goose>) repository.

At the time of this writing, goose supports 3 environment variables:
[code] 
    GOOSE_DRIVER
    GOOSE_DBSTRING
    GOOSE_MIGRATION_DIR
    
[/code]

We use them in the following command for convenience. Otherwise you'll need to set the driver and database connection strings as CLI parameters and the migration directory with the `-dir` flag.
[code] 
    GOOSE_DRIVER=clickhouse \
        GOOSE_DBSTRING="tcp://clickuser:password1@localhost:9000/clickdb" \
        GOOSE_MIGRATION_DIR="tests/clickhouse/testdata/migrations" \
        goose up
    
[/code]

Expected output following a successful migration.
[code] 
    2022/06/19 20:19:04 OK    00001_a.sql
    2022/06/19 20:19:04 OK    00002_b.sql
    2022/06/19 20:19:04 OK    00003_c.sql
    2022/06/19 20:19:04 goose: no migrations to run. current version: 3
    
[/code]

* * *

## Check migrations

We can now use the [`clickhouse-client`](<https://clickhouse.com/docs/en/interfaces/cli>) to poke around the server:

### **Show tables**
[code] 
    clickhouse-client --vertical \
        --database clickdb --password password1 -u clickuser \
        -q 'SHOW TABLES'
    
[/code]

Our migrations created the `goose_db_version` table, which stores migration data, and 2 new user tables: `clickstream` and `trips`.
[code] 
    Row 1:
    ──────
    name: clickstream
    
    Row 2:
    ──────
    name: goose_db_version
    
    Row 3:
    ──────
    name: trips
    
[/code]

### **Show all data from`clickstream` table**

We used the sample data from the [Getting Started with ClickHouse tutorial](<https://clickhouse.com/learn/lessons/gettingstarted/>).
[code] 
    clickhouse-client --vertical \
        --database clickdb --password password1 -u clickuser \
        -q 'SELECT * FROM clickstream'
    
[/code]

Output:
[code] 
    Row 1:
    ──────
    customer_id:      customer3
    time_stamp:       2021-11-07
    click_event_type: checkout
    country_code:
    source_id:        307493
    
    Row 2:
    ──────
    customer_id:      customer2
    time_stamp:       2021-10-30
    click_event_type: remove_from_cart
    country_code:
    source_id:        0
    
    Row 3:
    ──────
    customer_id:      customer1
    time_stamp:       2021-10-02
    click_event_type: add_to_cart
    country_code:     US
    source_id:        568239
    
[/code]

Back to top

## 2022 - pressly/goose

Source: https://pressly.github.io/goose/blog/archive/2022


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

## [Improving ClickHouse support](<https://pressly.github.io/goose/blog/2022/improving-clickhouse/>)

[ClickHouse](<https://clickhouse.com/>) is a an open-source column-oriented database that is well-suited for analytical workloads. Over the past few years we've seen more and more demand for improved ClickHouse support in goose.

To summarize:

  * Upgraded to the latest `/v2` driver: [ClickHouse/clickhouse-go](<https://github.com/ClickHouse/clickhouse-go>)
  * Full end-end tests against the docker image: [clickhouse/clickhouse-server](<https://hub.docker.com/r/clickhouse/clickhouse-server/>)
  * Bug fixes and improvements


The `/v2` driver [changed the DSN format](<https://github.com/ClickHouse/clickhouse-go/issues/525>), so be prepared for a breaking change. This is actually a good thing, because it brings the format in-line with other databases.

Back to top

## Blog - pressly/goose

Source: https://pressly.github.io/goose/blog/category/blog


## [Using `sqlc` and `goose`](<https://pressly.github.io/goose/blog/2024/goose-sqlc/>)

In this post, we give you a brief introduction to `sqlc` and show you how to use it with `goose`.

## [Adding a goose provider](<https://pressly.github.io/goose/blog/2023/goose-provider/>)

### [Introduction](<https://pressly.github.io/goose/blog/2023/goose-provider/#introduction>)

In this post, we'll explore the new `Provider` feature recently added to the core goose package. If you're new to goose, it's a tool for handling database migrations, available as a standalone CLI tool and a package that can be used in Go applications.

Requires version **[v3.16.0](<https://github.com/pressly/goose/releases/tag/v3.16.0>)** and above.

Adding a provider to your application is easy, here's a quick example:
[code] 
    provider, err := goose.NewProvider(
      goose.DialectPostgres, [](<#__code_0_annotation_1>)
      db, [](<#__code_0_annotation_2>)
      os.DirFS("migrations"), [](<#__code_0_annotation_3>)
    )
    
    results, err := provider.Up(ctx) [](<#__code_0_annotation_4>)
    
[/code]

  1.   2.   3.   4. 


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

## [Improving ClickHouse support](<https://pressly.github.io/goose/blog/2022/improving-clickhouse/>)

[ClickHouse](<https://clickhouse.com/>) is a an open-source column-oriented database that is well-suited for analytical workloads. Over the past few years we've seen more and more demand for improved ClickHouse support in goose.

To summarize:

  * Upgraded to the latest `/v2` driver: [ClickHouse/clickhouse-go](<https://github.com/ClickHouse/clickhouse-go>)
  * Full end-end tests against the docker image: [clickhouse/clickhouse-server](<https://hub.docker.com/r/clickhouse/clickhouse-server/>)
  * Bug fixes and improvements


The `/v2` driver [changed the DSN format](<https://github.com/ClickHouse/clickhouse-go/issues/525>), so be prepared for a breaking change. This is actually a good thing, because it brings the format in-line with other databases.

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

## ClickHouse - pressly/goose

Source: https://pressly.github.io/goose/blog/category/clickhouse


## [Improving ClickHouse support](<https://pressly.github.io/goose/blog/2022/improving-clickhouse/>)

[ClickHouse](<https://clickhouse.com/>) is a an open-source column-oriented database that is well-suited for analytical workloads. Over the past few years we've seen more and more demand for improved ClickHouse support in goose.

To summarize:

  * Upgraded to the latest `/v2` driver: [ClickHouse/clickhouse-go](<https://github.com/ClickHouse/clickhouse-go>)
  * Full end-end tests against the docker image: [clickhouse/clickhouse-server](<https://hub.docker.com/r/clickhouse/clickhouse-server/>)
  * Bug fixes and improvements


The `/v2` driver [changed the DSN format](<https://github.com/ClickHouse/clickhouse-go/issues/525>), so be prepared for a breaking change. This is actually a good thing, because it brings the format in-line with other databases.

Back to top

## Commands

Source: https://pressly.github.io/goose/documentation/cli-commands


# Commands

The following commands are part of the **stable set** of commands and will remain backwards compatible across minor/patch upgrades.
[code] 
    Usage: goose [flags] DRIVER DBSTRING <command>
    
[/code]

Flags must come **before** commands, otherwise they will be interpreted as arguments to the command.

Both `DRIVER` and `DBSTRING` may be set using environment variables `GOOSE_DRIVER` and `GOOSE_DBSTRING`. See the [environment variables](<https://pressly.github.io/goose/documentation/environment-variables/>) documentation for more information.

## Commands

### **`up`**

Migrate the DB to the most recent version available

### **up-by-one**

Migrate the DB up by 1

### **up-to**

Migrate the DB to a specific VERSION

### **down**

Roll back the version by 1

### **down-to**

Roll back to a specific VERSION

### **redo**

Re-run the latest migration

### **reset**

Roll back all migrations

### **status**

Dump the migration status for the current DB

### **version**

Print the current version of the database

### **create**

Creates new migration file with the current timestamp

### **fix**

Apply sequential ordering to migrations

## Supported Drivers

Driver | Go package  
---|---  
`clickhouse` | `github.com/ClickHouse/clickhouse-go/v2`  
`mssql` | `github.com/microsoft/go-mssqldb`  
`mysql` | `github.com/go-sql-driver/mysql`  
`postgres` | `github.com/jackc/pgx/v5/stdlib`  
`sqlite3` | `modernc.org/sqlite`  
`turso` | `github.com/tursodatabase/libsql-client-go/libsql`  
`vertica` | `github.com/vertica/vertica-sql-go`  
`ydb` | `github.com/yandex-cloud/ydb-go-sdk/v2`  
  
Back to top