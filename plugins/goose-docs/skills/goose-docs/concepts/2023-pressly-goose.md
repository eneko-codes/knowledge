# 2023 - pressly/goose

> Source: https://pressly.github.io/goose/blog/archive/2023

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


Back to top

