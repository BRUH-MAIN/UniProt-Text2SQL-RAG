| case | what it does | legacy guard | legacy: SELECT-only role | legacy: privileged role | hardened (any role) |
|---|---|---|---|---|---|
| `ctl_select` | plain SELECT | passes | ran, 3 rows | ran, 3 rows | ran, 3 rows |
| `ctl_cte` | read-only CTE | passes | ran, 3 rows | ran, 3 rows | ran, 3 rows |
| `ctl_semicolon_in_literal` | ';' inside a string literal | passes | ran, 1 rows | ran, 1 rows | ran, 1 rows |
| `w_cte_delete` | data-modifying CTE (DELETE) | passes | db error: InsufficientPrivilege: permission denied for table genes | ran, 1 rows | BLOCKED by guard |
| `w_cte_insert` | data-modifying CTE (INSERT) | passes | db error: InsufficientPrivilege: permission denied for table genes | ran, 1 rows | BLOCKED by guard |
| `w_cte_update` | data-modifying CTE (UPDATE) | passes | db error: InsufficientPrivilege: permission denied for table genes | ran, 1 rows | BLOCKED by guard |
| `w_with_delete_tail` | WITH ... DELETE (SELECT only inside the CTE) | **blocks** | BLOCKED by guard | BLOCKED by guard | BLOCKED by guard |
| `w_select_into` | SELECT ... INTO creates a table | passes | db error: InsufficientPrivilege: permission denied for schema public | EXECUTED (a write; no rows to fetch) | BLOCKED by guard |
| `w_for_update` | SELECT ... FOR UPDATE takes row locks | passes | db error: InsufficientPrivilege: permission denied for table genes | ran, 1 rows | BLOCKED by guard |
| `w_stacked` | stacked statements | **blocks** | BLOCKED by guard | BLOCKED by guard | BLOCKED by guard |
| `w_leading_comment` | comment before DELETE | **blocks** | BLOCKED by guard | BLOCKED by guard | BLOCKED by guard |
| `w_explain_analyze` | EXPLAIN ANALYZE of a write | **blocks** | BLOCKED by guard | BLOCKED by guard | BLOCKED by guard |
| `w_copy_program` | COPY ... TO PROGRAM | **blocks** | BLOCKED by guard | BLOCKED by guard | BLOCKED by guard |
| `d_pg_sleep` | pg_sleep ties up a connection | passes | RAN >4s (no timeout) | RAN >4s (no timeout) | BLOCKED by guard |
| `d_cartesian` | cartesian product, never returns | passes | RAN >4s (no timeout) | RAN >4s (no timeout) | CANCELLED by server timeout |
| `d_unbounded_comment` | trailing comment swallows the appended LIMIT | passes | ran, 157683 rows | ran, 157683 rows | ran, 200 rows (capped) |
| `d_unbounded_subquery_limit` | LIMIT in a subquery defeats the LIMIT regex | passes | ran, 62820 rows | ran, 62820 rows | ran, 200 rows (capped) |
| `x_pg_read_file` | server-side file read | passes | db error: InsufficientPrivilege: permission denied for function pg_read_file | ran, 1 rows | BLOCKED by guard |
| `x_lo_import` | server-side large-object import | passes | db error: InsufficientPrivilege: permission denied for function lo_import | ran, 1 rows | BLOCKED by guard |
| `x_set_config` | change a session setting | passes | ran, 1 rows | ran, 1 rows | BLOCKED by guard |
| `x_pg_user` | enumerate DB roles | passes | ran, 3 rows | ran, 3 rows | BLOCKED by guard |

Hostile cases: 18. Legacy guard let 13 of them through to the database. Run as a privileged role, 13 of the hostile cases did something unwanted (executed a write, read a file, hung, or returned an unbounded result) under the legacy path; under the hardened path 0 write/exfiltration cases ran.
