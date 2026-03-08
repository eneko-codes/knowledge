# Installing goose

> Source: https://pressly.github.io/goose/installation

# Installing goose

This project is both a command-line utility (CLI) and a library. This section covers how to install or build `goose`.

You can also install a pre-compiled binary from the [GitHub release page](<https://github.com/pressly/goose/releases>). Don't forget to set the executable bit on macOS and Linux.

##  macOS

* * *

### Homebrew

If you're on a Mac, the easiest way to get started is with the [Homebrew](<https://brew.sh>) package manager.
[code] 
    brew install goose
    
[/code]

An installation script is available that works on macOS, see [ Linux](<https://pressly.github.io/goose/installation/#linux>).

##  Linux

* * *

At the root of the project is an [`install.sh` script](<https://github.com/pressly/goose/blob/master/install.sh>) to download and install the binary.
[code] 
    curl -fsSL \
        https://raw.githubusercontent.com/pressly/goose/master/install.sh |\
        sh [](<#__code_1_annotation_1>)
    
[/code]

  1. 


The default output directory is `/usr/local/bin`, but can be changed by setting `GOOSE_INSTALL`. Do not include `/bin`, it is added by the script.

Optionally, a version can be specified as an argument. The default is to download the `latest` version.
[code] 
    curl -fsSL \
        https://raw.githubusercontent.com/pressly/goose/master/install.sh |\
        GOOSE_INSTALL=$HOME/.goose sh -s v3.5.0
    
[/code]

This will install `goose version v3.5.0` in directory:
[code] 
    $HOME/.goose/bin/goose
    
[/code]

##  Windows

* * *

No installation script is available, but you can download a [pre-built Windows binary](<https://github.com/pressly/goose/releases>) or build from source if Go is installed.

## ![🧰](https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/svg/1f9f0.svg) Building from source

* * *

You'll need Go 1.16 or later.
[code] 
    go install github.com/pressly/goose/v3/cmd/goose@latest
    
[/code]

Alternatively, you can clone the repository and build from source.
[code] 
    git clone https://github.com/pressly/goose
    cd goose
    go mod tidy
    go build -o goose ./cmd/goose
    
    ./goose --version
    # goose version:(devel)
    
[/code]

This will produce a `goose` binary **~15M** in size because it includes all supported drivers.

### Lite version

For a lite version of the binary, use the exclusive build tags. Here's an example where we target only `sqlite`, and the resulting binary is **~8.7M** in size.
[code] 
    go build \
        -tags='no_postgres no_clickhouse no_mssql no_mysql' \
        -o goose ./cmd/goose
    
[/code]

Bonus, let's make this binary smaller by stripping debugging information.
[code] 
    go build \
        -ldflags="-s -w" \
        -tags='no_postgres no_clickhouse no_mssql no_mysql' \
        -o goose ./cmd/goose
    
[/code]

We're still only targeting `sqlite` and reduced the binary to **~6.6M**.

You can go further with a tool called `upx`, for more info check out [Shrink your go binaries with this one weird trick](<https://words.filippo.io/shrink-your-go-binaries-with-this-one-weird-trick/>).

Back to top

