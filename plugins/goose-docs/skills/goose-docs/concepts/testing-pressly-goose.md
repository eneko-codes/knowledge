# Testing - pressly/goose

> Source: https://pressly.github.io/goose/blog/category/testing

## [Better tests with containers](<https://pressly.github.io/goose/blog/2021/better-tests/>)

Managing state is hard. Managing database state is even harder. And coordinating state within a test suite is just always a bad time.

But it doesn't have to be this way!

There is a fantastic Go package called [ory/dockertest](<https://github.com/ory/dockertest>) that allows you to spin up ephemeral docker containers. It'll work both locally (assuming you have Docker installed) and in your Continuous Integration (CI) pipelines.

Back to top

