# Embedding migrations

> Source: https://pressly.github.io/goose/blog/2021/embed-sql-migrations

# Embedding migrations

## Embedding migrations

Go continues to be boring while sprinkling quality of life features. One of the recent additions was the ability to embed files at compile time. Click here for [go1.16 release notes](<https://golang.org/doc/go1.16#library-embed>).

Sine many users compile `goose` themselves, this new embed feature paves the way for embedding SQL files directly into the `goose` binary. This was _already_ possible with existing tools, however, now that embedding is part of the standard library it's never been easier to offer this feature.

## **But why?**

We'll save "why would I compile `goose` myself?" for another post, instead we'll focus on why embedding files is an improvement to existing workflows.

A typical workflow looks something like this:

  1. Developer introduces new SQL migration file
  2. File gets merged to `main` and a `goose` binary is built
  3. The binary _along with SQL files_ is copied into a docker container
  4. The docker container is run as a singleton against the database before the application starts up


One of the cumbersome things about this workflow is that the `goose` binary and the migration files need to be shipped together and the directory structure has to be maintained.

But now that `goose` natively supports embedding files it simplifies the workflow. A `goose` binary is shipped without any file dependencies, i.e., the migration files are baked into the binary itself.

## **Gotchas**

We did not implement this in a backwards-compatible way, i.e., the feature is not guarded with build tags. Which means starting with [v3.1.0](<https://github.com/pressly/goose/releases/tag/v3.1.0>) you must be on go1.16 and up.

For older `goose` versions you may still pin [v3.0.1](<https://github.com/pressly/goose/releases/tag/v3.0.1>).

## **Try it out!**

Remember, the files to be embedded must be relative to the source file(s). Here is what our directory structure _might_ look like:
[code] 
    .
    ├── embed_example.sql
    ├── go.mod
    ├── go.sum
    └── internal
        └── goose
            ├── main.go
            └── migrations
                └── 00001_create_users_table.sql
    
[/code]

Here is a fully working example using an in-memory database (SQLite).
[code] 
    package main
    
    import (
        "database/sql"
        "embed"
        "log"
    
        _ "github.com/mattn/go-sqlite3"
        "github.com/pressly/goose/v3"
    )
    
    //go:embed migrations/*.sql
    var embedMigrations embed.FS // [](<#__code_1_annotation_1>)
    
    func main() {
        log.SetFlags(0)
        db, err := sql.Open("sqlite3", "embed_example.sql")
        if err != nil {
            log.Fatal(err)
        }
        goose.SetDialect("sqlite3")
        goose.SetBaseFS(embedMigrations) // [](<#__code_1_annotation_2>)
    
        if err := goose.Up(db, "migrations"); err != nil { // [](<#__code_1_annotation_3>)
            panic(err)
        }
        if err := goose.Version(db, "migrations"); err != nil {
            log.Fatal(err)
        }
        rows, err := db.Query(`SELECT * FROM users`)
        if err != nil {
            log.Fatal(err)
        }
        var user struct {
            ID       int
            Username string
        }
        for rows.Next() {
            if err := rows.Scan(&user.ID, &user.Username); err != nil {
                log.Fatal(err)
            }
            log.Println(user.ID, user.Username)
        }
    }
    
[/code]

  1.   2.   3. 


* * *

A sample repo can be found at [mfridmn/goose-demo](<https://github.com/mfridman/goose-demo>)

From the root of the directory you can build the binary, and to prove it has no dependencies move it to your home directory and run the binary. This will create a embed_example.sql file for sqlite database. Cool right?!
[code] 
    go build -o goosey internal/goose/main.go
    mv goosey $HOME
    cd $HOME
    ./goosey
    
[/code]

**Output:**
[code] 
    OK    00001_create.sql
    goose: no migrations to run. current version: 1
    goose: version 1
    0 root
    1 goosey
    
[/code]

Back to top

