# SQL migration files and goose annotations

> Source: https://pressly.github.io/goose/blog/2022/overview-sql-file

# SQL migration files and goose annotations

In this post we'll explore SQL migration files and `+goose` annotation comments, which are used to parse SQL statements and optionally modify how migrations are executed.

As of this writing there are five annotations:
[code] 
    -- +goose Up
    -- +goose Down
    -- +goose StatementBegin
    -- +goose StatementEnd
    -- +goose NO TRANSACTION
    
[/code]

bonus

In addition to SQL migration files, the [`goose` package](<https://pkg.go.dev/github.com/pressly/goose/v3>) can be used to write Go-based migrations and track both SQL and Go migrations in the same way.

See [repository example](<https://github.com/pressly/goose/tree/master/examples/go-migrations>) for Go migrations. We'll do a deep dive in a future post. Stay tuned!

## Quick start

Here's a copy/pasteable `.sql` migration file to get started:
[code] 
    -- +goose Up
    SELECT 'up SQL query';
    
    -- +goose Down
    SELECT 'down SQL query';
    
[/code]

Remember, annotations are captured as comments and cannot have leading spaces:
[code] 
    -- +goose Up ✅
        -- +goose Up ❌ (error because leading whitespace)
    
[/code]

## The basics

A SQL migration file must have a `.sql` extension and is prefixed with either a timestamp or a sequential number.

There is a handy `goose create` command to stub out migration files in a consistent way:

#### timestamp
[code] 
    $ goose -dir migrations create add_users_table sql
    Created new file: migrations/20230201093158_add_users_table.sql
    
[/code]

#### sequential
[code] 
    $ goose -dir migrations -s create add_users_table sql [](<#__code_4_annotation_1>)
    migrations/00001_add_users_table.sql
    
[/code]

  1. 


A SQL migration file can have both Up and Down migrations. For the curious, there is an open issue ([ #374](<https://github.com/pressly/goose/issues/374>)) requesting support for migrations to be split in separate files.

Each SQL migration file is expected to have exactly one `-- +goose Up` annotation.

The `-- +goose Down` annotation is optional, but recommended, and **must** come after the Up annotation within the file. Example:
[code] 
    -- +goose Up
    SELECT 'up SQL query 1';
    SELECT 'up SQL query 2';
    SELECT 'up SQL query 3';
    
    -- +goose Down [](<#__code_5_annotation_1>)
    SELECT 'down SQL query 1';
    SELECT 'down SQL query 2';
    
[/code]

  1. 


Any statements following `-- +goose Up` will be executed as part of an up migration, and any statements following `-- +goose Down` will be executed as part of a down migration.

## Complex statements

By default, SQL statements are delimited by semicolons - in fact, query statements **must** end with a semicolon to be properly recognized by `goose`.

More complex statements (PL/pgSQL) that have semicolons within them must be annotated with `-- +goose StatementBegin` and `-- +goose StatementEnd` to be properly parsed. For example:
[code] 
    -- +goose Up
    
    -- +goose StatementBegin
    CREATE OR REPLACE FUNCTION histories_partition_creation( DATE, DATE )
    returns void AS $$
    DECLARE
      create_query text;
    BEGIN
    -- This comment will be preserved.
      -- And so will this one.
      FOR create_query IN SELECT
          'CREATE TABLE IF NOT EXISTS histories_'
          || TO_CHAR( d, 'YYYY_MM' )
          || ' ( CHECK( created_at >= timestamp '''
          || TO_CHAR( d, 'YYYY-MM-DD 00:00:00' )
          || ''' AND created_at < timestamp '''
          || TO_CHAR( d + INTERVAL '1 month', 'YYYY-MM-DD 00:00:00' )
          || ''' ) ) inherits ( histories );'
        FROM generate_series( $1, $2, '1 month' ) AS d
      LOOP
        EXECUTE create_query;
      END LOOP;  -- LOOP END
    END;         -- FUNCTION END
    $$
    language plpgsql;
    -- +goose StatementEnd
    
[/code]

When `goose` detects a `-- +goose StatementBegin` annotation it continues parsing statement(s), ignoring semicolons, until `-- +goose StatementEnd` is detected. The resulting statement is stripped of leading and trailing comments / empty lines.

Comments and empty lines within the statement are preserved!

## Multiple statements

But that's not all, the Begin and End annotations can be used to combine multiple statements so they get sent as a single command instead of being sent one-by-one.

This is best illustrated with a contrived example. Suppose we have a migration that creates a `users` table and adds 100,000 rows with distinct `INSERT`'s.
[code] 
    -- +goose Up
    CREATE TABLE users (
        id int NOT NULL PRIMARY KEY,
        username text,
        name text,
        surname text
    );
    
    [](<#__code_7_annotation_1>)
    INSERT INTO "users" ("id", "username", "name", "surname") VALUES (1, 'gallant_almeida7', 'Gallant', 'Almeida7');
    INSERT INTO "users" ("id", "username", "name", "surname") VALUES (2, 'brave_spence8', 'Brave', 'Spence8');
    .
    .
    INSERT INTO "users" ("id", "username", "name", "surname") VALUES (99999, 'jovial_chaum1', 'Jovial', 'Chaum1');
    INSERT INTO "users" ("id", "username", "name", "surname") VALUES (100000, 'goofy_ptolemy0', 'Goofy', 'Ptolemy0');
    
    -- +goose Down
    DROP TABLE users;
    
[/code]

  1. 


The Up migration contains 100,001 unique statements, all executed within the same transaction, but sent to the database one-by-one. This migration will take ~38s to complete due to the number of round trips.

Using PostgreSQL as an example, here's what the database logs show:
[code] 
    LOG:  statement: INSERT INTO "users" ("id", "username", "name", "surname") VALUES (1, 'gallant_almeida7', 'Gallant', 'Almeida7');
    LOG:  statement: INSERT INTO "users" ("id", "username", "name", "surname") VALUES (2, 'brave_spence8', 'Brave', 'Spence8');
    LOG:  statement: INSERT INTO "users" ("id", "username", "name", "surname") VALUES (3, 'lucid_bardeen6', 'Lucid', 'Bardeen6');
    [...] 100,000 log statements
    
[/code]

However, if we want to combine the inserts into a single command, we can wrap them with `-- +goose StatementBegin` and `-- +goose StatementEnd` annotations. Note, a single command still contains several statements separated by semicolons, but they get sent to the server in the same query string like so: `"INSERT INTO ...; INSERT INTO ...;"`.
[code] 
    -- +goose Up
    CREATE TABLE users (
        id int NOT NULL PRIMARY KEY,
        username text,
        name text,
        surname text
    );
    
    -- +goose StatementBegin
    INSERT INTO "users" ("id", "username", "name", "surname") VALUES (1, 'gallant_almeida7', 'Gallant', 'Almeida7');
    INSERT INTO "users" ("id", "username", "name", "surname") VALUES (2, 'brave_spence8', 'Brave', 'Spence8');
    .
    .
    INSERT INTO "users" ("id", "username", "name", "surname") VALUES (99999, 'jovial_chaum1', 'Jovial', 'Chaum1');
    INSERT INTO "users" ("id", "username", "name", "surname") VALUES (100000, 'goofy_ptolemy0', 'Goofy', 'Ptolemy0');
    -- +goose StatementEnd
    
    -- +goose Down
    DROP TABLE users;
    
[/code]

These annotations instruct `goose` to send a single command, which now consists of multiples statements delimited by semicolons, in one shot.

Yes, that's a larg _er_ payload, but that's fine and the migration will execute in ~3s, which is an order of magnitude faster as compared to the previous example that ran in ~38s.

## Migrations outside transaction

All statements within a migration file are run within a transaction. Some statements, like `CREATE DATABASE` or `CREATE INDEX CONCURRENTLY`, cannot be run within a transaction block.

For such cases add the `-- +goose NO TRANSACTION` annotation, usually placed at the top of the file.

This annotation instructs `goose` to run all statements within the file without transactions. This applies to all Up and Down statements within the file.
[code] 
    -- +goose NO TRANSACTION
    
    -- +goose Up
    CREATE INDEX CONCURRENTLY ON users (user_id);
    
    -- +goose Down
    DROP INDEX IF EXISTS users_user_id_idx;
    
[/code]

Back to top

