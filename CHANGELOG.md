# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.11] - 2026-07-31
### Details
#### Fixed
- Drain re-entrant ibis reader on the blocking pool to avoid worker starvation by @mesejo in [#45](https://github.com/xorq-labs/xorq-datafusion/pull/45)

## [0.2.10] - 2026-07-02
### Details
#### Fixed
- Avoid nested runtime panic in wait_for_future by @mesejo in [#41](https://github.com/xorq-labs/xorq-datafusion/pull/41)
- Resolve ruff check violations across package and tests by @mesejo in [#42](https://github.com/xorq-labs/xorq-datafusion/pull/42)
- Unify execute_stream onto wait_for_future re-entry handoff by @dlovell in [#43](https://github.com/xorq-labs/xorq-datafusion/pull/43)

## [0.2.9] - 2026-06-09
### Details
#### Fixed
- SessionContext.sql re-entrancy panic (Already borrowed) by @mesejo in [#38](https://github.com/xorq-labs/xorq-datafusion/pull/38)
- Extend modified-method coverage to file/provider/metadata methods by @mesejo in [#39](https://github.com/xorq-labs/xorq-datafusion/pull/39)

## [0.2.8] - 2026-05-27
### Details
#### Added
- Add release profile optimizations to reduce binary size by @mesejo in [#34](https://github.com/xorq-labs/xorq-datafusion/pull/34)

#### Fixed
- Eliminate GIL/mutex deadlock in concurrent StreamCache scans by @mesejo in [#35](https://github.com/xorq-labs/xorq-datafusion/pull/35)

## [0.2.7] - 2026-05-14
### Details
#### Added
- Add tokio shutdown by @mesejo in [#32](https://github.com/xorq-labs/xorq-datafusion/pull/32)

#### Changed
- Upgrade DataFusion v51→v53, pyo3 0.26→0.28, arrow 57→58 by @mesejo in [#31](https://github.com/xorq-labs/xorq-datafusion/pull/31)

## [0.2.5] - 2025-12-17
### Details
#### Changed
- Update to v51 by @mesejo in [#28](https://github.com/xorq-labs/xorq-datafusion/pull/28)

## [0.2.4] - 2025-09-12
### Details
#### Changed
- Better error stacktraces by @mesejo in [#19](https://github.com/xorq-labs/xorq-datafusion/pull/19)
- Loosen pyarrow version by @mesejo in [#15](https://github.com/xorq-labs/xorq-datafusion/pull/15)

## [0.2.3] - 2025-06-30
### Details
#### Fixed
- Use vendored ibis for operations on PyTableProvider by @mesejo in [#17](https://github.com/xorq-labs/xorq-datafusion/pull/17)

## [0.2.2] - 2025-05-13
### Details
#### Added
- Support list of paths to read_csv or read_parquet by @mesejo in [#13](https://github.com/xorq-labs/xorq-datafusion/pull/13)

#### Changed
- Bump tokio from 1.44.1 to 1.44.2 by @dependabot[bot] in [#12](https://github.com/xorq-labs/xorq-datafusion/pull/12)

## New Contributors
* @dependabot[bot] made their first contribution in [#12](https://github.com/xorq-labs/xorq-datafusion/pull/12)
