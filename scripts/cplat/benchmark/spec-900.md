---
spec_id: 900-count-todos-with-get-todos-count
title: Count the todos with GET /todos/count
status: approved
priority: P2
shape: service-python
---

# 900 — Count the todos with GET /todos/count

This is the fixed spec of the platform benchmark (spec 099). It must not change within a task version.

## Problem

A caller that only needs to know how many todos exist has to download the whole list with `GET /todos` and count it.
A small endpoint that returns the number saves that.

## Stories

- As a caller of todo-api, I want `GET /todos/count` to return how many todos exist, so that I do not have to download the list to count it.

## Acceptance criteria

- **AC-900.1** Given three todos, when a caller sends `GET /todos/count`, then the response is `200` with the JSON body `{"count": 3}` and `Content-Type: application/json`.
- **AC-900.2** Given no todos, when a caller sends `GET /todos/count`, then the response is `200` with the JSON body `{"count": 0}`. The new route does not shadow the id routes: `PATCH /todos/count` with a valid body (`{"done": true}`) and `DELETE /todos/count` answer `404` with the existing `todo_not_found` error, exactly as for any unknown id. The existing endpoints do not change.

## Non-goals

- Filtering (by done state or title), paging, or any change to the other endpoints.
- A gitops, configuration or schema change.

## Open questions

None.

## Changelog

- 2026-10-25 created
- 2026-10-25 approved
