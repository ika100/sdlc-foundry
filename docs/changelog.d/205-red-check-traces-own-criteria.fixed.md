**The red check of an amended spec no longer judges tests of other specs that share its test file (spec 205).** A test that names another spec's criterion (`# AC-189.1`), or that names none and was not added or changed by the build, took the amended spec's criteria from the whole file. Its pass then stopped the build. Now such a test is unjudged and must only pass ([spec 205](../specs/205-acceptance-tests-are-proven-passable/spec.md)).

Caused by: #1103
