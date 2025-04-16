SELECT 4 & 2 AS "BitwiseAnd(4, 2)"
SELECT CAST(CASE WHEN "t0"."int_col" = 0 THEN 42 ELSE -1 END AS BIGINT) AS "where_col" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('year', ARROW_CAST('2015-09-01 14:48:05.359000', 'Timestamp(Microsecond, None)')) AS "tmp"
SELECT LOWER("t0"."string_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT SUBSTRING("t0"."date_string_col" FROM CASE WHEN (-2 + 1) >= 1 THEN -2 + 1 ELSE -2 + 1 + LENGTH("t0"."date_string_col") END FOR 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE WHEN "t0"."string_col" IS NULL OR '\d+' IS NULL THEN NULL ELSE COALESCE(ARRAY_LENGTH(REGEXP_MATCH("t0"."string_col", '\d+')) > 0, FALSE) END AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT COUNT(*) AS "CountStar()" FROM (SELECT * FROM "functional_alltypes" AS "t0" LIMIT 2) AS "t1"
SELECT 'STRI''NG' AS """STRI'NG"""
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') <= ARROW_CAST('2010-03-02 00:00:00.000123', 'Timestamp(Microsecond, None)')
SELECT CASE WHEN 'a' IS NULL OR "t0"."string_col" IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT('a', "t0"."string_col") END AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", NULLIF("t0"."int_col", 1) AS "int_col", NULLIF("t0"."double_col", 3.0) AS "double_col", NULLIF("t0"."string_col", '2') AS "string_col" FROM "functional_alltypes" AS "t0"
SELECT CASE (DATE_PART('dow', CAST('2017-01-07' AS DATE)) + 6) % 7 WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday' WHEN 5 THEN 'Saturday' WHEN 6 THEN 'Sunday' END AS "tmp"
SELECT NOT ("t0"."bool_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ABS(-("t0"."double_col")) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ARROW_TYPEOF(NULL) AS "TypeOf(None)"
SELECT LEAST(10, 1) AS "tmp"
SELECT CAST(CONCAT_WS('-', CASE WHEN '20' IS NULL OR ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 2 + CAST(2 >= 0 AS SMALLINT)) IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT('20', ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 2 + CAST(2 >= 0 AS SMALLINT))) END, ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 0 + CAST(0 >= 0 AS SMALLINT)), ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 1 + CAST(1 >= 0 AS SMALLINT))) AS DATE) + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' day') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE WHEN CASE WHEN CASE WHEN 'a' IS NULL OR "t0"."string_col" IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT('a', "t0"."string_col") END IS NULL OR 'a' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN 'a' IS NULL OR "t0"."string_col" IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT('a', "t0"."string_col") END, 'a') END IS NULL OR '\d+' IS NULL THEN NULL ELSE COALESCE(ARRAY_LENGTH(REGEXP_MATCH(CASE WHEN CASE WHEN 'a' IS NULL OR "t0"."string_col" IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT('a', "t0"."string_col") END IS NULL OR 'a' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN 'a' IS NULL OR "t0"."string_col" IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT('a', "t0"."string_col") END, 'a') END, '\d+')) > 0, FALSE) END AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ARROW_CAST('2023-01-07 13:20:05.561', 'Timestamp(Millisecond, None)') AS "Cast('2023-01-07 13:20:05.561', timestamp(3))"
SELECT 1.0 AS "1.0"
SELECT FALSE AS "False"
SELECT HASH_INT("t0"."string_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT UPPER(CAST(NULL AS VARCHAR)) AS "Uppercase(Cast(None, string))"
SELECT "t0"."smallint_col", "t0"."int_col" FROM "functional_alltypes" AS "t0"
SELECT CAST(NULL AS DOUBLE PRECISION) AS "None"
SELECT "t0"."timestamp_col" + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' minute') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ENCODE(DIGEST("t0"."string_col", 'sha256'), 'hex') AS "HexDigest(string_col)" FROM "functional_alltypes" AS "t0" ORDER BY "t0"."id" ASC LIMIT 10
SELECT "t0"."id" + 0 AS "c_0", "t0"."id" + 1 AS "c_1", "t0"."id" + 2 AS "c_2" FROM "functional_alltypes" AS "t0" LIMIT 11
SELECT SUBSTRING("t0"."date_string_col" FROM CASE WHEN ((CHARACTER_LENGTH("t0"."date_string_col") - 2) + 1) >= 1 THEN (CHARACTER_LENGTH("t0"."date_string_col") - 2) + 1 ELSE (CHARACTER_LENGTH("t0"."date_string_col") - 2) + 1 + LENGTH("t0"."date_string_col") END FOR (CHARACTER_LENGTH("t0"."date_string_col") - 1) - (CHARACTER_LENGTH("t0"."date_string_col") - 2)) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST("t0"."float_col" AS DOUBLE PRECISION) / 0.0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ASIN(0.0) AS "tmp"
SELECT "t0"."id", "t0"."string_col" IN ('1', '2', '3') AS "tmp" FROM "functional_alltypes" AS "t0" ORDER BY "t0"."id" ASC
SELECT COS(NULLIF(CAST("t0"."double_col" AS DOUBLE PRECISION) / 90.9, 0)) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", NOT ("t0"."string_col" IN ('1', '2', '3')) AS "tmp" FROM "functional_alltypes" AS "t0" ORDER BY "t0"."id" ASC
SELECT "t0"."playerID", "t0"."yearID" FROM "batting" AS "t0" WHERE "t0"."yearID" = (SELECT MAX("t1"."yearID") AS "Max(yearID)" FROM (SELECT * FROM "batting" AS "t0" WHERE "t0"."yearID" <= 2000) AS "t1")
SELECT CAST('NaN' AS DOUBLE PRECISION) AS "nan_col", CAST(NULL AS DOUBLE PRECISION) AS "none_col" FROM "functional_alltypes" AS "t0"
SELECT REGEXP_MATCH("t0"."date_string_col", CONCAT('(', '(\d+)\D(\d+)\D(\d+)', ')'))[3] AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT STRPOS("t0"."string_col", '6') > 0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT LEAST("t0"."bigint_col", "t0"."int_col", -2) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST('+Inf' AS DOUBLE PRECISION) IS NOT NULL AND ISNAN(CAST('+Inf' AS DOUBLE PRECISION)) AS "tmp"
SELECT CAST('2022-02-24' AS DATE) AS "Cast('2022-02-24', date)"
SELECT 'STRING' AS "'STRING'"
SELECT EXP(1) AS "E()"
SELECT DATE_BIN(INTERVAL '5 MINUTES', "t0"."timestamp_col") AS "TimestampBucket(timestamp_col, 5m)" FROM "functional_alltypes" AS "t0"
SELECT ABS("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT * FROM "functional_alltypes" AS "t0" WHERE FALSE
SELECT * FROM "functional_alltypes" AS "t0" WHERE "t0"."id" < 100 ORDER BY "t0"."id" DESC NULLS LAST
SELECT LOG(5.556) AS "tmp"
SELECT REPEAT("t0"."string_col", 2) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ASCII("t0"."string_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT * FROM "functional_alltypes" AS "t0" WHERE "t0"."id" < 100 ORDER BY "t0"."id" ASC, "t0"."int_col" ASC
SELECT PI() AS "Pi()"
SELECT CASE WHEN NULLIF("t0"."int_col", 1) < 0 THEN 0 ELSE NULLIF("t0"."int_col", 1) END AS "Clip(NullIf(int_col, 1), 0)" FROM "functional_alltypes" AS "t0"
SELECT CONCAT_WS('-', 'a', "t0"."string_col", 'c') AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT RIGHT("t0"."date_string_col", 2) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST("t0"."float_col" AS DOUBLE PRECISION) / 0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", NOT ("t0"."int_col" IN (1)) AS "tmp" FROM "functional_alltypes" AS "t0" ORDER BY "t0"."id" ASC
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') <> ARROW_CAST('2010-03-02 00:00:00+00:00', 'Timestamp(Microsecond, Some("UTC"))')
SELECT "t0"."double_col" IS NOT NULL AND ISNAN("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT COUNT(*) AS "CountStar()" FROM (SELECT * FROM "functional_alltypes" AS "t0" LIMIT 1 OFFSET 3) AS "t1"
SELECT "t0"."yearID", "t0"."stint" FROM "batting" AS "t0" ORDER BY "t0"."yearID" ASC, "t0"."stint" DESC NULLS LAST
SELECT DATE_PART('week', "t0"."timestamp_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('month', "t0"."timestamp_col") AS "month" FROM "functional_alltypes" AS "t0"
SELECT "t0"."int_col" & "t0"."int_col" AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT 3 << "t0"."int_col" AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ABS(-5) AS "tmp"
SELECT DATE_TRUNC('DAY', "t0"."timestamp_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT COT(NULLIF(CAST("t0"."double_col" AS DOUBLE PRECISION) / 90.9, 0)) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."date_string_col" AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT MIN("t0"."smallint_col") AS "Min(smallint_col)" FROM "functional_alltypes" AS "t0"
SELECT CAST(NULL AS TIME) AS "None"
SELECT COALESCE(NULLIF(STRPOS(SUBSTR("t0"."date_string_col", 3 + 1), '13') + 3, 3), 0) - 1 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."double_col" % ("t0"."smallint_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", DATE_TRUNC('DAY', "t0"."timestamp_col") + CAST(CONCAT(CAST("t0"."bigint_col" AS VARCHAR), ' day') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('day', CAST("t0"."timestamp_col" AS DATE)) AS "day" FROM "functional_alltypes" AS "t0"
SELECT CAST(NULL AS BYTEA) AS "None"
SELECT * FROM "functional_alltypes" AS "t0" WHERE NOT (CHARACTER_LENGTH("t0"."string_col") * 1 IN (1))
SELECT * FROM (SELECT CASE WHEN "t0"."int_col" = 2 THEN NULL ELSE "t0"."float_col" END AS "col_1", CASE WHEN "t0"."int_col" = 4 THEN NULL ELSE "t0"."float_col" END AS "col_2", CASE WHEN ("t0"."int_col" = 2) OR ("t0"."int_col" = 4) THEN NULL ELSE "t0"."float_col" END AS "col_3" FROM "functional_alltypes" AS "t0") AS "t1" WHERE "t1"."col_1" IS NOT NULL OR "t1"."col_3" IS NOT NULL
SELECT * FROM "functional_alltypes" AS "t0" WHERE "t0"."bool_col" ORDER BY "t0"."id" ASC
SELECT DATE_TRUNC('MONTH', "t0"."timestamp_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."double_col" + ("t0"."smallint_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT SUBSTRING("t0"."date_string_col" FROM CASE WHEN (1 + 1) >= 1 THEN 1 + 1 ELSE 1 + 1 + LENGTH("t0"."date_string_col") END FOR 2) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."int_col", "t0"."string_col" FROM "functional_alltypes" AS "t0" WHERE "t0"."string_col" = '4'
SELECT DATE_TRUNC('MINUTE', "t0"."timestamp_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT (DATE_PART('dow', CAST('2017-01-01' AS DATE)) + 6) % 7 AS "tmp"
SELECT REGEXP_REPLACE('aba', 'a', 'c', 'g') AS "RegexReplace('aba', 'a', 'c')"
SELECT DATE_PART('doy', "t0"."timestamp_col") AS "day_of_year" FROM "functional_alltypes" AS "t0"
SELECT CAST(NULL AS REAL) AS "None"
SELECT "t0"."bool_col" AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT 4 >> 2 AS "BitwiseRightShift(4, 2)"
SELECT CASE WHEN "t0"."int_col" < 0 THEN 0 WHEN "t0"."int_col" > 1.0 THEN 1.0 ELSE "t0"."int_col" END AS "Clip(int_col, 0, 1.0)" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", CAST(NULL AS DOUBLE PRECISION) AS "missing" FROM "functional_alltypes" AS "t0"
SELECT ATAN(0.0) AS "tmp"
SELECT CASE WHEN 'foo' = 'foo' THEN 'FOO' WHEN 'foo' = 'bar' THEN 'BAR' ELSE 'foo' END AS "SearchedCase((Equals('foo', 'foo'), Equals('foo', 'bar')), ('FOO', 'BAR'), 'foo')"
SELECT CAST('NaN' AS DOUBLE PRECISION) AS "nan_col", CAST(NULL AS DOUBLE PRECISION) AS "none_col" FROM "functional_alltypes" AS "t0" WHERE CAST(NULL AS DOUBLE PRECISION) IS NULL
SELECT DATE_TRUNC('HOUR', "t0"."timestamp_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST(NULL AS DATE) AS "None"
SELECT SUBSTRING("t0"."date_string_col" FROM CASE WHEN (2 + 1) >= 1 THEN 2 + 1 ELSE 2 + 1 + LENGTH("t0"."date_string_col") END FOR 3) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."G" FROM "batting" AS "t0"
SELECT CAST(NULL AS TIMESTAMP) AS "None"
SELECT CAST("t0"."bigint_col" AS DOUBLE PRECISION) / 0.0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('quarter', "t0"."timestamp_col") AS "quarter" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('month', DATE_TRUNC('DAY', "t0"."timestamp_col")) AS "month" FROM "functional_alltypes" AS "t0"
SELECT "t0"."double_col" - ("t0"."smallint_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_BIN(INTERVAL '2 DAYS', "t0"."timestamp_col") AS "TimestampBucket(timestamp_col, 2D)" FROM "functional_alltypes" AS "t0"
SELECT DATE_BIN(INTERVAL '2 HOURS', "t0"."timestamp_col") AS "TimestampBucket(timestamp_col, 2h)" FROM "functional_alltypes" AS "t0"
SELECT COUNT(*) AS "CountStar()" FROM (SELECT * FROM "functional_alltypes" AS "t0") AS "t1"
SELECT ACOS(0.0) AS "tmp"
SELECT EXP(5.556) AS "tmp"
SELECT LOG(2, 5.556) AS "tmp"
SELECT "t0"."float_col" IS NOT NULL AND ISNAN("t0"."float_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT 'STRI"NG' AS "'STRI""NG'"
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') = ARROW_CAST('2010-03-02 00:00:00+00:00', 'Timestamp(Microsecond, Some("UTC"))')
SELECT DATE_BIN(INTERVAL '5 MINUTES', "t0"."timestamp_col", ARROW_CAST('1970-01-01T00:00:00Z', 'Timestamp(Nanosecond, None)') - INTERVAL '-3 HOURS') AS "TimestampBucket(timestamp_col, 5m, -2h)" FROM "functional_alltypes" AS "t0"
SELECT "t0"."int_col" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('hour', ARROW_CAST('2015-09-01 14:48:05.359000', 'Timestamp(Microsecond, None)')) AS "tmp"
SELECT STRPOS("t0"."string_col", 'a') - 1 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ATAN2(0.0, 1.0) AS "tmp"
SELECT CASE WHEN CAST(FLOOR(CAST(("t0"."int_col" - (MIN("t0"."int_col") OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - 1e-13)) AS DOUBLE PRECISION) / (CAST((MAX("t0"."int_col") OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - (MIN("t0"."int_col") OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - 1e-13)) AS DOUBLE PRECISION) / 10)) AS BIGINT) < -1 THEN -1 WHEN CAST(FLOOR(CAST(("t0"."int_col" - (MIN("t0"."int_col") OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - 1e-13)) AS DOUBLE PRECISION) / (CAST((MAX("t0"."int_col") OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - (MIN("t0"."int_col") OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - 1e-13)) AS DOUBLE PRECISION) / 10)) AS BIGINT) > 9 THEN 9 ELSE CAST(FLOOR(CAST(("t0"."int_col" - (MIN("t0"."int_col") OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - 1e-13)) AS DOUBLE PRECISION) / (CAST((MAX("t0"."int_col") OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - (MIN("t0"."int_col") OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - 1e-13)) AS DOUBLE PRECISION) / 10)) AS BIGINT) END AS "hist" FROM "functional_alltypes" AS "t0"
SELECT LPAD("t0"."string_col", 10, 'a') AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT REGEXP_MATCH("t0"."date_string_col", CONCAT('(', '(\d+)\D(\d+)\D(\d+)', ')'))[4] AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST("t0"."double_col" AS DOUBLE PRECISION) / 0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT * FROM (SELECT CASE WHEN "t0"."int_col" = 2 THEN NULL ELSE "t0"."float_col" END AS "col_1", CASE WHEN "t0"."int_col" = 4 THEN NULL ELSE "t0"."float_col" END AS "col_2", CASE WHEN ("t0"."int_col" = 2) OR ("t0"."int_col" = 4) THEN NULL ELSE "t0"."float_col" END AS "col_3" FROM "functional_alltypes" AS "t0") AS "t1" WHERE "t1"."col_1" IS NOT NULL
SELECT * FROM (SELECT CASE WHEN "t0"."int_col" = 2 THEN NULL ELSE "t0"."float_col" END AS "col_1", CASE WHEN "t0"."int_col" = 4 THEN NULL ELSE "t0"."float_col" END AS "col_2", CASE WHEN ("t0"."int_col" = 2) OR ("t0"."int_col" = 4) THEN NULL ELSE "t0"."float_col" END AS "col_3" FROM "functional_alltypes" AS "t0") AS "t1" WHERE "t1"."col_1" IS NOT NULL OR "t1"."col_2" IS NOT NULL
SELECT "t0"."bool_col", "t0"."string_col", "t0"."bool_col" AS "dupe_col" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('hour', "t0"."timestamp_col") AS "hour" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", COALESCE(CAST(NULL AS DOUBLE PRECISION), 0.0) AS "missing" FROM "functional_alltypes" AS "t0"
SELECT TRUE AS "tmp"
SELECT * FROM "batting"
SELECT CAST("t0"."tinyint_col" AS DOUBLE PRECISION) / 0.0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT TAN(0.0) AS "tmp"
SELECT 2 & 4 AS "BitwiseAnd(2, 4)"
SELECT REGEXP_MATCH(CASE WHEN "t0"."string_col" IS NULL OR '1' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT("t0"."string_col", '1') END, CONCAT('(', '\d(\d+)', ')'))[1] AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT COUNT(*) AS "CountStar()" FROM (SELECT * FROM "functional_alltypes" AS "t0" WHERE "t0"."int_col" >= 2) AS "t1"
SELECT SIN(0.0) AS "tmp"
SELECT REPLACE("t0"."string_col", '1', '42') AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE (DATE_PART('dow', CAST('2017-01-05' AS DATE)) + 6) % 7 WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday' WHEN 5 THEN 'Saturday' WHEN 6 THEN 'Sunday' END AS "tmp"
SELECT * FROM (SELECT CASE WHEN "t0"."int_col" = 2 THEN NULL ELSE "t0"."float_col" END AS "col_1", CASE WHEN "t0"."int_col" = 4 THEN NULL ELSE "t0"."float_col" END AS "col_2", CASE WHEN ("t0"."int_col" = 2) OR ("t0"."int_col" = 4) THEN NULL ELSE "t0"."float_col" END AS "col_3" FROM "functional_alltypes" AS "t0") AS "t1" WHERE "t1"."col_1" IS NOT NULL AND "t1"."col_2" IS NOT NULL
SELECT CAST(CONCAT_WS('-', CASE WHEN '20' IS NULL OR ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 2 + CAST(2 >= 0 AS SMALLINT)) IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT('20', ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 2 + CAST(2 >= 0 AS SMALLINT))) END, ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 0 + CAST(0 >= 0 AS SMALLINT)), ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 1 + CAST(1 >= 0 AS SMALLINT))) AS DATE) + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' month') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT MEDIAN("t0"."G") AS "median_0(G)" FROM "batting" AS "t0"
SELECT "t0"."int_col" | 3 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT * FROM "functional_alltypes" AS "t0" WHERE "t0"."int_col" >= 2 LIMIT 1
SELECT "t0"."date_string_col" FROM "functional_alltypes" AS "t0"
SELECT REVERSE("t0"."string_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT 1 AS "x" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('year', "t0"."timestamp_col") AS "year" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('year', DATE_TRUNC('DAY', "t0"."timestamp_col")) AS "year" FROM "functional_alltypes" AS "t0"
SELECT "t0"."yearID", "t0"."stint" FROM "batting" AS "t0"
SELECT "t0"."timestamp_col" + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' year') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_TRUNC('YEAR', "t0"."timestamp_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id" FROM "functional_alltypes" AS "t0" LIMIT 11
SELECT REGEXP_REPLACE("t0"."string_col", '[[:digit:]]+', 'a', 'g') AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT * FROM "functional_alltypes" AS "t0" WHERE "t0"."id" < 100 ORDER BY "t0"."id" ASC
SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", CAST(CASE WHEN "t0"."int_col" = 1 THEN 20 WHEN "t0"."int_col" = 0 THEN 10 ELSE 0 END AS BIGINT) AS "new_col" FROM "functional_alltypes" AS "t0"
SELECT ATAN2(NULLIF(CAST("t0"."double_col" AS DOUBLE PRECISION) / 90.9, 0), NULLIF(CAST("t0"."double_col" AS DOUBLE PRECISION) / 90.9, 0)) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE (DATE_PART('dow', ARROW_CAST('2015-09-01 14:48:05.359000', 'Timestamp(Microsecond, None)')) + 6) % 7 WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday' WHEN 5 THEN 'Saturday' WHEN 6 THEN 'Sunday' END AS "tmp"
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') >= ARROW_CAST('2010-03-02 00:00:00.000123', 'Timestamp(Microsecond, None)')
SELECT (DATE_PART('dow', CAST('2017-01-05' AS DATE)) + 6) % 7 AS "tmp"
SELECT SUBSTRING("t0"."date_string_col" FROM CASE WHEN (0 + 1) >= 1 THEN 0 + 1 ELSE 0 + 1 + LENGTH("t0"."date_string_col") END FOR CHARACTER_LENGTH("t0"."date_string_col")) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ARROW_TYPEOF(1) AS "TypeOf(1)"
SELECT CAST("t0"."double_col" AS DOUBLE PRECISION) / 0.0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", NULLIF("t0"."int_col", 1) AS "int_col", COALESCE(NULLIF("t0"."double_col", 3.0), -1.5) AS "double_col", COALESCE(NULLIF("t0"."string_col", '2'), 'missing') AS "string_col" FROM "functional_alltypes" AS "t0"
SELECT 11 % 3 AS "tmp"
SELECT CAST("t0"."smallint_col" AS DOUBLE PRECISION) / 0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t1"."int_col" FROM (SELECT "t0"."string_col", SUM("t0"."int_col") AS "int_col" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."string_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."string_col") AS "t1"
SELECT ARROW_CAST('2419-10-11 10:10:25', 'Timestamp(Microsecond, None)') AS "tmp"
SELECT * FROM "functional_alltypes" AS "t0" WHERE "t0"."id" < 100 ORDER BY "t0"."id" ASC, "t0"."int_col" DESC NULLS LAST
SELECT ASIN(NULLIF(CAST("t0"."double_col" AS DOUBLE PRECISION) / 90.9, 0)) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CHARACTER_LENGTH("t0"."string_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT STARTS_WITH(CASE "t0"."int_col" WHEN 1 THEN 'abcd' WHEN 2 THEN 'ABCD' ELSE 'dabc' END, 'abc') AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT TRANSLATE("t0"."string_col", '01', 'ab') AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT 1 AS "1"
SELECT * FROM (SELECT CASE WHEN "t0"."int_col" = 2 THEN NULL ELSE "t0"."float_col" END AS "col_1", CASE WHEN "t0"."int_col" = 4 THEN NULL ELSE "t0"."float_col" END AS "col_2", CASE WHEN ("t0"."int_col" = 2) OR ("t0"."int_col" = 4) THEN NULL ELSE "t0"."float_col" END AS "col_3" FROM "functional_alltypes" AS "t0") AS "t1" WHERE "t1"."col_1" IS NOT NULL AND "t1"."col_2" IS NOT NULL AND "t1"."col_3" IS NOT NULL
SELECT REGEXP_REPLACE("t0"."string_col", '\d+', 'a', 'g') AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT RPAD("t0"."string_col", 10, 'a') AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."int_col" << 3 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST('1.1' AS DECIMAL(38, 9)) AS "Decimal('1.1')"
SELECT (DATE_PART('dow', CAST('2017-01-07' AS DATE)) + 6) % 7 AS "tmp"
SELECT CAST("t0"."bigint_col" AS DOUBLE PRECISION) / 0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST(FLOOR(5.556) AS BIGINT) AS "tmp"
SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", TO_TIMESTAMP("t0"."date_string_col", '%m/%d/%y') AS "date" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", SUBSTRING(CASE WHEN "t0"."bool_col" THEN "t0"."string_col" ELSE NULL END FROM CASE WHEN (0 + 1) >= 1 THEN 0 + 1 ELSE 0 + 1 + LENGTH(CASE WHEN "t0"."bool_col" THEN "t0"."string_col" ELSE NULL END) END FOR 2) AS "substr_col_null" FROM "functional_alltypes" AS "t0"
SELECT CASE WHEN TRUE THEN '%' ELSE NULL END AS "SearchedCase((True,), ('%',), None)"
SELECT CAST("t0"."int_col" AS DOUBLE PRECISION) / 0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT (DATE_PART('dow', CAST('2017-01-02' AS DATE)) + 6) % 7 AS "tmp"
SELECT "t0"."timestamp_col" + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' day') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE WHEN UPPER(SUBSTRING('aBc' FROM CASE WHEN (0 + 1) >= 1 THEN 0 + 1 ELSE 0 + 1 + LENGTH('aBc') END FOR 1)) IS NULL OR LOWER(SUBSTRING('aBc' FROM CASE WHEN (1 + 1) >= 1 THEN 1 + 1 ELSE 1 + 1 + LENGTH('aBc') END FOR CHARACTER_LENGTH('aBc'))) IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(UPPER(SUBSTRING('aBc' FROM CASE WHEN (0 + 1) >= 1 THEN 0 + 1 ELSE 0 + 1 + LENGTH('aBc') END FOR 1)), LOWER(SUBSTRING('aBc' FROM CASE WHEN (1 + 1) >= 1 THEN 1 + 1 ELSE 1 + 1 + LENGTH('aBc') END FOR CHARACTER_LENGTH('aBc')))) END AS "Capitalize('aBc')"
SELECT CASE WHEN REGEXP_REPLACE('hi', 'i', 'a', 'g') = 'd' THEN 'b' ELSE 'k' END AS "SearchedCase((Equals(RegexReplace('hi', 'i', 'a'), 'd'),), ('b',), 'k')"
SELECT "t0"."int_col" FROM "functional_alltypes" AS "t0" WHERE "t0"."string_col" = '4'
SELECT CAST(NULL AS VARCHAR) AS "None"
SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", TO_DATE("t0"."date_string_col", '%m/%d/%y') AS "date" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", "t0"."int_col" IN (1) AS "tmp" FROM "functional_alltypes" AS "t0" ORDER BY "t0"."id" ASC
SELECT "t0"."int_col" >> 3 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('month', CAST("t0"."timestamp_col" AS DATE)) AS "month" FROM "functional_alltypes" AS "t0"
SELECT REGEXP_MATCH("t0"."date_string_col", CONCAT('(', '^(\d+)', ')'))[2] AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE WHEN "t0"."int_col" < 0.0 THEN 0.0 ELSE "t0"."int_col" END AS "Clip(int_col, 0.0)" FROM "functional_alltypes" AS "t0"
SELECT HASH_INT('aBc') AS "Hash('aBc')"
SELECT "t0"."int_col" >> "t0"."int_col" AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT * FROM (SELECT CASE WHEN "t0"."int_col" = 2 THEN NULL ELSE "t0"."float_col" END AS "col_1", CASE WHEN "t0"."int_col" = 4 THEN NULL ELSE "t0"."float_col" END AS "col_2", CASE WHEN ("t0"."int_col" = 2) OR ("t0"."int_col" = 4) THEN NULL ELSE "t0"."float_col" END AS "col_3" FROM "functional_alltypes" AS "t0") AS "t1" WHERE "t1"."col_1" IS NOT NULL AND "t1"."col_3" IS NOT NULL
SELECT SQRT(5.556) AS "tmp"
SELECT COALESCE(NULLIF("t0"."int_col", 1), 0) AS "int_col", COALESCE(NULLIF("t0"."double_col", 3.0), 0) AS "double_col" FROM "functional_alltypes" AS "t0"
SELECT SIN(NULLIF(CAST("t0"."double_col" AS DOUBLE PRECISION) / 90.9, 0)) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('day', "t0"."timestamp_col") AS "day" FROM "functional_alltypes" AS "t0"
SELECT LN("t0"."double_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT COS(0.0) AS "tmp"
SELECT "t0"."timestamp_col" + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' millisecond') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT 4 << 2 AS "BitwiseLeftShift(4, 2)"
SELECT CAST(CEIL(5.556) AS BIGINT) AS "tmp"
SELECT CAST("t0"."smallint_col" AS DOUBLE PRECISION) / 0.0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_BIN(INTERVAL '5 MINUTES', "t0"."timestamp_col", ARROW_CAST('1970-01-01T00:00:00Z', 'Timestamp(Nanosecond, None)') - INTERVAL '3 HOURS') AS "TimestampBucket(timestamp_col, 5m, 2h)" FROM "functional_alltypes" AS "t0"
SELECT CAST("t0"."tinyint_col" AS DOUBLE PRECISION) / 0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col" FROM "functional_alltypes" AS "t0" LIMIT 11
SELECT CAST(NULL AS INT) AS "None"
SELECT COALESCE(NULL, 5) AS "Coalesce((None, 5))"
SELECT CASE WHEN "t0"."string_col" IS NULL OR 'a' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT("t0"."string_col", 'a') END AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST(CEIL("t0"."double_col") AS BIGINT) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST("t0"."double_col" AS DOUBLE PRECISION) / ("t0"."smallint_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST(CASE WHEN CASE WHEN CASE WHEN CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END IS NULL OR LPAD(CAST("t0"."month" AS VARCHAR), 2, '0') IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END, LPAD(CAST("t0"."month" AS VARCHAR), 2, '0')) END IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END IS NULL OR LPAD(CAST("t0"."month" AS VARCHAR), 2, '0') IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END, LPAD(CAST("t0"."month" AS VARCHAR), 2, '0')) END, '-') END IS NULL OR LPAD(CAST("t0"."int_col" + 1 AS VARCHAR), 2, '0') IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN CASE WHEN CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END IS NULL OR LPAD(CAST("t0"."month" AS VARCHAR), 2, '0') IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END, LPAD(CAST("t0"."month" AS VARCHAR), 2, '0')) END IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END IS NULL OR LPAD(CAST("t0"."month" AS VARCHAR), 2, '0') IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END, LPAD(CAST("t0"."month" AS VARCHAR), 2, '0')) END, '-') END, LPAD(CAST("t0"."int_col" + 1 AS VARCHAR), 2, '0')) END AS DATE) = DATE_TRUNC('DAY', '2010-11-01') AS "result" FROM "functional_alltypes" AS "t0"
SELECT TO_HEX(42) AS "to_hex_0(42)"
SELECT COUNT(*) AS "CountStar(functional_alltypes)" FROM "functional_alltypes" AS "t0"
SELECT DATE_BIN(INTERVAL '5 MINUTES', "t0"."timestamp_col", ARROW_CAST('1970-01-01T00:00:00Z', 'Timestamp(Nanosecond, None)') - INTERVAL '3 MINUTES') AS "TimestampBucket(timestamp_col, 5m, 2m)" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id" + 0 AS "c_0", "t0"."id" + 1 AS "c_1", "t0"."id" + 2 AS "c_2", "t0"."id" + 3 AS "c_3", "t0"."id" + 4 AS "c_4", "t0"."id" + 5 AS "c_5", "t0"."id" + 6 AS "c_6", "t0"."id" + 7 AS "c_7", "t0"."id" + 8 AS "c_8", "t0"."id" + 9 AS "c_9", "t0"."id" + 10 AS "c_10", "t0"."id" + 11 AS "c_11", "t0"."id" + 12 AS "c_12", "t0"."id" + 13 AS "c_13", "t0"."id" + 14 AS "c_14", "t0"."id" + 15 AS "c_15", "t0"."id" + 16 AS "c_16", "t0"."id" + 17 AS "c_17", "t0"."id" + 18 AS "c_18", "t0"."id" + 19 AS "c_19", "t0"."id" + 20 AS "c_20", "t0"."id" + 21 AS "c_21", "t0"."id" + 22 AS "c_22", "t0"."id" + 23 AS "c_23", "t0"."id" + 24 AS "c_24", "t0"."id" + 25 AS "c_25", "t0"."id" + 26 AS "c_26", "t0"."id" + 27 AS "c_27", "t0"."id" + 28 AS "c_28", "t0"."id" + 29 AS "c_29", "t0"."id" + 30 AS "c_30", "t0"."id" + 31 AS "c_31", "t0"."id" + 32 AS "c_32", "t0"."id" + 33 AS "c_33", "t0"."id" + 34 AS "c_34", "t0"."id" + 35 AS "c_35", "t0"."id" + 36 AS "c_36", "t0"."id" + 37 AS "c_37", "t0"."id" + 38 AS "c_38", "t0"."id" + 39 AS "c_39", "t0"."id" + 40 AS "c_40", "t0"."id" + 41 AS "c_41", "t0"."id" + 42 AS "c_42", "t0"."id" + 43 AS "c_43", "t0"."id" + 44 AS "c_44", "t0"."id" + 45 AS "c_45", "t0"."id" + 46 AS "c_46", "t0"."id" + 47 AS "c_47", "t0"."id" + 48 AS "c_48", "t0"."id" + 49 AS "c_49" FROM "functional_alltypes" AS "t0" LIMIT 11
SELECT CAST('1.100000000' AS DECIMAL(38, 9)) AS "Decimal('1.100000000')"
SELECT "t0"."int_col", CAST(CASE WHEN "t0"."int_col" = 0 THEN 42 ELSE -1 END AS BIGINT) AS "where_col" FROM "functional_alltypes" AS "t0"
SELECT TAN(NULLIF(CAST("t0"."double_col" AS DOUBLE PRECISION) / 90.9, 0)) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT GREATEST("t0"."bigint_col", "t0"."int_col", -2) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT (DATE_PART('dow', CAST('2017-01-04' AS DATE)) + 6) % 7 AS "tmp"
SELECT COUNT(*) AS "CountStar()" FROM (SELECT * FROM "functional_alltypes" AS "t0" LIMIT 0 OFFSET 3) AS "t1"
SELECT LN(5.556) AS "tmp"
SELECT SUBSTRING("t0"."date_string_col" FROM CASE WHEN (2 + 1) >= 1 THEN 2 + 1 ELSE 2 + 1 + LENGTH("t0"."date_string_col") END) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ROUND(5.556, 2) AS "tmp"
SELECT POW("t0"."double_col", ("t0"."smallint_col" + 1)) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE WHEN "t0"."string_col" IS NULL OR "t0"."date_string_col" IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT("t0"."string_col", "t0"."date_string_col") END AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE WHEN "t0"."string_col" IS NULL OR '0|1|2|3|4|5|6|7|8|9' IS NULL THEN NULL ELSE COALESCE(ARRAY_LENGTH(REGEXP_MATCH("t0"."string_col", '0|1|2|3|4|5|6|7|8|9')) > 0, FALSE) END AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."int_col" << "t0"."int_col" AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", NULLIF("t0"."int_col", 1) AS "int_col", COALESCE(NULLIF("t0"."double_col", 3.0), -1) AS "double_col", COALESCE(NULLIF("t0"."string_col", '2'), 'missing') AS "string_col" FROM "functional_alltypes" AS "t0"
SELECT GREATEST("t0"."bigint_col", "t0"."int_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT LOG("t0"."double_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST(FLOOR("t0"."double_col") AS BIGINT) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT REGEXP_MATCH("t0"."date_string_col", CONCAT('(', '(\d+)$', ')'))[2] AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT NOT (TRUE) AS "tmp"
SELECT GREATEST(10, 1) AS "tmp"
SELECT "t0"."yearID", "t0"."stint" FROM "batting" AS "t0" ORDER BY "t0"."yearID" ASC
SELECT SUBSTRING("t0"."date_string_col" FROM CASE WHEN (0 + 1) >= 1 THEN 0 + 1 ELSE 0 + 1 + LENGTH("t0"."date_string_col") END FOR 2) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."int_col" & 3 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT COALESCE(5, NULL, 4) AS "tmp"
SELECT DATE_TRUNC('DAY', "t0"."timestamp_col") + CAST(CONCAT(CAST(10 AS VARCHAR), ' day') AS INTERVAL) AS "result" FROM "functional_alltypes" AS "t0"
SELECT * FROM "functional_alltypes" AS "t0" WHERE NOT (FALSE)
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') < ARROW_CAST('2010-03-02 00:00:00+00:00', 'Timestamp(Microsecond, Some("UTC"))')
SELECT CAST(CASE WHEN CASE WHEN CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END IS NULL OR LPAD(CAST("t0"."month" AS VARCHAR), 2, '0') IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END, LPAD(CAST("t0"."month" AS VARCHAR), 2, '0')) END IS NULL OR '-13' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END IS NULL OR LPAD(CAST("t0"."month" AS VARCHAR), 2, '0') IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CASE WHEN CAST("t0"."year" AS VARCHAR) IS NULL OR '-' IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(CAST("t0"."year" AS VARCHAR), '-') END, LPAD(CAST("t0"."month" AS VARCHAR), 2, '0')) END, '-13') END AS DATE) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT COUNT(*) AS "CountStar()" FROM (SELECT * FROM "functional_alltypes" AS "t0" LIMIT 0) AS "t1"
SELECT CASE WHEN "t0"."int_col" < 0 THEN 0 ELSE "t0"."int_col" END AS "Clip(int_col, 0)" FROM "functional_alltypes" AS "t0"
SELECT "t0"."timestamp_col" FROM "functional_alltypes" AS "t0"
SELECT ABS(5) AS "tmp"
SELECT "t0"."timestamp_col" + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' month') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE WHEN UPPER(SUBSTRING("t0"."string_col" FROM CASE WHEN (0 + 1) >= 1 THEN 0 + 1 ELSE 0 + 1 + LENGTH("t0"."string_col") END FOR 1)) IS NULL OR LOWER(SUBSTRING("t0"."string_col" FROM CASE WHEN (1 + 1) >= 1 THEN 1 + 1 ELSE 1 + 1 + LENGTH("t0"."string_col") END FOR CHARACTER_LENGTH("t0"."string_col"))) IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT(UPPER(SUBSTRING("t0"."string_col" FROM CASE WHEN (0 + 1) >= 1 THEN 0 + 1 ELSE 0 + 1 + LENGTH("t0"."string_col") END FOR 1)), LOWER(SUBSTRING("t0"."string_col" FROM CASE WHEN (1 + 1) >= 1 THEN 1 + 1 ELSE 1 + 1 + LENGTH("t0"."string_col") END FOR CHARACTER_LENGTH("t0"."string_col")))) END AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_TRUNC('SECOND', "t0"."timestamp_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT (DATE_PART('dow', CAST('2017-01-03' AS DATE)) + 6) % 7 AS "tmp"
SELECT CASE WHEN "t0"."int_col" < ("t0"."int_col" - 1) THEN "t0"."int_col" - 1 WHEN "t0"."int_col" > ("t0"."int_col" + 1) THEN "t0"."int_col" + 1 ELSE "t0"."int_col" END AS "Clip(int_col, Subtract(int_col, 1), Add(int_col, 1))" FROM "functional_alltypes" AS "t0"
SELECT CASE WHEN "t0"."string_col" IS NULL OR '[[:digit:]]+' IS NULL THEN NULL ELSE COALESCE(ARRAY_LENGTH(REGEXP_MATCH("t0"."string_col", '[[:digit:]]+')) > 0, FALSE) END AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE (DATE_PART('dow', CAST('2017-01-06' AS DATE)) + 6) % 7 WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday' WHEN 5 THEN 'Saturday' WHEN 6 THEN 'Sunday' END AS "tmp"
SELECT "t0"."timestamp_col" + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' second') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') <> ARROW_CAST('2010-03-02 00:00:00.000123', 'Timestamp(Microsecond, None)')
SELECT * FROM "functional_alltypes" AS "t0" WHERE CHARACTER_LENGTH("t0"."string_col") * 1 IN (1)
SELECT DATE_TRUNC('WEEK', "t0"."timestamp_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') <= ARROW_CAST('2010-03-02 00:00:00+00:00', 'Timestamp(Microsecond, Some("UTC"))')
SELECT ATAN(NULLIF(CAST("t0"."double_col" AS DOUBLE PRECISION) / 90.9, 0)) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_BIN(INTERVAL '2 SECONDS', "t0"."timestamp_col") AS "TimestampBucket(timestamp_col, 2s)" FROM "functional_alltypes" AS "t0"
SELECT "t0"."string_col" FROM "functional_alltypes" AS "t0"
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') >= ARROW_CAST('2010-03-02 00:00:00+00:00', 'Timestamp(Microsecond, Some("UTC"))')
SELECT CASE WHEN NULLIF("t0"."int_col", 1) > 0 THEN 0 ELSE NULLIF("t0"."int_col", 1) END AS "Clip(NullIf(int_col, 1), 0)" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('month', ARROW_CAST('2015-09-01 14:48:05.359000', 'Timestamp(Microsecond, None)')) AS "tmp"
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') = ARROW_CAST('2010-03-02 00:00:00.000123', 'Timestamp(Microsecond, None)')
SELECT * FROM (SELECT CASE WHEN "t0"."int_col" = 2 THEN NULL ELSE "t0"."float_col" END AS "col_1", CASE WHEN "t0"."int_col" = 4 THEN NULL ELSE "t0"."float_col" END AS "col_2", CASE WHEN ("t0"."int_col" = 2) OR ("t0"."int_col" = 4) THEN NULL ELSE "t0"."float_col" END AS "col_3" FROM "functional_alltypes" AS "t0") AS "t1" WHERE "t1"."col_1" IS NOT NULL OR "t1"."col_2" IS NOT NULL OR "t1"."col_3" IS NOT NULL
SELECT STARTS_WITH("t0"."date_string_col", '2010-01') AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT COALESCE(NULLIF("t0"."string_col", '2'), 'missing') AS "string_col" FROM "functional_alltypes" AS "t0"
SELECT * FROM "functional_alltypes" AS "t0" WHERE ("t0"."bool_col" AND (NOT "t0"."bool_col")) OR ((NOT "t0"."bool_col") AND "t0"."bool_col") ORDER BY "t0"."id" ASC
SELECT 3 >> "t0"."int_col" AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT (DATE_PART('dow', CAST('2017-01-06' AS DATE)) + 6) % 7 AS "tmp"
SELECT NULLIF(10, 5) AS "NullIf(10, 5)"
SELECT "t0"."smallint_col" % ("t0"."smallint_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST(CONCAT_WS('-', CASE WHEN '20' IS NULL OR ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 2 + CAST(2 >= 0 AS SMALLINT)) IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT('20', ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 2 + CAST(2 >= 0 AS SMALLINT))) END, ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 0 + CAST(0 >= 0 AS SMALLINT)), ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 1 + CAST(1 >= 0 AS SMALLINT))) AS DATE) + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' year') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."timestamp_col" + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' week') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."double_col" * ("t0"."smallint_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT SQRT("t0"."double_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST(FLOOR(CAST("t0"."double_col" AS DOUBLE PRECISION) / ("t0"."smallint_col" + 1)) AS BIGINT) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST(NULL AS BOOLEAN) AS "None"
SELECT DATE_PART('day', DATE_TRUNC('DAY', "t0"."timestamp_col")) AS "day" FROM "functional_alltypes" AS "t0"
SELECT ACOS(NULLIF(CAST("t0"."double_col" AS DOUBLE PRECISION) / 90.9, 0)) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT COALESCE(NULL, 4, NULL) AS "tmp"
SELECT "t0"."string_col", COUNT((DATE_PART('dow', "t0"."timestamp_col") + 6) % 7) AS "day_of_week_result" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."string_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."string_col"
SELECT CASE WHEN "t0"."int_col" < 0 THEN 0 WHEN "t0"."int_col" > 1 THEN 1 ELSE "t0"."int_col" END AS "Clip(int_col, 0, 1)" FROM "functional_alltypes" AS "t0"
SELECT CAST(NULL AS BIGINT) AS "None"
SELECT NULL AS "None"
SELECT "t0"."timestamp_col" + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' hour') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT COALESCE(5, 10) AS "Coalesce((5, 10))"
SELECT "t0"."string_col", SUM(CHARACTER_LENGTH(CASE (DATE_PART('dow', "t0"."timestamp_col") + 6) % 7 WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday' WHEN 5 THEN 'Saturday' WHEN 6 THEN 'Sunday' END)) AS "day_of_week_result" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."string_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."string_col"
SELECT CAST('NaN' AS DOUBLE PRECISION) IS NOT NULL AND ISNAN(CAST('NaN' AS DOUBLE PRECISION)) AS "tmp"
SELECT * FROM "functional_alltypes" AS "t0" WHERE "t0"."bool_col" OR "t0"."bool_col" ORDER BY "t0"."id" ASC
SELECT "t0"."timestamp_col" + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' microsecond') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT (DATE_PART('dow', ARROW_CAST('2015-09-01 14:48:05.359000', 'Timestamp(Microsecond, None)')) + 6) % 7 AS "tmp"
SELECT COUNT(*) AS "CountStar()" FROM (SELECT * FROM "functional_alltypes" AS "t0" OFFSET 3) AS "t1"
SELECT REGEXP_MATCH("t0"."string_col", CONCAT('(', '([[:digit:]]+)', ')'))[2] AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE (DATE_PART('dow', CAST('2017-01-03' AS DATE)) + 6) % 7 WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday' WHEN 5 THEN 'Saturday' WHEN 6 THEN 'Sunday' END AS "tmp"
SELECT 4 | 2 AS "BitwiseOr(4, 2)"
SELECT UPPER("t0"."string_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT DATE_PART('day', ARROW_CAST('2015-09-01 14:48:05.359000', 'Timestamp(Microsecond, None)')) AS "tmp"
SELECT LOG(2, "t0"."double_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT ARROW_CAST('4567-01-01 00:00:00', 'Timestamp(Microsecond, None)') AS "datetime.datetime(4567, 1, 1, 0, 0)"
SELECT REGEXP_MATCH("t0"."date_string_col", CONCAT('(', '(\d+)\D(\d+)\D(\d+)', ')'))[2] AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", NOT ("t0"."int_col" IN (1, 2, 3)) AS "tmp" FROM "functional_alltypes" AS "t0" ORDER BY "t0"."id" ASC
SELECT CASE WHEN "t0"."int_col" = 2 THEN NULL ELSE "t0"."float_col" END AS "col_1", CASE WHEN "t0"."int_col" = 4 THEN NULL ELSE "t0"."float_col" END AS "col_2", CASE WHEN ("t0"."int_col" = 2) OR ("t0"."int_col" = 4) THEN NULL ELSE "t0"."float_col" END AS "col_3" FROM "functional_alltypes" AS "t0" WHERE FALSE
SELECT DEGREES(5.556) AS "tmp"
SELECT * FROM (SELECT * FROM "functional_alltypes" AS "t0" WHERE "t0"."int_col" >= 2) AS "t1" WHERE RANDOM() <= 0.1
SELECT "t0"."id", COALESCE(NULLIF("t0"."int_col", 1), 20) AS "int_col", NULLIF("t0"."double_col", 3.0) AS "double_col", NULLIF("t0"."string_col", '2') AS "string_col" FROM "functional_alltypes" AS "t0"
SELECT CASE (DATE_PART('dow', CAST('2017-01-02' AS DATE)) + 6) % 7 WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday' WHEN 5 THEN 'Saturday' WHEN 6 THEN 'Sunday' END AS "tmp"
SELECT TO_TIMESTAMP_MICROS(CAST(NOW() AS VARCHAR)) AS "tmp"
SELECT * FROM (SELECT * FROM "functional_alltypes" AS "t0" WHERE "t0"."id" < 100) AS "t1" ORDER BY RANDOM() ASC LIMIT 5
SELECT ROUND(5.5) AS "tmp"
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') < ARROW_CAST('2010-03-02 00:00:00.000123', 'Timestamp(Microsecond, None)')
SELECT 1.3 IS NOT NULL AND ISNAN(1.3) AS "tmp"
SELECT CAST(CONCAT_WS('-', CASE WHEN '20' IS NULL OR ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 2 + CAST(2 >= 0 AS SMALLINT)) IS NULL THEN CAST(NULL AS VARCHAR) ELSE CONCAT('20', ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 2 + CAST(2 >= 0 AS SMALLINT))) END, ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 0 + CAST(0 >= 0 AS SMALLINT)), ARRAY_ELEMENT(STRING_TO_ARRAY("t0"."date_string_col", '/'), 1 + CAST(1 >= 0 AS SMALLINT))) AS DATE) + CAST(CONCAT(CAST("t0"."int_col" AS VARCHAR), ' week') AS INTERVAL) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."int_col" | "t0"."int_col" AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE (DATE_PART('dow', CAST('2017-01-01' AS DATE)) + 6) % 7 WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday' WHEN 5 THEN 'Saturday' WHEN 6 THEN 'Sunday' END AS "tmp"
SELECT (DATE_PART('dow', "t0"."timestamp_col") + 6) % 7 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id", "t0"."int_col" IN (1, 2, 3) AS "tmp" FROM "functional_alltypes" AS "t0" ORDER BY "t0"."id" ASC
SELECT * FROM "functional_alltypes"
SELECT CASE (DATE_PART('dow', CAST('2017-01-04' AS DATE)) + 6) % 7 WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday' WHEN 5 THEN 'Saturday' WHEN 6 THEN 'Sunday' END AS "tmp"
SELECT * FROM (SELECT "t0"."string_col", SUM("t0"."int_col") AS "sum(int_col)" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."string_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."string_col") AS "t1" ORDER BY "t1"."string_col" ASC
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') > ARROW_CAST('2010-03-02 00:00:00+00:00', 'Timestamp(Microsecond, Some("UTC"))')
SELECT DATE_BIN(INTERVAL '5 MINUTES', "t0"."timestamp_col", ARROW_CAST('1970-01-01T00:00:00Z', 'Timestamp(Nanosecond, None)') - INTERVAL '-3 MINUTES') AS "TimestampBucket(timestamp_col, 5m, -2m)" FROM "functional_alltypes" AS "t0"
SELECT * FROM "functional_alltypes" AS "t0" WHERE NOT ("t0"."bool_col") ORDER BY "t0"."id" ASC
SELECT NULLIF(5, 5) AS "NullIf(5, 5)"
SELECT 2 | 4 AS "BitwiseOr(2, 4)"
SELECT COALESCE(NULL, NULL, 3.14) AS "tmp"
SELECT TO_TIMESTAMP_MICROS(CAST(NOW() AS VARCHAR)) AS "now" FROM "functional_alltypes" AS "t0" LIMIT 2
SELECT RADIANS(5.556) AS "tmp"
SELECT * FROM "functional_alltypes" AS "t0" WHERE ARROW_CAST("t0"."timestamp_col", 'Timestamp(Microsecond, Some("UTC"))') > ARROW_CAST('2010-03-02 00:00:00.000123', 'Timestamp(Microsecond, None)')
SELECT FALSE AS "tmp"
SELECT ARROW_CAST('2023-01-07 13:20:05.561000231', 'Timestamp(Nanosecond, None)') AS "Cast('2023-01-07 13:20:05.561000231', timestamp(9))"
SELECT CASE WHEN TRUE THEN '%' ELSE NULL END AS "IfElse(True, '%', None)"
SELECT ARROW_CAST('2023-01-07 13:20:05.561021', 'Timestamp(Microsecond, None)') AS "Cast('2023-01-07 13:20:05.561021', timestamp(6))"
SELECT LEAST("t0"."bigint_col", "t0"."int_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT EXP("t0"."double_col" + 1) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CAST(NULL AS SMALLINT) AS "None"
SELECT * FROM "functional_alltypes" AS "t0" ORDER BY "t0"."id" ASC LIMIT 10
SELECT ARROW_TYPEOF(FALSE) AS "TypeOf(False)"
SELECT "t0"."date_string_col" FROM "functional_alltypes" AS "t0" LIMIT 11
SELECT DATE_PART('year', CAST("t0"."timestamp_col" AS DATE)) AS "year" FROM "functional_alltypes" AS "t0"
SELECT "t0"."id" + 0 AS "c_0", "t0"."id" + 1 AS "c_1", "t0"."id" + 2 AS "c_2", "t0"."id" + 3 AS "c_3", "t0"."id" + 4 AS "c_4", "t0"."id" + 5 AS "c_5", "t0"."id" + 6 AS "c_6", "t0"."id" + 7 AS "c_7", "t0"."id" + 8 AS "c_8", "t0"."id" + 9 AS "c_9", "t0"."id" + 10 AS "c_10", "t0"."id" + 11 AS "c_11" FROM "functional_alltypes" AS "t0" LIMIT 11
SELECT RANDOM() AS "RandomScalar()"
SELECT CASE (DATE_PART('dow', "t0"."timestamp_col") + 6) % 7 WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday' WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday' WHEN 5 THEN 'Saturday' WHEN 6 THEN 'Sunday' END AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT CASE WHEN "t0"."int_col" > 0 THEN 0 ELSE "t0"."int_col" END AS "Clip(int_col, 0)" FROM "functional_alltypes" AS "t0"
SELECT CAST('NaN' AS DOUBLE PRECISION) AS "nan_col", CAST(NULL AS DOUBLE PRECISION) AS "none_col" FROM "functional_alltypes" AS "t0" WHERE CAST('NaN' AS DOUBLE PRECISION) IS NOT NULL AND ISNAN(CAST('NaN' AS DOUBLE PRECISION))
SELECT CASE WHEN "t0"."int_col" = 2 THEN NULL ELSE "t0"."float_col" END AS "col_1", CASE WHEN "t0"."int_col" = 4 THEN NULL ELSE "t0"."float_col" END AS "col_2", CASE WHEN ("t0"."int_col" = 2) OR ("t0"."int_col" = 4) THEN NULL ELSE "t0"."float_col" END AS "col_3" FROM "functional_alltypes" AS "t0"
SELECT DATE_TRUNC('DAY', "t0"."timestamp_col") AS "result" FROM "functional_alltypes" AS "t0"
SELECT CAST("t0"."int_col" AS DOUBLE PRECISION) / 0.0 AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT NOT (FALSE) AS "tmp"
SELECT COT(1.0) AS "tmp"
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" INNER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" LEFT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" RIGHT OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON TRUE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
WITH "t1" AS (SELECT * FROM "awards_players" AS "t0" LIMIT 5) SELECT "t5"."left_key", "t6"."right_key" FROM (SELECT "t2"."playerID" AS "left_key" FROM "t1" AS "t2") AS "t5" FULL OUTER JOIN (SELECT "t2"."playerID" AS "right_key" FROM "t1" AS "t2") AS "t6" ON FALSE
SELECT * FROM "functional_alltypes"
SELECT AVG("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT MIN("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT MAX("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT SUM("t0"."double_col" + 5) AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT MAX("t0"."timestamp_col") AS "tmp" FROM "functional_alltypes" AS "t0"
SELECT "t0"."bigint_col", AVG("t0"."double_col") AS "tmp" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."bigint_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."bigint_col"
SELECT "t0"."bigint_col", MIN("t0"."double_col") AS "tmp" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."bigint_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."bigint_col"
SELECT "t0"."bigint_col", MIN("t0"."double_col") AS "tmp" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."bigint_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."bigint_col"
SELECT "t0"."bigint_col", MAX("t0"."double_col") AS "tmp" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."bigint_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."bigint_col"
SELECT "t0"."bigint_col", MAX("t0"."double_col") AS "tmp" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."bigint_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."bigint_col"
SELECT "t0"."bigint_col", SUM("t0"."double_col" + 5) AS "tmp" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."bigint_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."bigint_col"
SELECT "t0"."bigint_col", SUM("t0"."double_col" + 5) AS "tmp" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."bigint_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."bigint_col"
SELECT "t0"."bigint_col", MAX("t0"."timestamp_col") AS "tmp" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."bigint_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."bigint_col"
SELECT "t0"."bigint_col", MAX("t0"."timestamp_col") AS "tmp" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", "t0"."bigint_col" FROM "functional_alltypes" AS "t0") AS t0 GROUP BY "t0"."bigint_col"
SELECT * FROM (SELECT COUNT("t0"."bool_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT COUNT(DISTINCT "t0"."bool_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT BOOL_OR("t0"."bool_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT NOT (BOOL_OR("t0"."bool_col")) AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT NOT (BOOL_OR("t0"."bool_col")) AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT BOOL_AND("t0"."bool_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT NOT (BOOL_AND("t0"."bool_col")) AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT NOT (BOOL_AND("t0"."bool_col")) AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT SUM("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT SUM(CAST("t0"."int_col" > 0 AS INT)) AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT AVG("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT MIN("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT MAX("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT STDDEV_SAMP("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT VAR_SAMP("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT STDDEV_POP("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT VAR_POP("t0"."double_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM (SELECT COUNT(DISTINCT "t0"."string_col") AS "tmp" FROM "functional_alltypes" AS "t0") AS "t1"
SELECT * FROM "batting"
SELECT COVAR_POP("t0"."G", "t0"."RBI") AS "tmp" FROM "batting" AS "t0"
SELECT COVAR_SAMP("t0"."G", "t0"."RBI") AS "tmp" FROM "batting" AS "t0"
SELECT CORR("t0"."G", "t0"."RBI") AS "tmp" FROM "batting" AS "t0"
SELECT CORR("t0"."G", "t0"."RBI") AS "tmp" FROM "batting" AS "t0"
SELECT COVAR_POP(CAST("t0"."G" > 34.0 AS DOUBLE PRECISION), CAST("t0"."G" <= 34.0 AS DOUBLE PRECISION)) AS "tmp" FROM "batting" AS "t0"
SELECT CORR(CAST("t0"."G" > 34.0 AS DOUBLE PRECISION), CAST("t0"."G" <= 34.0 AS DOUBLE PRECISION)) AS "tmp" FROM "batting" AS "t0"
SELECT APPROX_MEDIAN("t0"."double_col") AS "ApproxMedian(double_col)" FROM "functional_alltypes" AS "t0"
SELECT MEDIAN("t0"."double_col") AS "Median(double_col)" FROM "functional_alltypes" AS "t0"
SELECT * FROM (SELECT "t1"."string_col", COUNT(*) AS "CountStar()" FROM (SELECT "t1"."id", "t1"."bool_col", "t1"."tinyint_col", "t1"."smallint_col", "t1"."int_col", "t1"."bigint_col", "t1"."float_col", "t1"."double_col", "t1"."date_string_col", "t1"."timestamp_col", "t1"."year", "t1"."month", "t1"."string_col" FROM (SELECT * FROM "functional_alltypes" AS "t0" ORDER BY "t0"."string_col" ASC) AS "t1") AS t1 GROUP BY "t1"."string_col") AS "t2" ORDER BY "t2"."CountStar()" DESC NULLS LAST LIMIT 3
WITH "t1" AS (SELECT * FROM "functional_alltypes" AS "t0" ORDER BY "t0"."string_col" ASC) SELECT "t3"."id", "t3"."bool_col", "t3"."tinyint_col", "t3"."smallint_col", "t3"."int_col", "t3"."bigint_col", "t3"."float_col", "t3"."double_col", "t3"."date_string_col", "t3"."string_col", "t3"."timestamp_col", "t3"."year", "t3"."month" FROM "t1" AS "t3" LEFT SEMI JOIN (SELECT * FROM (SELECT "t2"."string_col", COUNT(*) AS "CountStar()" FROM (SELECT "t2"."id", "t2"."bool_col", "t2"."tinyint_col", "t2"."smallint_col", "t2"."int_col", "t2"."bigint_col", "t2"."float_col", "t2"."double_col", "t2"."date_string_col", "t2"."timestamp_col", "t2"."year", "t2"."month", "t2"."string_col" FROM "t1" AS "t2") AS t2 GROUP BY "t2"."string_col") AS "t4" ORDER BY "t4"."CountStar()" DESC NULLS LAST LIMIT 3) AS "t7" ON "t3"."string_col" = "t7"."string_col"
SELECT SUM(CASE "t0"."string_col" WHEN '1-URGENT' THEN 1 ELSE 0 END) AS "high_line_count" FROM "functional_alltypes" AS "t0"
SELECT "t1"."x", SUM("t1"."double_col") AS "sum" FROM (SELECT "t1"."id", "t1"."bool_col", "t1"."tinyint_col", "t1"."smallint_col", "t1"."int_col", "t1"."bigint_col", "t1"."float_col", "t1"."double_col", "t1"."date_string_col", "t1"."string_col", "t1"."timestamp_col", "t1"."year", "t1"."month", "t1"."x" FROM (SELECT "t0"."id", "t0"."bool_col", "t0"."tinyint_col", "t0"."smallint_col", "t0"."int_col", "t0"."bigint_col", "t0"."float_col", "t0"."double_col", "t0"."date_string_col", "t0"."string_col", "t0"."timestamp_col", "t0"."year", "t0"."month", 1 AS "x" FROM "functional_alltypes" AS "t0" WHERE "t0"."string_col" = '1') AS "t1") AS t1 GROUP BY "t1"."x"
SELECT MIN("t0"."int_col") AS "Min(int_col)", MAX("t0"."int_col") AS "Max(int_col)" FROM "functional_alltypes" AS "t0"
SELECT * FROM (SELECT "t1"."Add(bigint_col, 1)", COUNT(*) AS "Add(bigint_col, 1)_count" FROM (SELECT "t1"."Add(bigint_col, 1)" FROM (SELECT "t0"."bigint_col" + 1 AS "Add(bigint_col, 1)" FROM "functional_alltypes" AS "t0") AS "t1") AS t1 GROUP BY "t1"."Add(bigint_col, 1)") AS "t2" ORDER BY "t2"."Add(bigint_col, 1)" ASC, "t2"."Add(bigint_col, 1)_count" ASC